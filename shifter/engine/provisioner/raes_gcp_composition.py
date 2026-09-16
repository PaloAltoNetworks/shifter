"""Realize RAES composition (content/features/accounts) as GCE guest bootstrap (ADR-032).

Genuine baked-image + inline delivery (the model chosen for the RAES cutover):

- **content, file + inline ``text``** -> the file is written for real (base64, so
  arbitrary bytes/quotes/newlines are safe), mode 0600 when ``sensitive``.
- **content, source-backed file or directory** -> excluded from this bootstrap
  entirely (#1564): the bytes are delivered post-boot over an authenticated guest
  channel with a provisioner-side + in-guest digest verification, never baked
  into the startup script (see ``raes_content_delivery``).
- **content, source-less directory** -> the realizer only creates the structural
  target directory; it never fetches an artifact and never writes an inert
  descriptor stub (the reference backend's thin path is deliberately rejected).
- **account** -> a real guest user (groups/shell/home; locked when ``disabled``).
- **feature, service** -> a real install+enable step; the package is resolved by
  the guest package manager or already present in the baked image.

Rendered as an **idempotent** bootstrap script appended to the instance startup
script (Linux bash / Windows PowerShell), so it re-converges on every boot. All
plan-controlled values are shell-quoted (file bytes go through base64) and
identifiers (usernames, package names) are validated fail-closed, so authored
content can never inject shell. Because startup runs asynchronously,
``raes_composition_verification`` reads the resulting file, directory, account,
and credential state through the authenticated guest channel before apply can
return success.
"""

from __future__ import annotations

import base64
import posixpath
import re
import shlex

from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanContent, RaesPlanFeature, RaesPlanNode

#: Conservative identifier charset for values interpolated into a command name
#: position (usernames, package names). Anything else fails closed.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_USERNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,31}$")
_SERVICE_FEATURE = "service"


class RaesGceCompositionError(RuntimeError):
    """Raised when an authored composition construct cannot be realized safely."""


def _safe_identifier(value: str, *, kind: str) -> str:
    """Return ``value`` if it is a safe command identifier, else fail closed."""
    pattern = _SAFE_USERNAME if kind == "username" else _SAFE_IDENTIFIER
    if not pattern.fullmatch(value) or value.startswith("-"):
        raise RaesGceCompositionError(f"unsafe {kind} {value!r}: expected characters [A-Za-z0-9._-]")
    return value


def _ps_quote(value: str) -> str:
    """Single-quote a value for PowerShell (doubling embedded single quotes)."""
    return "'" + value.replace("'", "''") + "'"


def node_bootstrap_script(node: RaesPlanNode, plan: RaesPlan) -> str:
    """Return the guest bootstrap script realizing ``node``'s composition, or ''.

    Selects the Linux or Windows dialect from the node's ``os_family``. Returns an
    empty string when the node has no content/accounts/features.
    """
    content, accounts, features = _node_composition(node, plan)
    if not (content or accounts or features):
        return ""
    if (node.os_family or "linux").lower() == "windows":
        return _windows_script(content, accounts, features)
    return _linux_script(content, accounts, features)


def _node_composition(
    node: RaesPlanNode,
    plan: RaesPlan,
) -> tuple[list[RaesPlanContent], list[RaesPlanAccount], list[RaesPlanFeature]]:
    """Return local-only composition placements targeting one node.

    Source-backed content (``source_name`` set) is excluded here: it is
    delivered post-boot over an authenticated guest channel with a
    provisioner-side + in-guest digest verification (#1564,
    ``raes_content_delivery``), never baked into the startup script. Inline
    (``text``) files and source-less directories are unaffected -- they keep
    the existing bootstrap realization below.
    """
    content = [item for item in plan.content if item.target_address == node.address and item.source_name is None]
    # Domain-bound placements (including the authority account) are directory
    # principals and are realized only after the controller/member topology is
    # live. They must never also become local guest users.
    accounts = [
        account
        for account in plan.accounts
        if account.target_address == node.address and account.domain_ref is None and account.domain_id is None
    ]
    # Features are realized synchronously after boot through the authenticated
    # guest channel, where install/activation and digest/service readback can
    # gate READY (#1565). Startup metadata must never approximate success.
    features: list[RaesPlanFeature] = []
    return content, accounts, features


# --- Linux (bash) ---------------------------------------------------------------


def _linux_account(account: RaesPlanAccount) -> list[str]:
    """Render bash lines creating one guest user (idempotent)."""
    user = _safe_identifier(account.username, kind="username")
    lines = [
        f"if ! id -u {user} >/dev/null 2>&1; then",
        f"  if command -v useradd >/dev/null 2>&1; then useradd -m {user};",
        f"  elif command -v adduser >/dev/null 2>&1; then adduser -D {user};",
        "  else exit 1; fi",
        "fi",
    ]
    if account.login_shell:
        lines.append(f"command -v usermod >/dev/null 2>&1 && usermod -s {shlex.quote(account.login_shell)} {user}")
    if account.home:
        lines.append(f"command -v usermod >/dev/null 2>&1 && usermod -d {shlex.quote(account.home)} -m {user}")
    for group in account.groups:
        lines.append(
            f"if getent group {shlex.quote(group)} >/dev/null 2>&1; then "
            f"if command -v usermod >/dev/null 2>&1; then usermod -aG {shlex.quote(group)} {user}; "
            f"else addgroup {user} {shlex.quote(group)}; fi; fi"
        )
    if account.disabled:
        lines.append(f"if command -v usermod >/dev/null 2>&1; then usermod -L {user}; else passwd -l {user}; fi")
    return lines


def _linux_content(content: RaesPlanContent) -> list[str]:
    """Render bash lines placing one content item (inline file written; else dir)."""
    if content.content_type == "file" and content.text is not None and content.path:
        encoded = base64.b64encode(content.text.encode()).decode("ascii")
        mode = "600" if content.sensitive else "644"
        parent = posixpath.dirname(content.path) or "/"
        return [
            f"mkdir -p {shlex.quote(parent)}",
            f"base64 -d > {shlex.quote(content.path)} <<'RAES_B64_EOF'",
            encoded,
            "RAES_B64_EOF",
            f"chown root:root {shlex.quote(content.path)}",
            f"chmod {mode} {shlex.quote(content.path)}",
        ]
    # A directory (source-less; source-backed directories are excluded from
    # composition entirely -- see _node_composition), or a file with neither
    # inline text nor a source: create the structural target only.
    target = content.destination or (posixpath.dirname(content.path) if content.path else "")
    return [f"mkdir -p {shlex.quote(target)}"] if target else []


def _linux_feature(feature: RaesPlanFeature) -> list[str]:
    """Render bash lines installing+enabling a service feature (else a dir)."""
    if feature.feature_type != _SERVICE_FEATURE or not feature.source_name:
        return [f"mkdir -p {shlex.quote(feature.destination)}"] if feature.destination else []
    package = _safe_identifier(feature.source_name, kind="package")
    return [
        f"if command -v apt-get >/dev/null 2>&1; then"
        f" DEBIAN_FRONTEND=noninteractive apt-get install -y {package} || true;"
        f" elif command -v dnf >/dev/null 2>&1; then dnf install -y {package} || true;"
        f" elif command -v yum >/dev/null 2>&1; then yum install -y {package} || true; fi",
        f"systemctl enable --now {package} >/dev/null 2>&1 || true",
    ]


def _linux_script(
    content: list[RaesPlanContent], accounts: list[RaesPlanAccount], features: list[RaesPlanFeature]
) -> str:
    """Assemble the Linux composition bootstrap (accounts, then content, then features)."""
    lines: list[str] = ["", "# --- RAES composition (accounts, content, features) ---"]
    for account in accounts:
        lines.extend(_linux_account(account))
    for item in content:
        lines.extend(_linux_content(item))
    for feature in features:
        lines.extend(_linux_feature(feature))
    return "\n".join(lines) + "\n"


# --- Windows (PowerShell) -------------------------------------------------------


def _windows_account(account: RaesPlanAccount) -> list[str]:
    """Render PowerShell lines creating one local user (idempotent)."""
    user = _safe_identifier(account.username, kind="username")
    quoted = _ps_quote(user)
    lines = [
        f"if (-not (Get-LocalUser -Name {quoted} -ErrorAction SilentlyContinue)) "
        f"{{ New-LocalUser -Name {quoted} -NoPassword -ErrorAction SilentlyContinue }}"
    ]
    for group in account.groups:
        lines.append(f"Add-LocalGroupMember -Group {_ps_quote(group)} -Member {quoted} -ErrorAction SilentlyContinue")
    if account.disabled:
        lines.append(f"Disable-LocalUser -Name {quoted} -ErrorAction SilentlyContinue")
    return lines


def _windows_content(content: RaesPlanContent) -> list[str]:
    """Render PowerShell lines placing one content item (inline file written; else dir)."""
    if content.content_type == "file" and content.text is not None and content.path:
        encoded = base64.b64encode(content.text.encode()).decode("ascii")
        quoted = _ps_quote(content.path)
        lines = [
            f"New-Item -ItemType Directory -Force -Path (Split-Path -Parent {quoted}) | Out-Null",
            f"[IO.File]::WriteAllBytes({quoted}, [Convert]::FromBase64String('{encoded}'))",
        ]
        if content.sensitive:
            lines.extend(
                [
                    "$SensitiveAcl = [System.Security.AccessControl.FileSecurity]::new()",
                    "$SensitiveAcl.SetAccessRuleProtection($true, $false)",
                    "$SystemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')",
                    "$AdministratorsSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')",
                    "$SensitiveAcl.SetOwner($SystemSid)",
                    "foreach ($Sid in @($SystemSid, $AdministratorsSid)) {",
                    "  $SensitiveAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(",
                    "    $Sid, [System.Security.AccessControl.FileSystemRights]::FullControl,",
                    "    [System.Security.AccessControl.AccessControlType]::Allow))",
                    "}",
                    f"Set-Acl -LiteralPath {quoted} -AclObject $SensitiveAcl",
                ]
            )
        return lines
    target = content.destination or content.path
    return [f"New-Item -ItemType Directory -Force -Path {_ps_quote(target)} | Out-Null"] if target else []


def _windows_feature(feature: RaesPlanFeature) -> list[str]:
    """Render PowerShell lines installing+enabling a service feature (else a dir)."""
    if feature.feature_type != _SERVICE_FEATURE or not feature.source_name:
        if feature.destination:
            return [f"New-Item -ItemType Directory -Force -Path {_ps_quote(feature.destination)} | Out-Null"]
        return []
    package = _safe_identifier(feature.source_name, kind="package")
    return [
        f"choco install -y --no-progress {package}",
        f"Set-Service -Name {package} -StartupType Automatic -ErrorAction SilentlyContinue",
        f"Start-Service -Name {package} -ErrorAction SilentlyContinue",
    ]


def _windows_script(
    content: list[RaesPlanContent], accounts: list[RaesPlanAccount], features: list[RaesPlanFeature]
) -> str:
    """Assemble the Windows composition bootstrap (accounts, then content, then features)."""
    lines: list[str] = ["", "# --- RAES composition (accounts, content, features) ---"]
    for account in accounts:
        lines.extend(_windows_account(account))
    for item in content:
        lines.extend(_windows_content(item))
    for feature in features:
        lines.extend(_windows_feature(feature))
    return "\n".join(lines) + "\n"
