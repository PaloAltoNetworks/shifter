"""Bounded immutable-subject support must retain rejection and drift checks."""

import pytest

import inventory_checkov


@pytest.mark.parametrize("repository", ["example/product", "example@456/product@123"])
def test_reviewed_repository_formats(repository):
    assert inventory_checkov.repository_pattern(inventory_checkov.LEGACY_PATTERN).match(repository)


@pytest.mark.parametrize(
    "repository",
    [
        "*@456/product@123",
        "example@*/product@123",
        "example@456/*@123",
        "example@456/product@*",
        "example@456/product@123/other",
        "example@456/product@123suffix",
        "example@456/product",
        "example/product",
    ],
)
def test_immutable_grammar_rejects_wildcards_partial_ids_and_legacy(repository):
    import re

    assert not re.fullmatch(inventory_checkov.IMMUTABLE_PATTERN, repository)


def test_unreviewed_parser_is_rejected():
    with pytest.raises(RuntimeError, match="parser changed"):
        inventory_checkov.repository_pattern(".*")


def test_unreviewed_scanner_version_is_rejected(monkeypatch):
    monkeypatch.setattr(inventory_checkov.importlib.metadata, "version", lambda name: "unknown")
    with pytest.raises(RuntimeError, match="version differs"):
        inventory_checkov.main()


def test_scanner_exit_status_is_preserved(monkeypatch):
    import re
    from types import SimpleNamespace

    rule = SimpleNamespace(gh_repo_regex=re.compile(inventory_checkov.LEGACY_PATTERN))
    scanner = SimpleNamespace(Checkov=lambda: SimpleNamespace(run=lambda: 1))
    monkeypatch.setattr(inventory_checkov.importlib.metadata, "version", lambda name: inventory_checkov.CHECKOV_VERSION)
    monkeypatch.setattr(
        inventory_checkov.importlib, "import_module", lambda name: scanner if name == "checkov.main" else rule
    )
    assert inventory_checkov.main() == 1
    assert rule.gh_repo_regex.match("example@456/product@123")
