"""Behavior coverage for Shifter-owned helpers transplanted during #1311."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.persisted_envelope import (
    PAYLOAD_KEY,
    SPEC_SCHEMA_KEY,
    SPEC_VERSION,
    SPEC_VERSION_KEY,
    ensure_wrapped_persisted_spec,
    is_wrapped_persisted_spec,
    unwrap_persisted_spec,
)
from shared.schemas.range import RangeSpec
from shared.schemas.registry import UnknownSpecSlugError, get_model_for_slug, resolve_catalog_slug
from shared.template_vars import (
    TemplateString,
    build_instance_data,
    extract_variables,
    resolve_template,
    validate_template,
)


class TestTemplateVariables:
    """Pin parsing, validation, resolution, and Pydantic integration."""

    def test_extracts_and_validates_references(self) -> None:
        template = "Use {{Workstation.ip}} and {{Workstation.name}}."

        assert extract_variables(template) == [("Workstation", "ip"), ("Workstation", "name")]
        assert validate_template(template, {"Workstation"}) == []

    def test_validation_reports_unknown_instances_and_properties(self) -> None:
        errors = validate_template("{{Missing.password}}", {"Workstation"})

        assert len(errors) == 2
        assert "Unknown instance" in errors[0]
        assert "Unknown property" in errors[1]

    def test_resolves_known_values(self) -> None:
        resolved = resolve_template(
            "Connect to {{Workstation.ip}}",
            {"Workstation": {"ip": "10.0.0.5"}},
        )

        assert resolved == "Connect to 10.0.0.5"

    def test_rejects_missing_instance(self) -> None:
        instance_data: dict[str, dict[str, object]] = {}

        with pytest.raises(ValueError, match="instance not found"):
            resolve_template("{{Missing.ip}}", instance_data)

    def test_rejects_missing_property(self) -> None:
        instance_data: dict[str, dict[str, object]] = {"Workstation": {}}

        with pytest.raises(ValueError, match="property not found"):
            resolve_template("{{Workstation.ip}}", instance_data)

    def test_builds_instance_data_and_tolerates_incomplete_rows(self) -> None:
        result = build_instance_data(
            {
                "Workstation": {"private_ip": "10.0.0.5", "instance_id": "i-abc12345"},
                "Pending": None,
            }
        )

        assert result["Workstation"] == {
            "ip": "10.0.0.5",
            "name": "Workstation",
            "instance_id": "i-abc12345",
        }
        assert result["Pending"] == {"ip": "", "name": "Pending"}

    def test_build_instance_data_rejects_non_mapping_input(self) -> None:
        invalid_input = cast(dict[str, object], [])

        assert build_instance_data(invalid_input) == {}

    def test_pydantic_template_validator_uses_context(self) -> None:
        adapter = TypeAdapter(TemplateString)

        assert adapter.validate_python("{{Host.ip}}", context={"instance_names": {"Host"}}) == "{{Host.ip}}"

    def test_pydantic_template_validator_rejects_unknown_reference(self) -> None:
        adapter = TypeAdapter(TemplateString)

        with pytest.raises(ValidationError, match="Unknown instance"):
            adapter.validate_python("{{Missing.ip}}", context={"instance_names": {"Host"}})

    @pytest.mark.parametrize("context", [None, {}, {"instance_names": None}, {"instance_names": 42}])
    def test_pydantic_template_validator_skips_unusable_context(self, context: object) -> None:
        adapter = TypeAdapter(TemplateString)

        assert adapter.validate_python("plain text", context=context) == "plain text"


class TestPersistedEnvelope:
    """Pin wrapping and legacy pass-through behavior."""

    def test_detects_only_complete_envelopes(self) -> None:
        assert not is_wrapped_persisted_spec(None)
        assert not is_wrapped_persisted_spec({SPEC_SCHEMA_KEY: "range_spec"})
        assert is_wrapped_persisted_spec({SPEC_SCHEMA_KEY: "range_spec", PAYLOAD_KEY: {}})

    def test_unwraps_current_and_legacy_payloads(self) -> None:
        legacy = {"scenario_id": "polaris"}
        wrapped = {SPEC_SCHEMA_KEY: "range_spec", SPEC_VERSION_KEY: SPEC_VERSION, PAYLOAD_KEY: legacy}

        assert unwrap_persisted_spec(None) == {}
        assert unwrap_persisted_spec(legacy) is legacy
        assert unwrap_persisted_spec(wrapped) is legacy

    def test_rejects_non_mapping_payload(self) -> None:
        wrapped = {SPEC_SCHEMA_KEY: "range_spec", PAYLOAD_KEY: "invalid"}

        with pytest.raises(TypeError, match="Expected dict payload"):
            unwrap_persisted_spec(wrapped)

    def test_wraps_only_legacy_payloads(self) -> None:
        legacy = {"scenario_id": "polaris"}
        wrapped = ensure_wrapped_persisted_spec("range_spec", legacy)

        assert ensure_wrapped_persisted_spec("range_spec", None) == {}
        assert wrapped == {
            SPEC_SCHEMA_KEY: "range_spec",
            SPEC_VERSION_KEY: SPEC_VERSION,
            PAYLOAD_KEY: legacy,
        }
        assert ensure_wrapped_persisted_spec("range_spec", wrapped) is wrapped


class TestSchemaRegistry:
    """Pin stable schema slugs and fail-closed unknown lookup."""

    def test_resolves_stable_model_and_legacy_catalog_path(self) -> None:
        assert get_model_for_slug("range_spec") is RangeSpec
        assert resolve_catalog_slug("shared.schemas.SCMCredentialSpec") == "credential.scm"

    def test_rejects_unknown_slug(self) -> None:
        with pytest.raises(UnknownSpecSlugError, match="Unknown schema slug"):
            get_model_for_slug("unknown")

    def test_rejects_unknown_legacy_path(self) -> None:
        with pytest.raises(UnknownSpecSlugError, match="Unknown legacy spec_class path"):
            resolve_catalog_slug("legacy.Unknown")
