#!/usr/bin/env python3
"""Compatibility facade and executable entrypoint for the Shifter deployment CLI."""

from __future__ import annotations

import argparse
import functools
import getpass
import importlib.util
import inspect
import ipaddress
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import Any as TypingAny
from typing import cast
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import aws_bootstrap as _aws_bootstrap
import aws_eks as _aws_eks
import bootstrap_core as _bootstrap_core
import cli as _cli
import gcp_control_plane as _gcp_control_plane
import gdc_cluster as _gdc_cluster
import preflight as _preflight
import terraform_backend as tb
import terraform_deploy as _terraform_deploy_module
import walkthrough as _walkthrough

_OWNING_MODULES: tuple[ModuleType, ...] = (
    _aws_bootstrap,
    _aws_eks,
    _gdc_cluster,
    _gcp_control_plane,
    _preflight,
    _terraform_deploy_module,
    _walkthrough,
    _cli,
)
_SYNC_MODULES: tuple[ModuleType, ...] = (_bootstrap_core, *_OWNING_MODULES)
_ORIGINAL_EXPORTS: dict[str, tuple[ModuleType, object]] = {}
_THIS_MODULE = sys.modules[__name__]
# Module CLI entrypoints (``if __name__ == "__main__"`` targets) are per-module, not shared
# helpers: cli.main and preflight.main are distinct functions. They must not be recorded as
# facade exports, because _sync_modules would then propagate one across every module that has a
# ``main`` and clobber another module's entrypoint (#1828). deploy.main is built explicitly.
_ENTRYPOINT_NAMES: frozenset[str] = frozenset({"main"})
_COMPAT_EXPORTS: dict[str, object] = {
    "Any": TypingAny,
    "Path": Path,
    "argparse": argparse,
    "contextmanager": contextmanager,
    "dataclass": dataclass,
    "dedent": dedent,
    "getpass": getpass,
    "importlib": importlib,
    "ipaddress": ipaddress,
    "json": json,
    "os": os,
    "re": re,
    "shutil": shutil,
    "subprocess": subprocess,
    "sys": sys,
    "tb": tb,
    "tempfile": tempfile,
    "time": time,
    "urllib_error": urllib_error,
    "urllib_parse": urllib_parse,
    "urllib_request": urllib_request,
    "uuid": uuid,
}


def _copy_core_exports() -> None:
    """Expose bootstrap_core names through the legacy deploy module."""
    for name, value in _bootstrap_core.__dict__.items():
        if name.startswith("__"):
            continue
        _ORIGINAL_EXPORTS[name] = (_bootstrap_core, value)
        if inspect.isfunction(value):
            globals()[name] = _make_facade(name, _bootstrap_core, value)
        else:
            globals()[name] = value


def _should_export_from_owner(name: str, value: object, module: ModuleType) -> bool:
    """Return True for definitions owned by the delegated module."""
    if name.startswith("__"):
        return False
    if name in _ENTRYPOINT_NAMES:
        return False
    owner = getattr(value, "__module__", None)
    return owner == module.__name__


def _make_facade(name: str, module: ModuleType, original: Callable[..., object]) -> Callable[..., object]:
    """Build a wrapper that syncs monkeypatchable globals before delegation."""

    @functools.wraps(original)
    def facade(*args: object, **kwargs: object) -> object:
        """Delegate one legacy deploy export after syncing patched globals."""
        _sync_modules()
        return getattr(module, name)(*args, **kwargs)

    facade.__module__ = __name__
    facade._facade_original = original  # type: ignore[attr-defined]
    return facade


def _copy_owner_exports() -> None:
    """Expose functions/classes owned by the focused bootstrap modules."""
    for module in _OWNING_MODULES:
        for name, value in module.__dict__.items():
            if not _should_export_from_owner(name, value, module):
                continue
            _ORIGINAL_EXPORTS[name] = (module, value)
            if inspect.isfunction(value):
                globals()[name] = _make_facade(name, module, value)
            else:
                globals()[name] = value


def _copy_compat_exports() -> None:
    """Expose legacy imported modules and aliases expected by old tests/users."""
    for name, value in _COMPAT_EXPORTS.items():
        _ORIGINAL_EXPORTS[name] = (_THIS_MODULE, value)
        globals()[name] = value


def _unwrapped_export(current: object, original: object) -> object:
    """Return the original callable when the deploy facade was not patched."""
    if getattr(current, "_facade_original", None) is original:
        return original
    return current


def _sync_modules() -> None:
    """Propagate deploy-module monkeypatches into the delegated modules.

    Entrypoint names in ``_ENTRYPOINT_NAMES`` are excluded (see ``_copy_owner_exports``): a
    per-module ``main`` is a distinct CLI entrypoint, not a shared helper, so it is never
    recorded as an export and never propagated across modules.
    """
    for name, (_owner, original) in _ORIGINAL_EXPORTS.items():
        value = _unwrapped_export(globals().get(name, original), original)
        for module in _SYNC_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


_copy_core_exports()
_copy_owner_exports()
_copy_compat_exports()
# deploy.main is the top-level CLI entrypoint and delegates to cli.main. It is built here
# explicitly rather than through _copy_owner_exports (which excludes _ENTRYPOINT_NAMES), so a
# per-module ``main`` is never a synced export and can never clobber another module's distinct
# entrypoint such as preflight.main (#1828). The facade still syncs shared helpers before it runs.
main: Callable[..., object] = cast(Callable[..., object], _make_facade("main", _cli, _cli.main))


if __name__ == "__main__":
    main()
