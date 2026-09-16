"""Post-boot install and independent verification for RAES service features."""

from __future__ import annotations

import shlex
from typing import Any

from .base import SetupStep

LINUX_INSTALL_SERVICE = r"""#!/bin/bash
set -euo pipefail
package={{ package_quoted }}
version={{ version_quoted }}

if command -v apt-get >/dev/null 2>&1; then
    if [ -n "$version" ]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y "${package}=${version}"
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$package"
    fi
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y "${package}${version:+-${version}}"
elif command -v yum >/dev/null 2>&1; then
    yum install -y "${package}${version:+-${version}}"
elif ! command -v dpkg-query >/dev/null 2>&1 && ! command -v rpm >/dev/null 2>&1; then
    echo "FATAL: no supported package inventory" >&2
    exit 1
fi
systemctl enable --now "$package"
echo "RAES_FEATURE_SERVICE_INSTALLED"
"""

LINUX_VERIFY_SERVICE = r"""#!/bin/bash
set -euo pipefail
package={{ package_quoted }}
expected_version={{ version_quoted }}

if command -v dpkg-query >/dev/null 2>&1; then
    installed_version=$(dpkg-query -W -f='${Version}' "$package")
elif command -v rpm >/dev/null 2>&1; then
    installed_version=$(rpm -q --qf '%{VERSION}-%{RELEASE}' "$package")
else
    echo "FATAL: no supported package inventory" >&2
    exit 1
fi
if [ -n "$expected_version" ] && [ "$installed_version" != "$expected_version" ]; then
    echo "FATAL: RAES feature package version mismatch" >&2
    exit 1
fi
systemctl is-enabled --quiet "$package"
systemctl is-active --quiet "$package"
echo "RAES_FEATURE_SERVICE_VERIFIED"
"""

WINDOWS_INSTALL_SERVICE = r"""$ErrorActionPreference = 'Stop'
$package = {{ package_ps }}
$version = {{ version_ps }}
$args = @('install', '-y', '--no-progress', $package)
if ($version) { $args += @('--version', $version) }
& choco @args
Set-Service -Name $package -StartupType Automatic
Start-Service -Name $package
Write-Output 'RAES_FEATURE_SERVICE_INSTALLED'
"""

WINDOWS_VERIFY_SERVICE = r"""$ErrorActionPreference = 'Stop'
$package = {{ package_ps }}
$expectedVersion = {{ version_ps }}
$inventory = (& choco list --local-only --exact $package --limit-output | Select-Object -First 1)
if (-not $inventory) { throw 'RAES feature package is missing' }
if ($expectedVersion -and -not $inventory.EndsWith("|$expectedVersion")) {
    throw 'RAES feature package version mismatch'
}
$service = Get-Service -Name $package
if ($service.Status -ne 'Running' -or $service.StartType -ne 'Automatic') {
    throw 'RAES feature service is not enabled and running'
}
Write-Output 'RAES_FEATURE_SERVICE_VERIFIED'
"""


def _ps_quote(value: str) -> str:
    """Return one PowerShell single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


class RaesFeatureServicePlan:
    """Install/locate one package-backed service and verify its live state."""

    def __init__(self, *, platform: str, package: str, version: str | None) -> None:
        """Validate and retain one platform/package/version service identity."""
        if platform not in {"linux", "windows"}:
            raise ValueError("unsupported RAES feature service platform")
        self._platform = platform
        self._package = package
        self._version = version or ""

    @property
    def steps(self) -> list[SetupStep]:
        script = LINUX_INSTALL_SERVICE if self._platform == "linux" else WINDOWS_INSTALL_SERVICE
        return [SetupStep(name=f"raes_install_service_{self._platform}", script=script, timeout_seconds=600)]

    @property
    def verify_step(self) -> SetupStep:
        script = LINUX_VERIFY_SERVICE if self._platform == "linux" else WINDOWS_VERIFY_SERVICE
        return SetupStep(
            name=f"raes_verify_service_{self._platform}",
            script=script,
            timeout_seconds=120,
            is_verification=True,
        )

    def get_context(self, _instance: object) -> dict[str, Any]:
        return {
            "package_quoted": shlex.quote(self._package),
            "version_quoted": shlex.quote(self._version),
            "package_ps": _ps_quote(self._package),
            "version_ps": _ps_quote(self._version),
        }
