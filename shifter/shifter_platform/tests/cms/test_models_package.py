"""Re-export integrity tests for the cms.models package.

These tests pin the public API surface of ``cms.models`` and verify that the
package layout splits classes by bounded context as planned in #1067. They
fail loudly if a submodule is renamed, a class moves to the wrong file, or
a public symbol stops being re-exported from ``cms.models``.

The 41 in-tree consumers of ``cms.models`` rely on ``from cms.models import X``
continuing to work after the refactor. Add to ``EXPECTED_LAYOUT`` whenever a
new public model is added.
"""

from __future__ import annotations

import importlib

import pytest

# Map: submodule name -> set of public symbols that must live there.
# Order matches the leaf-first dependency graph: catalogs has no internal deps;
# range depends on provisioning + assets.
EXPECTED_LAYOUT: dict[str, set[str]] = {
    "catalogs": {
        "CatalogBase",
        "CredentialType",
        "InstanceType",
        "AppType",
        "OperatingSystem",
        "AgentType",
    },
    "assets": {
        "Asset",
        "FileAsset",
        "CredentialBase",
        "Credential",
        "AgentConfig",
    },
    "provisioning": {
        "EntityBase",
        "Request",
        "Instance",
        "App",
        "Subnet",
    },
    "scenarios": {
        "Scenario",
        "ScenarioMetadata",
    },
    "range": {
        "RangeInstance",
    },
}

ALL_PUBLIC_SYMBOLS: set[str] = {name for symbols in EXPECTED_LAYOUT.values() for name in symbols}


def test_cms_models_is_a_package():
    """cms.models must be importable as a package, not a single module."""
    import cms.models as models_pkg

    assert hasattr(models_pkg, "__path__"), (
        "cms.models must be a package (have __path__) so it can host submodules. "
        "If this fails, the refactor still has a flat models.py file."
    )


@pytest.mark.parametrize("submodule", sorted(EXPECTED_LAYOUT))
def test_submodule_is_importable(submodule: str):
    """Each bounded-context submodule must exist and be importable."""
    importlib.import_module(f"cms.models.{submodule}")


@pytest.mark.parametrize("symbol", sorted(ALL_PUBLIC_SYMBOLS))
def test_symbol_is_re_exported_from_cms_models(symbol: str):
    """Every public symbol must remain importable as ``from cms.models import X``."""
    models_pkg = importlib.import_module("cms.models")
    assert hasattr(models_pkg, symbol), (
        f"cms.models is missing re-export for {symbol!r}. "
        "All 41 in-repo importers depend on this surface; add it to "
        "cms/models/__init__.py."
    )


@pytest.mark.parametrize(
    ("symbol", "expected_submodule"),
    sorted((symbol, submodule) for submodule, symbols in EXPECTED_LAYOUT.items() for symbol in symbols),
)
def test_symbol_lives_in_expected_submodule(symbol: str, expected_submodule: str):
    """Each class must be defined in its bounded-context submodule.

    If this fails, a class was moved to the wrong file or its ``__module__``
    drifted away from the planned layout.
    """
    models_pkg = importlib.import_module("cms.models")
    obj = getattr(models_pkg, symbol)
    expected = f"cms.models.{expected_submodule}"
    assert obj.__module__ == expected, f"{symbol} should live in {expected}, found in {obj.__module__}"


def test_re_export_preserves_object_identity():
    """``cms.models.Foo`` must be the same object as ``cms.models.<sub>.Foo``.

    Tests rely on patching ``cms.models.Credential`` etc.; if re-exports
    create copies (e.g. via ``from .submodule import X as X`` indirection),
    patches won't reach the canonical class.
    """
    models_pkg = importlib.import_module("cms.models")
    for submodule, symbols in EXPECTED_LAYOUT.items():
        sub = importlib.import_module(f"cms.models.{submodule}")
        for symbol in symbols:
            assert getattr(models_pkg, symbol) is getattr(sub, symbol), (
                f"cms.models.{symbol} is not the same object as "
                f"cms.models.{submodule}.{symbol}; re-exports must preserve identity."
            )


def test_django_models_keep_cms_app_label():
    """Concrete Django models must remain registered under the ``cms`` app label.

    If this fails after the refactor, Django sees the moved model as a new
    model in a different app and will try to generate destructive migrations.
    """
    models_pkg = importlib.import_module("cms.models")
    abstract_or_non_django = {
        "CatalogBase",
        "EntityBase",
        "Asset",
        "FileAsset",
        "CredentialBase",
        "AgentType",  # TextChoices, not a Model
    }
    concrete_models = ALL_PUBLIC_SYMBOLS - abstract_or_non_django
    for symbol in sorted(concrete_models):
        obj = getattr(models_pkg, symbol)
        assert obj._meta.app_label == "cms", (
            f"{symbol}._meta.app_label drifted to {obj._meta.app_label!r}; must remain 'cms' to preserve migrations."
        )
