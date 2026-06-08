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
