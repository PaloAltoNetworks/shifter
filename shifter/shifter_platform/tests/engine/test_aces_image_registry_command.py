"""Tests for the aces_image_registry management command (#1566).

Drives the real command against a real database and the real engine.services
write path: register/list/disable, argument validation via CommandError, and the
SHIFTER_ACES_NATIVE_PROVISIONING gate.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from engine.models import AcesImageMapping
from engine.services import AcesImageMappingOptions, upsert_aces_image_mapping

pytestmark = pytest.mark.django_db


@pytest.fixture
def native_on(settings):
    settings.ACES_NATIVE_PROVISIONING_ENABLED = True
    return settings


def _run(*argv: str) -> str:
    out = StringIO()
    call_command("aces_image_registry", *argv, stdout=out)
    return out.getvalue()


class TestRegister:
    def test_registers_mapping(self, native_on):
        output = _run(
            "--action",
            "register",
            "--provider",
            "gce",
            "--source-name",
            "alpine",
            "--source-version",
            "3.19",
            "--image-ref",
            "projects/x/global/images/alpine-3-19",
            "--disk-size-gb",
            "20",
        )
        mapping = AcesImageMapping.objects.get(source_name="alpine")
        assert mapping.provider == "gce"
        assert mapping.source_version == "3.19"
        assert mapping.disk_size_gb == 20
        assert mapping.enabled is True
        assert "registered gce:alpine@3.19" in output

    def test_register_disabled_flag(self, native_on):
        _run(
            "--action",
            "register",
            "--provider",
            "gce",
            "--source-name",
            "kali",
            "--image-ref",
            "img",
            "--disabled",
        )
        assert AcesImageMapping.objects.get(source_name="kali").enabled is False

    def test_missing_required_arg_raises(self, native_on):
        with pytest.raises(CommandError):
            _run("--action", "register", "--provider", "gce", "--source-name", "kali")  # no --image-ref

    def test_invalid_provider_raises(self, native_on):
        with pytest.raises(CommandError):
            _run("--action", "register", "--provider", "azure", "--source-name", "kali", "--image-ref", "img")


class TestList:
    def test_lists_rows_and_count(self, native_on):
        upsert_aces_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        upsert_aces_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-v1",
            options=AcesImageMappingOptions(source_version="1"),
        )
        output = _run("--action", "list")
        assert "gce:alpine@* -> img-any [enabled]" in output
        assert "gce:kali@1 -> img-v1 [enabled]" in output
        assert "2 mapping(s)" in output

    def test_enabled_only_filters_disabled(self, native_on):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_aces_image_mapping(
            provider="gce",
            source_name="ubuntu",
            image_ref="img",
            options=AcesImageMappingOptions(enabled=False),
        )
        output = _run("--action", "list", "--enabled-only")
        assert "kali" in output
        assert "ubuntu" not in output
        assert "1 mapping(s)" in output


class TestDisable:
    def test_disables_existing_mapping(self, native_on):
        upsert_aces_image_mapping(provider="gce", source_name="kali", image_ref="img-keep")
        output = _run("--action", "disable", "--provider", "gce", "--source-name", "kali")
        assert AcesImageMapping.objects.get(source_name="kali").enabled is False
        assert "disabled gce:kali@* -> img-keep [disabled]" in output

    def test_disable_missing_mapping_raises(self, native_on):
        with pytest.raises(CommandError):
            _run("--action", "disable", "--provider", "gce", "--source-name", "absent")

    def test_disable_missing_required_arg_raises(self, native_on):
        with pytest.raises(CommandError):
            _run("--action", "disable", "--provider", "gce")  # no --source-name


class TestNativeProvisioningGate:
    def test_command_refuses_when_flag_off(self, settings):
        settings.ACES_NATIVE_PROVISIONING_ENABLED = False
        with pytest.raises(CommandError):
            _run("--action", "list")
