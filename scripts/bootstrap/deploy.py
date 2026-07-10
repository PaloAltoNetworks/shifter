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
import bootstrap_core as _bootstrap_core
import cli as _cli
import gcp_control_plane as _gcp_control_plane
import gdc_cluster as _gdc_cluster
import terraform_backend as tb
import terraform_deploy as _terraform_deploy_module
import walkthrough as _walkthrough

_OWNING_MODULES: tuple[ModuleType, ...] = (
    _aws_bootstrap,
    _gdc_cluster,
    _gcp_control_plane,
    _terraform_deploy_module,
    _walkthrough,
    _cli,
)
_SYNC_MODULES: tuple[ModuleType, ...] = (_bootstrap_core, *_OWNING_MODULES)
_ORIGINAL_EXPORTS: dict[str, tuple[ModuleType, object]] = {}
_THIS_MODULE = sys.modules[__name__]
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
    """Propagate deploy-module monkeypatches into the delegated modules."""
    for name, (_owner, original) in _ORIGINAL_EXPORTS.items():
        value = _unwrapped_export(globals().get(name, original), original)
        for module in _SYNC_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


_copy_core_exports()
_copy_owner_exports()
_copy_compat_exports()
main: Callable[..., object] = cast(Callable[..., object], globals()["main"])


if __name__ == "__main__":
    main()
