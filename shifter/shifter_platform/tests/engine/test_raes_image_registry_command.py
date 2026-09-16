"""Tests for the raes_image_registry management command (#1566).

Drives the real command against a real database and the real engine.services
write path: register/list/disable and argument validation via CommandError.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from engine.models import RaesImageMapping
from engine.services import RaesImageMappingOptions, upsert_raes_image_mapping

pytestmark = pytest.mark.django_db


def _run(*argv: str) -> str:
    out = StringIO()
    call_command("raes_image_registry", *argv, stdout=out)
    return out.getvalue()


class TestRegister:
    def test_registers_mapping(self):
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
        mapping = RaesImageMapping.objects.get(source_name="alpine")
        assert mapping.provider == "gce"
        assert mapping.source_version == "3.19"
        assert mapping.disk_size_gb == 20
        assert mapping.enabled is True
        assert "registered gce:alpine@3.19" in output

    def test_register_disabled_flag(self):
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
        assert RaesImageMapping.objects.get(source_name="kali").enabled is False

    def test_missing_required_arg_raises(self):
        with pytest.raises(CommandError):
            _run("--action", "register", "--provider", "gce", "--source-name", "kali")  # no --image-ref

    def test_invalid_provider_raises(self):
        with pytest.raises(CommandError):
            _run("--action", "register", "--provider", "azure", "--source-name", "kali", "--image-ref", "img")


class TestList:
    def test_lists_rows_and_count(self):
        upsert_raes_image_mapping(provider="gce", source_name="alpine", image_ref="img-any")
        upsert_raes_image_mapping(
            provider="gce",
            source_name="kali",
            image_ref="img-v1",
            options=RaesImageMappingOptions(source_version="1"),
        )
        output = _run("--action", "list")
        assert "gce:alpine@* -> img-any [enabled]" in output
        assert "gce:kali@1 -> img-v1 [enabled]" in output
        assert "2 mapping(s)" in output

    def test_enabled_only_filters_disabled(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img")
        upsert_raes_image_mapping(
            provider="gce",
            source_name="ubuntu",
            image_ref="img",
            options=RaesImageMappingOptions(enabled=False),
        )
        output = _run("--action", "list", "--enabled-only")
        assert "kali" in output
        assert "ubuntu" not in output
        assert "1 mapping(s)" in output


class TestDisable:
    def test_disables_existing_mapping(self):
        upsert_raes_image_mapping(provider="gce", source_name="kali", image_ref="img-keep")
        output = _run("--action", "disable", "--provider", "gce", "--source-name", "kali")
        assert RaesImageMapping.objects.get(source_name="kali").enabled is False
        assert "disabled gce:kali@* -> img-keep [disabled]" in output

    def test_disable_missing_mapping_raises(self):
        with pytest.raises(CommandError):
            _run("--action", "disable", "--provider", "gce", "--source-name", "absent")

    def test_disable_missing_required_arg_raises(self):
        with pytest.raises(CommandError):
            _run("--action", "disable", "--provider", "gce")  # no --source-name
