"""Tests for the seed_raes_image_registry management command.

Drives the real command against a real database and the real engine.services
write path: it converges any-version RaesImageMapping rows from the
GCP_RANGE_*_IMAGE environment, skips unset images, and is idempotent.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from engine.models import RaesImageMapping

pytestmark = pytest.mark.django_db

_IMAGE_ENVS = (
    "GCP_RANGE_KALI_IMAGE",
    "GCP_RANGE_KALI_MACHINE_TYPE",
    "GCP_RANGE_KALI_DISK_SIZE_GB",
    "GCP_RANGE_KALI_DISK_TYPE",
    "GCP_RANGE_LINUX_IMAGE",
    "GCP_RANGE_LINUX_DISK_SIZE_GB",
    "GCP_RANGE_WINDOWS_IMAGE",
    "GCP_RANGE_DC_IMAGE",
    "GCP_RANGE_BACKEND",
)


@pytest.fixture(autouse=True)
def _clear_image_env(monkeypatch):
    for name in _IMAGE_ENVS:
        monkeypatch.delenv(name, raising=False)


def _run(*argv: str) -> str:
    out = StringIO()
    call_command("seed_raes_image_registry", *argv, stdout=out)
    return out.getvalue()


def test_seeds_kali_and_ubuntu_any_version(monkeypatch):
    monkeypatch.setenv("GCP_RANGE_KALI_IMAGE", "projects/x/global/images/family/shifter-kali")
    monkeypatch.setenv("GCP_RANGE_KALI_DISK_SIZE_GB", "30")
    monkeypatch.setenv("GCP_RANGE_LINUX_IMAGE", "projects/x/global/images/family/shifter-ubuntu")

    output = _run()

    kali = RaesImageMapping.objects.get(source_name="kali")
    assert kali.provider == "gce"
    assert kali.source_version == ""  # any-version fallback
    assert kali.image_ref == "projects/x/global/images/family/shifter-kali"
    assert kali.disk_size_gb == 30
    assert kali.enabled is True

    ubuntu = RaesImageMapping.objects.get(source_name="ubuntu")
    assert ubuntu.image_ref == "projects/x/global/images/family/shifter-ubuntu"
    assert ubuntu.source_version == ""
    assert "Seeded 2 RAES image mapping(s)." in output


def test_skips_unset_images(monkeypatch):
    monkeypatch.setenv("GCP_RANGE_KALI_IMAGE", "projects/x/global/images/family/shifter-kali")

    output = _run()

    assert RaesImageMapping.objects.filter(source_name="kali").exists()
    assert not RaesImageMapping.objects.filter(source_name="ubuntu").exists()
    assert not RaesImageMapping.objects.filter(source_name="windows").exists()
    assert "skip ubuntu: GCP_RANGE_LINUX_IMAGE is unset" in output


def test_is_idempotent(monkeypatch):
    monkeypatch.setenv("GCP_RANGE_KALI_IMAGE", "projects/x/global/images/family/shifter-kali")

    _run()
    _run()

    assert RaesImageMapping.objects.filter(source_name="kali").count() == 1


def test_rejects_non_integer_disk_size(monkeypatch):
    monkeypatch.setenv("GCP_RANGE_KALI_IMAGE", "projects/x/global/images/family/shifter-kali")
    monkeypatch.setenv("GCP_RANGE_KALI_DISK_SIZE_GB", "big")

    with pytest.raises(CommandError, match="disk size for 'kali' must be an integer"):
        _run()
