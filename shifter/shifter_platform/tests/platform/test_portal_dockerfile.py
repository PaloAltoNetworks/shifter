"""Portal container image invariants."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "shifter" / "shifter_platform" / "Dockerfile"


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
