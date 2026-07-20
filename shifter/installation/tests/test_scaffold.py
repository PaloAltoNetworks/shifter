"""Tests for the ``init`` scaffolding helper (installation.scaffold, #727)."""

from __future__ import annotations

from pathlib import Path

import pytest

from installation.scaffold import (
    ScaffoldError,
    available_backends,
    scaffold_config,
)


class TestAvailableBackends:
    def test_lists_backends_that_ship_an_example(self) -> None:
        backends = available_backends()
        assert backends == ["aws", "gcp"]

    def test_is_sorted(self) -> None:
        assert available_backends() == sorted(available_backends())


class TestScaffoldConfig:
    @pytest.mark.parametrize("backend", ["aws", "gcp"])
    def test_copies_the_checked_example_verbatim(self, backend: str, tmp_path: Path) -> None:
        dest = tmp_path / "shifter.yaml"
        result = scaffold_config(backend, dest)
        assert result.backend == backend
        assert result.destination == dest
        assert dest.read_text(encoding="utf-8") == result.source.read_text(encoding="utf-8")
        # A scaffolded config carries the backend selector it was scaffolded for.
        assert f"backend: {backend}" in dest.read_text(encoding="utf-8")

    def test_unknown_backend_is_rejected_and_writes_nothing(self, tmp_path: Path) -> None:
        dest = tmp_path / "shifter.yaml"
        with pytest.raises(ScaffoldError) as exc:
            scaffold_config("azure", dest)
        assert "azure" in str(exc.value)
        assert not dest.exists()

    def test_refuses_to_overwrite_existing_destination(self, tmp_path: Path) -> None:
        dest = tmp_path / "shifter.yaml"
        dest.write_text("existing: config\n", encoding="utf-8")
        with pytest.raises(ScaffoldError) as exc:
            scaffold_config("aws", dest)
        assert "exists" in str(exc.value).lower()
        # The existing file is left untouched.
        assert dest.read_text(encoding="utf-8") == "existing: config\n"

    def test_force_overwrites_existing_destination(self, tmp_path: Path) -> None:
        dest = tmp_path / "shifter.yaml"
        dest.write_text("existing: config\n", encoding="utf-8")
        scaffold_config("aws", dest, force=True)
        assert "backend: aws" in dest.read_text(encoding="utf-8")

    def test_default_destination_is_shifter_yaml_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = scaffold_config("aws")
        assert result.destination == Path("shifter.yaml")
        assert (tmp_path / "shifter.yaml").is_file()

    def test_nul_byte_in_destination_is_rejected(self) -> None:
        with pytest.raises(ScaffoldError) as exc:
            scaffold_config("aws", "shifter\x00.yaml")
        assert "NUL" in str(exc.value)

    def test_unwritable_destination_raises_scaffold_error(self, tmp_path: Path) -> None:
        # Writing into a non-existent parent directory raises OSError, surfaced as ScaffoldError.
        dest = tmp_path / "missing-parent" / "shifter.yaml"
        with pytest.raises(ScaffoldError) as exc:
            scaffold_config("aws", dest)
        assert "could not write" in str(exc.value)
