"""The shipped examples must validate against the same parser the rest of the system uses."""

from __future__ import annotations

import pytest

from installation.loader import load_root_config


def _example_files(examples_dir):
    return sorted(examples_dir.glob("*.yaml"))


def test_examples_directory_is_not_empty(examples_dir):
    assert _example_files(examples_dir), "expected at least one example root config"


def test_examples_cover_the_known_backends(examples_dir):
    from installation import KNOWN_BACKENDS

    stems = {p.stem for p in _example_files(examples_dir)}
    # Every backend the schema accepts today ships a worked example.
    assert stems >= KNOWN_BACKENDS


def test_each_example_parses_and_matches_its_filename(examples_dir):
    files = _example_files(examples_dir)
    assert files
    for path in files:
        cfg = load_root_config(path)
        assert cfg.backend == path.stem, f"{path.name}: backend should be {path.stem!r}, got {cfg.backend!r}"


@pytest.mark.parametrize("example_name", ["aws.yaml", "gcp.yaml"])
def test_required_examples_exist(examples_dir, example_name):
    assert (examples_dir / example_name).is_file()
