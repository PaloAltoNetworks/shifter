"""Portal container image invariants."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.markers import Marker

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "shifter" / "shifter_platform" / "Dockerfile"


def test_cloud_lock_preserves_platform_versions_for_container_python() -> None:
    """A second cloud install must not downgrade shared runtime dependencies."""
    platform = DOCKERFILE.parent
    packages = tomllib.loads((platform / "uv.lock").read_text())["package"]
    environment = {"python_version": "3.12", "python_full_version": "3.12.0", "sys_platform": "linux"}
    versions = {
        package["name"]: package["version"]
        for package in packages
        if not package.get("resolution-markers")
        or any(Marker(marker).evaluate(environment) for marker in package["resolution-markers"])
    }
    cloud = dict(re.findall(r"^([\w-]+)==([^\s]+)", (platform / "requirements-gcp.lock").read_text(), re.MULTILINE))
    mismatches = {
        name: (version, versions[name])
        for name, version in cloud.items()
        if name in versions and version != versions[name]
    }
    assert not mismatches, f"Cloud lock replaces platform dependencies: {mismatches}"


def test_portal_image_creates_owned_appuser_home() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "--create-home --home-dir /home/appuser" in dockerfile
    assert "HOME=/home/appuser" in dockerfile
    assert "/home/appuser/.terraform.d/plugin-cache" in dockerfile
    assert "/home/appuser/.pulumi" in dockerfile
    assert "chown -R appuser:appgroup /app/staticfiles /app/media /home/appuser" in dockerfile


def test_portal_image_builds_django_artifacts_as_appuser() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    user_index = dockerfile.index("USER appuser")
    compile_index = dockerfile.index("python manage.py compilemessages")
    collect_index = dockerfile.index("python manage.py collectstatic --noinput")
    healthcheck_index = dockerfile.index("HEALTHCHECK")

    assert user_index < compile_index < collect_index < healthcheck_index
    assert "BUILD_DJANGO_SECRET_KEY=" in dockerfile
    assert "BUILD_FIELD_ENCRYPTION_KEY=" in dockerfile
    assert 'DJANGO_SECRET_KEY="$BUILD_DJANGO_SECRET_KEY"' in dockerfile
    assert 'FIELD_ENCRYPTION_KEY="$BUILD_FIELD_ENCRYPTION_KEY"' in dockerfile
    assert "OIDC_RP_CLIENT_ID=build-time-client" in dockerfile
    assert "DJANGO_DEBUG=True" not in dockerfile
