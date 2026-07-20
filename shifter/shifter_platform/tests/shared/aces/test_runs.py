"""Realizability-model representation of parameterized ACES runs (#1579, ADR-034).

These tests pin the ``shared.aces.runs`` seam: reading a pack's declared run
parameter schema, deciding whether a scenario is parameterized, and validating a
proposed parameter binding against the ACES SDL variable contract. They assert
the boundary guarantees ADR-034 requires -- bounded, body-free diagnostics and a
one-way binding identity that never carries raw parameter values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.aces.runs import (
    RunRepresentationError,
    is_parameterized,
    read_run_parameters,
    validate_run_binding,
)

# A scenario with no declared variables (not a parameterized run unit) and a
# source-less VM node (image-optional): the backend supplies the base OS.
_IMAGELESS_SDL = """\
name: imageless-run
description: Image-less, non-parameterized scenario.
nodes:
  lan: {type: Switch}
  host: {type: VM, os: linux, resources: {ram: 512 mib, cpu: 1}}
infrastructure:
  lan: {count: 1, properties: {cidr: 10.90.0.0/24, gateway: 10.90.0.1}}
  host: {count: 1, links: [lan], properties: [{lan: 10.90.0.10}]}
"""

# A scenario whose runs are parameterized via ACES SDL variables.
_PARAMETERIZED_SDL = """\
name: parameterized-run
description: Parameterized scenario using SDL variables.
variables:
  flavor: {type: string, default: small, required: false, allowed_values: [small, large]}
  seats: {type: integer, required: true}
  label: {type: string, required: false}
nodes:
  lan: {type: Switch}
  host: {type: VM, os: linux, resources: {ram: 512 mib, cpu: 1}}
infrastructure:
  lan: {count: 1, properties: {cidr: 10.91.0.0/24, gateway: 10.91.0.1}}
  host: {count: 1, links: [lan], properties: [{lan: 10.91.0.10}]}
"""


def _write_sdl(tmp_path: Path, body: str, name: str = "scenario.sdl.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def imageless_sdl(tmp_path: Path) -> Path:
    return _write_sdl(tmp_path, _IMAGELESS_SDL)


@pytest.fixture
def parameterized_sdl(tmp_path: Path) -> Path:
    return _write_sdl(tmp_path, _PARAMETERIZED_SDL)


class TestReadRunParameters:
    def test_non_parameterized_scenario_has_no_parameters(self, imageless_sdl: Path) -> None:
        assert read_run_parameters(imageless_sdl) == ()
        assert is_parameterized(imageless_sdl) is False

    def test_parameterized_scenario_projects_bounded_declarations(self, parameterized_sdl: Path) -> None:
        params = {p.name: p for p in read_run_parameters(parameterized_sdl)}
        assert set(params) == {"flavor", "seats", "label"}
        assert params["flavor"].type == "string"
        assert params["flavor"].required is False
        assert params["flavor"].has_default is True
        assert params["flavor"].allowed_value_count == 2
        assert params["seats"].type == "integer"
        assert params["seats"].required is True
        assert params["seats"].has_default is False
        assert params["seats"].allowed_value_count == 0
        assert params["label"].type == "string"
        assert params["label"].required is False
        assert params["label"].has_default is False
        assert params["label"].allowed_value_count == 0
        assert is_parameterized(parameterized_sdl) is True

    def test_declaration_projection_carries_no_author_values(self, parameterized_sdl: Path) -> None:
        # Declared default ("small") and allowed values must not cross the boundary.
        rendered = repr(read_run_parameters(parameterized_sdl))
        assert "small" not in rendered
        assert "large" not in rendered

    def test_unreadable_sdl_raises_bounded_error(self, tmp_path: Path) -> None:
        with pytest.raises(RunRepresentationError):
            read_run_parameters(tmp_path / "missing.sdl.yaml")

    def test_malformed_sdl_error_is_body_free(self, tmp_path: Path) -> None:
        secret = "SUPERSECRETTOKEN123"
        bad = _write_sdl(tmp_path, f"name: broken\nnodes: {secret}\n")
        with pytest.raises(RunRepresentationError) as exc_info:
            read_run_parameters(bad)
        assert secret not in str(exc_info.value)


class TestValidateRunBinding:
    def test_valid_binding_returns_bounded_descriptor(self, parameterized_sdl: Path) -> None:
        result = validate_run_binding(
            parameterized_sdl, {"seats": 4, "flavor": "large"}, scenario_id="parameterized-run"
        )
        assert result.ok is True
        assert result.diagnostics == ()
        assert result.descriptor is not None
        assert result.descriptor.scenario_id == "parameterized-run"
        assert result.descriptor.bound_parameter_names == ("flavor", "seats")
        assert result.descriptor.binding_identity.startswith("sha256:")

    def test_descriptor_never_carries_raw_parameter_values(self, parameterized_sdl: Path) -> None:
        import dataclasses

        sentinel = "ZZ-NONHEX-SENTINEL-VALUE"
        result = validate_run_binding(parameterized_sdl, {"seats": 7, "flavor": "large", "label": sentinel})
        assert result.ok is True
        # Structural guarantee: the descriptor exposes only bounded identity fields,
        # never a raw parameter-value field.
        assert {f.name for f in dataclasses.fields(result.descriptor)} == {
            "scenario_id",
            "profile",
            "binding_identity",
            "bound_parameter_names",
        }
        # And no submitted value survives into the descriptor's rendering (the
        # binding is only present as a one-way digest).
        rendered = repr(result.descriptor)
        assert sentinel not in rendered
        assert "large" not in rendered

    def test_binding_identity_is_stable_and_selection_specific(self, parameterized_sdl: Path) -> None:
        a = validate_run_binding(parameterized_sdl, {"seats": 4}, scenario_id="s")
        again = validate_run_binding(parameterized_sdl, {"seats": 4}, scenario_id="s")
        different = validate_run_binding(parameterized_sdl, {"seats": 5}, scenario_id="s")
        assert a.descriptor.binding_identity == again.descriptor.binding_identity
        assert a.descriptor.binding_identity != different.descriptor.binding_identity

    def test_optional_scenario_accepts_empty_binding(self, imageless_sdl: Path) -> None:
        # No declared variables: an empty binding is valid.
        result = validate_run_binding(imageless_sdl, None, scenario_id="imageless-run")
        assert result.ok is True
        assert result.descriptor.bound_parameter_names == ()

    def test_missing_required_variable_is_rejected(self, parameterized_sdl: Path) -> None:
        result = validate_run_binding(parameterized_sdl, {"flavor": "small"})
        assert result.ok is False
        assert result.descriptor is None
        assert any("seats" in d for d in result.diagnostics)

    def test_undeclared_parameter_is_rejected(self, parameterized_sdl: Path) -> None:
        result = validate_run_binding(parameterized_sdl, {"seats": 1, "undeclared": 9})
        assert result.ok is False
        assert any("undeclared" in d for d in result.diagnostics)

    def test_disallowed_value_is_rejected(self, parameterized_sdl: Path) -> None:
        result = validate_run_binding(parameterized_sdl, {"seats": 1, "flavor": "huge"})
        assert result.ok is False
        assert result.diagnostics

    def test_wrong_type_is_rejected(self, parameterized_sdl: Path) -> None:
        result = validate_run_binding(parameterized_sdl, {"seats": "not-an-int"})
        assert result.ok is False
        assert result.diagnostics

    def test_binding_diagnostics_do_not_echo_values(self, parameterized_sdl: Path) -> None:
        secret = "SUPERSECRETVALUE"
        result = validate_run_binding(parameterized_sdl, {"seats": 1, "flavor": secret})
        assert result.ok is False
        assert all(secret not in d for d in result.diagnostics)

    def test_unreadable_sdl_returns_bounded_failure(self, tmp_path: Path) -> None:
        result = validate_run_binding(tmp_path / "missing.sdl.yaml", {"seats": 1})
        assert result.ok is False
        assert result.diagnostics
