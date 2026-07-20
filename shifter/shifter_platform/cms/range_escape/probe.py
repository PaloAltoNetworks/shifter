"""The in-guest escape probe program and its record parser (issue #1347).

The probe is a bounded, unprivileged, non-mutating shell program executed in
participant context by a probe-launch adapter. ``render_probe_program`` embeds the
bounded target spec directly in the program (via a quoted heredoc) so the whole
thing can be delivered over a single ``bash -s`` for a native VM or
``docker exec -i <container> bash -s`` for a scenario container.

Each probe emits a distinct :class:`ObservedProbe` outcome so the gate never
mistakes "I could not test" for "the boundary blocked me":

- ``blocked``   - the attempt timed out / was silently dropped (the secure signal)
- ``refused``   - the target host answered with a reset: the network path reached it
- ``reachable`` - a connection or resolution succeeded
- ``error``     - a required tool was missing or the attempt could not run

Nothing is installed, mutated, or left behind, and the metadata probe records only
whether a *useful* credential was returned, never the credential itself.

``parse_probe_record`` reads the emitted JSON envelope back into
:class:`ObservedProbe` values. It is the tested seam, and a companion test executes
the rendered program end-to-end against controlled targets.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from cms.range_escape.model import ObservedProbe, ProbeOutcome, ProbeTarget, spec_entry_from_target

_RECORD_START = "__ESCAPE_RECORD__"
_RECORD_END = "__END__"
_SPEC_DELIMITER = "__ESC_SPEC__"
# Probe target fields are data, not shell. Only IP/hostname/id-shaped characters
# are permitted; anything else (pipe, whitespace, newline, shell metacharacters,
# the heredoc delimiter) is rejected before the spec is rendered, so a target
# value cannot break the spec line format or the delimiter, or reach a shell.
_SAFE_FIELD = re.compile(r"^[A-Za-z0-9._:\-]*$")

# The bounded probe body. Reads the embedded ``$SPEC`` (one target per line:
# check_id|kind|address|port|hostname), attempts each with a hard timeout, and
# prints a single JSON envelope keyed by check id. A missing tool is an ``error``,
# a silent drop is ``blocked``, a reset is ``refused``, and success is
# ``reachable``, so a broken probe can never read as secure.
_PROBE_BODY = r"""set -u
T="${ESCAPE_PROBE_TIMEOUT:-4}"
first=1
printf '%s' "__ESCAPE_RECORD__{"

emit() {
  local cid="$1" outcome="$2" detail="$3" useful="${4:--}"
  local ubool="null"; [ "$useful" = "1" ] && ubool="true"; [ "$useful" = "0" ] && ubool="false"
  detail="${detail//\"/}"; detail="${detail//\\/}"
  [ "$first" = "1" ] || printf ','
  first=0
  printf '"%s":{"outcome":"%s","detail":"%s","metadata_credentials_useful":%s}' \
    "$cid" "$outcome" "$detail" "$ubool"
}

have() { command -v "$1" >/dev/null 2>&1; }

tcp_probe() {
  local addr="$1" port="$2"
  if ! have timeout || ! have bash; then echo error; return; fi
  # addr/port are passed as positional args to a single-quoted program, so target
  # values are data, never shell code (no injection even if validation is bypassed).
  timeout "$T" bash -c 'exec 3<>/dev/tcp/"$1"/"$2"' _ "$addr" "$port" 2>/dev/null
  local rc=$?
  if [ "$rc" = "0" ]; then echo reachable
  elif [ "$rc" = "124" ]; then echo blocked
  else echo refused
  fi
}

while IFS='|' read -r cid kind addr port host; do
  [ -z "${cid:-}" ] && continue
  case "$kind" in
    tcp_connect)
      emit "$cid" "$(tcp_probe "$addr" "$port")" "tcp ${addr}:${port}"
      ;;
    dns_resolve)
      if ! have getent; then
        emit "$cid" error "getent missing"
      elif getent hosts "$host" >/dev/null 2>&1; then
        emit "$cid" reachable "resolved ${host}"
      else
        emit "$cid" blocked "no route for ${host}"
      fi
      ;;
    metadata)
      if ! have curl; then
        emit "$cid" error "curl missing"
      else
        code=$(curl -s -m "$T" -o /tmp/.esc_md -w '%{http_code}' \
          -H 'Metadata-Flavor: Google' \
          "http://${addr}/computeMetadata/v1/instance/service-accounts/default/token" 2>/dev/null)
        rc=$?
        if [ -z "$code" ] || [ "$code" = "000" ]; then
          if [ "$rc" = "7" ]; then
            emit "$cid" refused "metadata refused"
          else
            emit "$cid" blocked "metadata unreachable"
          fi
        else
          useful=0
          grep -q 'access_token' /tmp/.esc_md 2>/dev/null && useful=1
          emit "$cid" reachable "metadata http ${code}" "$useful"
        fi
        rm -f /tmp/.esc_md 2>/dev/null || true
      fi
      ;;
    *)
      emit "$cid" error "unknown probe kind"
      ;;
  esac
done <<< "$SPEC"

printf '}%s\n' "__END__"
"""


def render_probe_program(targets: Sequence[ProbeTarget], *, per_target_timeout_s: int = 4) -> str:
    """Render the self-contained probe program with the target spec embedded.

    ``per_target_timeout_s`` is the bounded per-attempt timeout the probe applies to
    each target; it is validated as an integer and embedded, so the transport-level
    timeout can be sized separately from the per-probe budget. Every string target
    field is validated against a strict allowlist and unsafe values raise, so target
    data can never break the spec format or reach a shell.
    """
    timeout = int(per_target_timeout_s)
    if timeout <= 0:
        raise ValueError("per_target_timeout_s must be a positive integer")
    spec_lines = []
    for target in targets:
        entry = spec_entry_from_target(target)
        _require_safe("check_id", entry.check_id)
        _require_safe("kind", entry.kind)
        _require_safe("address", entry.address)
        _require_safe("hostname", entry.hostname)
        spec_lines.append(f"{entry.check_id}|{entry.kind}|{entry.address}|{int(entry.port)}|{entry.hostname}")
    spec_block = "\n".join(spec_lines)
    # Load the spec with the ``read`` builtin (not ``cat``) so the spec is still
    # delivered when PATH is empty; a missing external tool must surface as a
    # per-check ``error``, not silently drop every check.
    return (
        "#!/bin/bash\n"
        f"ESCAPE_PROBE_TIMEOUT={timeout}\n"
        f"IFS='' read -r -d '' SPEC <<'{_SPEC_DELIMITER}' || true\n"
        f"{spec_block}\n{_SPEC_DELIMITER}\n{_PROBE_BODY}"
    )


def _require_safe(field_name: str, value: str) -> None:
    """Raise if a probe target field contains anything but IP/hostname/id characters."""
    if not _SAFE_FIELD.match(value):
        raise ValueError(f"unsafe probe target {field_name!r}: only IP/hostname/id characters are allowed")


def parse_probe_record(stdout: str) -> dict[str, ObservedProbe]:
    """Parse the ``__ESCAPE_RECORD__{json}__END__`` envelope into observations.

    Returns an empty mapping when the envelope is absent or malformed; the runner
    treats a missing observation for a target as a fail-closed result. An
    unrecognized outcome value is coerced to ``error`` (never a pass).
    """
    raw = _extract_record_json(stdout)
    record: dict[str, ObservedProbe] = {}
    if isinstance(raw, dict):
        for check_id, value in raw.items():
            if isinstance(value, dict):
                record[str(check_id)] = ObservedProbe(
                    outcome=_parse_outcome(value.get("outcome")),
                    detail=str(value.get("detail", "")),
                    metadata_credentials_useful=_optional_bool(value.get("metadata_credentials_useful")),
                )
    return record


def _extract_record_json(stdout: str) -> object:
    """Return the parsed JSON body of the record envelope, or None if absent/malformed."""
    start = stdout.find(_RECORD_START)
    end = stdout.find(_RECORD_END, start + len(_RECORD_START)) if start != -1 else -1
    if start == -1 or end == -1:
        return None
    body = stdout[start + len(_RECORD_START) : end]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _parse_outcome(value: object) -> ProbeOutcome:
    """Parse an outcome string, coercing anything unrecognized to ``error``."""
    outcome = ProbeOutcome.ERROR
    if isinstance(value, str):
        try:
            outcome = ProbeOutcome(value)
        except ValueError:
            outcome = ProbeOutcome.ERROR
    return outcome


def _optional_bool(value: object) -> bool | None:
    """Return None for a null value, else the value coerced to bool."""
    if value is None:
        return None
    return bool(value)


__all__ = ["parse_probe_record", "render_probe_program"]
