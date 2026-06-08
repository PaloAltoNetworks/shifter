"""Unit tests for the pre-event scenario smoketest harness.

Run with the repo test venv:
    python -m pytest scenario-dev/polaris/tests/test_scenario_smoketest.py
"""

import json
from pathlib import Path

import pytest

from scenario_smoketest import __main__ as cli
from scenario_smoketest import board, compare, ctfd_check, report, run, runner
from scenario_smoketest.adapters import (
    ADAPTERS,
    Adapter,
    AdapterContext,
    Produced,
    register,
)

REPO_CHALLENGES = (
    Path(__file__).resolve().parents[1] / "build" / "ctfd-challenges.json"
)


# --------------------------------------------------------------------------
# board
# --------------------------------------------------------------------------


def _board_file(tmp_path, challenges, meta=None):
    path = tmp_path / "ctfd-challenges.json"
    payload = {"challenges": challenges}
    if meta is not None:
        payload["meta"] = meta
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_board_parses_challenges(tmp_path):
    path = _board_file(
        tmp_path,
        [
            {
                "id": 1,
                "name": "Company Info",
                "category": "Mission 1",
                "flags": [{"type": "static", "content": "FLAG{aaaa1111}"}],
            }
        ],
    )
    challenges = board.load_board(path)
    assert len(challenges) == 1
    assert challenges[0].id == 1
    assert challenges[0].name == "Company Info"
    assert challenges[0].static_flag == "FLAG{aaaa1111}"


def test_load_board_marks_missing_static_flag(tmp_path):
    path = _board_file(
        tmp_path,
        [{"id": 2, "name": "No Flag", "category": "M1", "flags": []}],
    )
    challenges = board.load_board(path)
    assert challenges[0].static_flag is None


def test_load_board_marks_multiple_static_flags(tmp_path):
    path = _board_file(
        tmp_path,
        [
            {
                "id": 3,
                "name": "Two Flags",
                "category": "M1",
                "flags": [
                    {"type": "static", "content": "FLAG{a}"},
                    {"type": "static", "content": "FLAG{b}"},
                ],
            }
        ],
    )
    challenges = board.load_board(path)
    # Fail closed: ambiguous static flag set is not a usable comparison target.
    assert challenges[0].static_flag is None


def test_load_board_merges_onboarding(tmp_path):
    challenges_path = _board_file(
        tmp_path, [{"id": 1, "name": "C1", "category": "M1", "flags": []}]
    )
    onboarding_path = tmp_path / "ctfd-onboarding.json"
    onboarding_path.write_text(
        json.dumps(
            {"challenges": [{"id": 99, "name": "Start Here", "category": "Onboarding", "flags": []}]}
        ),
        encoding="utf-8",
    )
    challenges = board.load_board(challenges_path, onboarding_path)
    assert {c.id for c in challenges} == {1, 99}


def test_load_board_rejects_duplicate_ids(tmp_path):
    path = _board_file(
        tmp_path,
        [
            {"id": 1, "name": "A", "category": "M1", "flags": []},
            {"id": 1, "name": "B", "category": "M1", "flags": []},
        ],
    )
    with pytest.raises(ValueError):
        board.load_board(path)


def test_load_board_rejects_missing_challenges_key(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"meta": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        board.load_board(path)


@pytest.mark.skipif(
    not REPO_CHALLENGES.exists(),
    reason="ctfd-challenges.json is a build artifact; run the board build first",
)
def test_load_board_real_repo_board():
    challenges = board.load_board(REPO_CHALLENGES)
    assert len(challenges) >= 54
    assert all(isinstance(c.id, int) for c in challenges)


# --------------------------------------------------------------------------
# compare / redaction
# --------------------------------------------------------------------------


def test_redact_never_emits_raw_value():
    redacted = compare.redact("FLAG{c6f8d2b3e91a4507}")
    assert "c6f8d2b3e91a4507" not in redacted
    assert redacted != "FLAG{c6f8d2b3e91a4507}"


def test_redact_is_stable():
    assert compare.redact("FLAG{x}") == compare.redact("FLAG{x}")


def test_redact_empty():
    assert compare.redact(None) == "<none>"
    assert compare.redact("") == "<empty>"


def test_compare_flag_match():
    result = compare.compare("FLAG{abcd}", "FLAG{abcd}", "flag")
    assert result.status == "pass"


def test_compare_flag_mismatch():
    result = compare.compare("FLAG{abcd}", "FLAG{wxyz}", "flag")
    assert result.status == "fail"
    # Raw flag bodies must never appear in comparison detail.
    assert "abcd" not in result.detail
    assert "wxyz" not in result.detail


def test_compare_flag_missing_expected():
    result = compare.compare("FLAG{abcd}", None, "flag")
    assert result.status == "fail"
    assert "no configured static flag" in result.detail.lower()


def test_compare_flag_missing_produced():
    result = compare.compare(None, "FLAG{abcd}", "flag")
    assert result.status == "fail"


def test_compare_answer_match():
    result = compare.compare("AHS-TAIL-7741", "AHS-TAIL-7741", "answer")
    assert result.status == "pass"


def test_compare_answer_mismatch():
    result = compare.compare("WRONG", "AHS-TAIL-7741", "answer")
    assert result.status == "fail"
    assert "AHS-TAIL-7741" not in result.detail


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------


def test_runner_builds_docker_exec_argv():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return runner.ExecResult(0, "ok", "")

    r = runner.Runner(runner_run=fake_run)
    result = r.exec("a14-kali", ["curl", "-s", "http://example"])
    assert result.returncode == 0
    assert calls[0][:3] == ["docker", "exec", "a14-kali"]
    assert calls[0][3:] == ["curl", "-s", "http://example"]


def test_runner_rejects_string_argv():
    r = runner.Runner(runner_run=lambda *a, **k: runner.ExecResult(0, "", ""))
    with pytest.raises(TypeError):
        r.exec("a14-kali", "curl http://example")


def test_runner_rejects_bad_container_name():
    r = runner.Runner(runner_run=lambda *a, **k: runner.ExecResult(0, "", ""))
    with pytest.raises(ValueError):
        r.exec("a14 kali; rm -rf /", ["echo", "hi"])


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------


class FakeRunner:
    """Stand-in for Runner that returns canned output per (container, argv)."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def exec(self, container, argv, **kwargs):
        self.calls.append((container, tuple(argv)))
        key = (container, tuple(argv))
        if key in self._responses:
            return self._responses[key]
        # Match on a prefix of argv so tests need not pin every flag.
        for (rc, rargv), value in self._responses.items():
            if rc == container and tuple(argv)[: len(rargv)] == rargv:
                return value
        return runner.ExecResult(0, "", "")


def test_adapter_context_carries_runner():
    fr = FakeRunner({})
    ctx = AdapterContext(runner=fr, hosts={"a0": "boreas-systems.ctf"})
    assert ctx.runner is fr
    assert ctx.host("a0") == "boreas-systems.ctf"


def test_registered_adapters_have_consistent_metadata():
    from scenario_smoketest.adapters import ADAPTERS

    for challenge_id, adapter in ADAPTERS.items():
        assert adapter.challenge_id == challenge_id
        assert adapter.value_kind in ("flag", "answer")
        assert callable(adapter.solve)
        if adapter.value_kind == "answer":
            assert adapter.expected_answer, challenge_id


# The exact argv challenge 1's adapter issues against the A0 site. Keying
# FakeRunner on the full argv (not a bare ("curl",) prefix) means a URL or
# flag regression in the adapter breaks the match and fails the test.
CHALLENGE_1_HOSTS = {"a0": "boreas-systems.ctf"}
CHALLENGE_1_CURL_ARGV = (
    "curl", "-s", "http://boreas-systems.ctf/about.html",
)


def test_adapter_challenge_1_extracts_flag_from_about_page():
    from scenario_smoketest.adapters import ADAPTERS

    adapter = ADAPTERS[1]
    html = (
        '<table><tr><td>Reg</td><td>7741-BSI-2018</td></tr></table>'
        "<!-- FLAG{8f3a2c1e9b7d4056} -->"
    )
    fr = FakeRunner(
        {("a14-kali", CHALLENGE_1_CURL_ARGV): runner.ExecResult(0, html, "")}
    )
    ctx = AdapterContext(runner=fr, hosts=dict(CHALLENGE_1_HOSTS))
    produced = adapter.solve(ctx)
    assert produced.value == "FLAG{8f3a2c1e9b7d4056}"
    assert produced.kind == "flag"


def test_adapter_returns_none_when_flag_absent():
    from scenario_smoketest.adapters import ADAPTERS

    adapter = ADAPTERS[1]
    fr = FakeRunner(
        {
            ("a14-kali", CHALLENGE_1_CURL_ARGV): runner.ExecResult(
                0, "<html>no flag</html>", ""
            )
        }
    )
    ctx = AdapterContext(runner=fr, hosts=dict(CHALLENGE_1_HOSTS))
    produced = adapter.solve(ctx)
    assert produced.value is None


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def test_report_aggregate_exit_code_all_pass():
    results = [
        report.ChallengeResult(1, "C1", "pass", "ok"),
        report.ChallengeResult(2, "C2", "pass", "ok"),
    ]
    assert report.aggregate_exit_code(results) == 0


def test_report_aggregate_exit_code_any_fail():
    results = [
        report.ChallengeResult(1, "C1", "pass", "ok"),
        report.ChallengeResult(2, "C2", "fail", "mismatch"),
    ]
    assert report.aggregate_exit_code(results) != 0


def test_report_aggregate_exit_code_uncovered_fails():
    results = [report.ChallengeResult(1, "C1", "uncovered", "no adapter")]
    assert report.aggregate_exit_code(results) != 0


def test_report_text_has_no_raw_flag():
    raw_flag_body = "c6f8d2b3e91a4507"
    # Mirror the real harness: run.run_smoketest sets detail from
    # compare.compare(), which redacts before the value ever reaches a
    # ChallengeResult. Feed build_report a detail produced that same way.
    verdict = compare.compare(f"FLAG{{{raw_flag_body}}}", "FLAG{wxyz}", "flag")
    assert verdict.status == "fail"
    assert raw_flag_body not in verdict.detail  # compare's contract holds
    results = [
        report.ChallengeResult(6, "Follow the Money", "fail", verdict.detail)
    ]
    rendered = report.build_report(results)
    assert "Follow the Money" in rendered
    assert "6" in rendered
    # The whole point of this test: a raw flag body must never survive into
    # the rendered report. build_report renders detail verbatim, so a
    # redaction failure anywhere upstream would surface here.
    assert raw_flag_body not in rendered


def test_report_json_roundtrip():
    results = [report.ChallengeResult(1, "C1", "pass", "ok")]
    payload = report.to_json(results)
    assert payload[0]["challenge_id"] == 1
    assert payload[0]["status"] == "pass"


def test_report_counts_summary():
    results = [
        report.ChallengeResult(1, "C1", "pass", ""),
        report.ChallengeResult(2, "C2", "fail", ""),
        report.ChallengeResult(3, "C3", "uncovered", ""),
    ]
    summary = report.summarize(results)
    assert summary["pass"] == 1
    assert summary["fail"] == 1
    assert summary["uncovered"] == 1
    assert summary["total"] == 3


# --------------------------------------------------------------------------
# ctfd_check
# --------------------------------------------------------------------------


class FakeCtfdClient:
    """Minimal CtfdClient stand-in driven by a path -> payload map."""

    def __init__(self, pages):
        self._pages = pages
        self.requests = []

    def get(self, path, query=None):
        self.requests.append((path, query))
        return self._pages[(path, _freeze(query))]


def _freeze(query):
    if not query:
        return None
    return tuple(sorted(query.items()))


def test_ctfd_check_flags_passes_when_all_present():
    client = FakeCtfdClient(
        {
            ("/challenges", _freeze({"page": 1})): {
                "data": [{"id": 1}, {"id": 2}],
                "meta": {"pagination": {"next": None}},
            },
            ("/challenges/1/flags", None): {"data": [{"id": 10, "type": "static"}]},
            ("/challenges/2/flags", None): {"data": [{"id": 11, "type": "static"}]},
        }
    )
    results = ctfd_check.check_flags(client)
    assert all(r.has_flags for r in results)
    assert ctfd_check.exit_code(results) == 0


def test_ctfd_check_flags_detects_empty_flag_rows():
    client = FakeCtfdClient(
        {
            ("/challenges", _freeze({"page": 1})): {
                "data": [{"id": 1}, {"id": 2}],
                "meta": {"pagination": {"next": None}},
            },
            ("/challenges/1/flags", None): {"data": [{"id": 10}]},
            ("/challenges/2/flags", None): {"data": []},
        }
    )
    results = ctfd_check.check_flags(client)
    by_id = {r.challenge_id: r for r in results}
    assert by_id[1].has_flags is True
    assert by_id[2].has_flags is False
    assert ctfd_check.exit_code(results) != 0


def test_ctfd_check_flags_follows_pagination():
    client = FakeCtfdClient(
        {
            ("/challenges", _freeze({"page": 1})): {
                "data": [{"id": 1}],
                "meta": {"pagination": {"next": 2}},
            },
            ("/challenges", _freeze({"page": 2})): {
                "data": [{"id": 2}],
                "meta": {"pagination": {"next": None}},
            },
            ("/challenges/1/flags", None): {"data": [{"id": 10}]},
            ("/challenges/2/flags", None): {"data": [{"id": 11}]},
        }
    )
    results = ctfd_check.check_flags(client)
    assert {r.challenge_id for r in results} == {1, 2}


# --------------------------------------------------------------------------
# run (orchestration)
# --------------------------------------------------------------------------


def _challenge(cid, name="C", category="M", static_flag="FLAG{x}"):
    return board.Challenge(cid, name, category, static_flag)


def test_run_marks_uncovered_challenge():
    # Challenge id 9001 has no adapter registered.
    results = run.run_smoketest([_challenge(9001)], FakeRunner({}), hosts={})
    assert results[0].status == "uncovered"


def test_run_passes_when_adapter_matches_board_flag(tmp_path):
    fr = FakeRunner(
        {
            ("a14-kali", CHALLENGE_1_CURL_ARGV): runner.ExecResult(
                0, "<!-- FLAG{abc123} -->", ""
            )
        }
    )
    challenges = [_challenge(1, name="Company Info", static_flag="FLAG{abc123}")]
    results = run.run_smoketest(
        challenges, fr, hosts=dict(CHALLENGE_1_HOSTS)
    )
    assert results[0].status == "pass"


def test_run_fails_when_adapter_value_drifts_from_board(tmp_path):
    fr = FakeRunner(
        {
            ("a14-kali", CHALLENGE_1_CURL_ARGV): runner.ExecResult(
                0, "<!-- FLAG{aaa111} -->", ""
            )
        }
    )
    challenges = [_challenge(1, static_flag="FLAG{bbb222}")]
    results = run.run_smoketest(
        challenges, fr, hosts=dict(CHALLENGE_1_HOSTS)
    )
    assert results[0].status == "fail"
    # No raw flag bodies leak into the result detail.
    assert "aaa111" not in results[0].detail
    assert "bbb222" not in results[0].detail


def test_run_catches_adapter_exception():
    class Boom:
        def exec(self, *a, **k):
            raise RuntimeError("network down")

    results = run.run_smoketest(
        [_challenge(1, static_flag="FLAG{x}")], Boom(), hosts={"a0": "h"}
    )
    assert results[0].status == "error"
    assert "network down" not in results[0].detail  # exception body not leaked


def test_run_filters_by_challenge_id():
    results = run.run_smoketest(
        [_challenge(1, static_flag="FLAG{x}"), _challenge(2, static_flag="FLAG{y}")],
        FakeRunner({}),
        hosts={"a0": "h"},
        only_ids={2},
    )
    assert {r.challenge_id for r in results} == {2}


def test_run_answer_kind_compares_against_expected_answer():
    register_id = 9100

    @register(register_id, runner="a9-splice", value_kind="answer",
              expected_answer="MODEL-A")
    def _adapter(ctx):
        return Produced("MODEL-A", "answer", "device id probe")

    try:
        results = run.run_smoketest(
            [_challenge(register_id, static_flag="FLAG{unrelated}")],
            FakeRunner({}),
            hosts={},
        )
        assert results[0].status == "pass"
    finally:
        ADAPTERS.pop(register_id, None)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_parse_host_overrides_merges_defaults():
    hosts = cli._parse_host_overrides(["a0=example.ctf"])
    assert hosts["a0"] == "example.ctf"
    # Built-in defaults survive a partial override.
    assert "a3" in hosts


def test_cli_parse_host_overrides_rejects_bad_pair():
    with pytest.raises(SystemExit):
        cli._parse_host_overrides(["nopair"])


def test_cli_uncovered_only_returns_failure(tmp_path, capsys):
    # An uncovered challenge id needs no docker; the CLI still reports failure.
    path = _board_file(
        tmp_path, [{"id": 9001, "name": "Ghost", "category": "M", "flags": []}]
    )
    code = cli.main(["--challenges", str(path), "--only", "9001"])
    assert code == 1
    assert "UNCOVERED" in capsys.readouterr().out


def test_cli_skip_range_with_no_ctfd_is_clean():
    assert cli.main(["--skip-range"]) == 0


# --------------------------------------------------------------------------
# mission 5 (Bunker) — challenge 31 splice-relay credential gate (#707)
# --------------------------------------------------------------------------

_M5_KEY_PATH = "/home/kali/.ssh/splice_relay"
_M5_RUNNER = "a14-kali"
_M5_EXPECTED_ANSWER = "AHS-TAIL-7741AHS-LEG-MN07AHS-ARM-AL42"
_M5_DEVID_BODIES = {
    "tail-ctrl": "Device Identification:\n  VendorName: Aurora\n  ProductName: AHS-TAIL-7741\n  MajorMinorRevision: 2.4\n",
    "leg-ctrl": "Device Identification:\n  VendorName: Aurora\n  ProductName: AHS-LEG-MN07\n  MajorMinorRevision: 2.4\n",
    "arms-ctrl": "Device Identification:\n  VendorName: Aurora\n  ProductName: AHS-ARM-AL42\n  MajorMinorRevision: 2.4\n",
}


def _m5_happy_responses(perms: str = "600", devid_bodies=None):
    """FakeRunner argv -> ExecResult map for the full happy-path participant chain."""
    bodies = devid_bodies if devid_bodies is not None else _M5_KEY_HAPPY_DEVID_BODIES()
    base = {
        (_M5_RUNNER, ("test", "-f", _M5_KEY_PATH)): runner.ExecResult(0, "", ""),
        (_M5_RUNNER, ("stat", "-c", "%a", _M5_KEY_PATH)): runner.ExecResult(0, f"{perms}\n", ""),
        (_M5_RUNNER, (
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            "root@splice-relay", "true",
        )): runner.ExecResult(0, "", ""),
    }
    for host, body in bodies.items():
        argv = (
            "ssh", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "root@splice-relay",
            "python3", "/usr/local/bin/modbus_client.py", host, "devid",
        )
        base[(_M5_RUNNER, argv)] = runner.ExecResult(0, body, "")
    return base


def _M5_KEY_HAPPY_DEVID_BODIES():
    return dict(_M5_DEVID_BODIES)


def test_mission5_adapter_registered_for_challenge_31():
    """Importing scenario_smoketest.adapters must register challenge 31."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    assert 31 in ADAPTERS
    adapter = ADAPTERS[31]
    assert adapter.value_kind == "answer"
    assert adapter.expected_answer == _M5_EXPECTED_ANSWER
    assert adapter.runner == _M5_RUNNER


def test_mission5_adapter_happy_path_produces_concatenated_models():
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    fr = FakeRunner(_m5_happy_responses())
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    assert produced.value == _M5_EXPECTED_ANSWER
    assert produced.kind == "answer"

    # Pin the exact SSH auth argv. Without this assertion the FakeRunner's
    # argv-prefix fallback would silently let a regression drop BatchMode=yes
    # or ConnectTimeout=5 — both required for an unattended smoketest run:
    # BatchMode prevents interactive prompts that would hang; ConnectTimeout
    # bounds the probe time. A regressed auth argv would miss the canned
    # key, fall back to ExecResult(0, "", ""), look like "auth passed", and
    # the modbus probes' exact-key matches would still yield the expected
    # concatenation.
    expected_auth_argv = (
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "root@splice-relay", "true",
    )
    assert any(
        argv == expected_auth_argv for _, argv in fr.calls
    ), f"happy path must invoke the exact auth argv {expected_auth_argv!r}"


def test_mission5_adapter_evidence_missing_short_circuits():
    """If the participant's key file isn't staged, no SSH is attempted."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    fr = FakeRunner({
        (_M5_RUNNER, ("test", "-f", _M5_KEY_PATH)): runner.ExecResult(1, "", ""),
    })
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    assert produced.value is None
    assert "evidence missing" in produced.note.lower()
    # No SSH attempt — running the SSH command would not have a canned response
    # and would fall through to FakeRunner's empty default. Verify by argv set.
    invoked = {tuple(argv) for _, argv in fr.calls}
    assert not any("ssh" in argv for argv in invoked)


def test_mission5_adapter_wrong_perms_fails_redacted():
    """A 0644 key would be a real participant-flow defect; surface it without leaking content."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    responses = _m5_happy_responses(perms="644")
    fr = FakeRunner(responses)
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    assert produced.value is None
    note = produced.note.lower()
    assert "perm" in note
    # Detail names the observed mode but never the key bytes; we only ever
    # invoke `stat` on the key path, never `cat`.
    invoked = {tuple(argv) for _, argv in fr.calls}
    assert not any(("cat",) == argv[:1] for argv in invoked)


def test_mission5_adapter_auth_refused_fails_without_modbus_probe():
    """If sshd rejects the key, the harness must not attempt downstream probes."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    responses = _m5_happy_responses()
    ssh_key = (
        _M5_RUNNER,
        (
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            "root@splice-relay", "true",
        ),
    )
    responses[ssh_key] = runner.ExecResult(255, "", "Permission denied (publickey).")
    fr = FakeRunner(responses)
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    assert produced.value is None
    assert "auth" in produced.note.lower()
    # No modbus probe argv invoked when auth fails.
    invoked = [tuple(argv) for _, argv in fr.calls]
    assert not any("modbus_client.py" in tuple(argv) for argv in invoked)
    # Raw stderr (which would leak SSH banner or host details) does not surface.
    assert "Permission denied" not in produced.note


def test_mission5_adapter_modbus_mismatch_redacts_value():
    """Wrong ProductName surfaces a host-keyed failure without leaking model bodies."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    bodies = _M5_KEY_HAPPY_DEVID_BODIES()
    bodies["arms-ctrl"] = "VendorName: Aurora\nProductName: AHS-ARM-WRONG\nMajorMinorRevision: 2.4\n"
    fr = FakeRunner(_m5_happy_responses(devid_bodies=bodies))
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    # Adapter returns the concatenated produced value (including the drift); the
    # harness compare layer turns the mismatch into a redacted "fail" verdict.
    assert produced.value is not None
    assert "AHS-ARM-WRONG" in produced.value  # adapter doesn't lie about what it saw
    verdict = compare.compare(produced.value, adapter.expected_answer, adapter.value_kind)
    assert verdict.status == "fail"
    assert "AHS-ARM-WRONG" not in verdict.detail  # compare layer redacts
    assert "AHS-TAIL-7741" not in verdict.detail


def test_mission5_adapter_modbus_devid_missing_field_fails():
    """A devid response without ProductName is the bake-defect signal."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    bodies = _M5_KEY_HAPPY_DEVID_BODIES()
    bodies["leg-ctrl"] = "VendorName: Aurora\n# ProductName field absent\n"
    fr = FakeRunner(_m5_happy_responses(devid_bodies=bodies))
    ctx = AdapterContext(runner=fr, hosts={})
    produced = adapter.solve(ctx)
    assert produced.value is None
    assert "leg-ctrl" in produced.note
    assert "productname" in produced.note.lower()


def test_mission5_adapter_runner_chain_uses_only_a14_kali():
    """Per the participant path, every exec must originate from a14-kali."""
    import scenario_smoketest.adapters.mission5_bunker  # noqa: F401

    adapter = ADAPTERS[31]
    fr = FakeRunner(_m5_happy_responses())
    ctx = AdapterContext(runner=fr, hosts={})
    adapter.solve(ctx)
    containers = {container for container, _ in fr.calls}
    assert containers == {_M5_RUNNER}
