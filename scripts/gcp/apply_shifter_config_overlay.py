#!/usr/bin/env python3
"""Apply a bounded, non-secret deployment overlay to an ephemeral shifter.yaml."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_OVERLAY_BYTES = 96 * 1024
ALLOWED_SETTINGS = frozenset({"model_access", "model_broker", "model_broker_runtime"})


class ConfigOverlayError(ValueError):
    """A deployment overlay failed its closed contract."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigOverlayError("deployment overlay contains a duplicate member")
        result[key] = value
    return result


def _read_bounded(path: Path, limit: int) -> str:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ConfigOverlayError("deployment configuration exceeds its size limit")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigOverlayError("deployment configuration must be UTF-8") from None


def _load_overlay(raw: str) -> Mapping[str, object]:
    if len(raw.encode("utf-8")) > MAX_OVERLAY_BYTES:
        raise ConfigOverlayError("deployment overlay exceeds its size limit")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_members)
    except json.JSONDecodeError:
        raise ConfigOverlayError("deployment overlay must be valid JSON") from None
    if not isinstance(value, Mapping) or set(value) != {"settings"}:
        raise ConfigOverlayError("deployment overlay must contain only settings")
    settings = value["settings"]
    if not isinstance(settings, Mapping) or not settings:
        raise ConfigOverlayError("deployment overlay settings must be a non-empty object")
    unknown = set(settings) - ALLOWED_SETTINGS
    if unknown:
        raise ConfigOverlayError("deployment overlay contains an unsupported setting")
    return settings


def apply_overlay(path: Path, raw_overlay: str) -> bool:
    """Replace allowlisted settings blocks and atomically rewrite ``path``."""
    if not raw_overlay.strip():
        return False
    try:
        config = yaml.safe_load(_read_bounded(path, MAX_CONFIG_BYTES))
    except yaml.YAMLError:
        raise ConfigOverlayError("deployment configuration must be valid YAML") from None
    if not isinstance(config, dict) or not isinstance(config.get("settings"), dict):
        raise ConfigOverlayError("deployment configuration requires a settings object")

    config["settings"].update(_load_overlay(raw_overlay))
    rendered = yaml.safe_dump(config, sort_keys=False, allow_unicode=False)
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        overlay_file = os.environ.get("SHIFTER_CONFIG_OVERLAY_FILE", "")
        raw_overlay = (
            _read_bounded(Path(overlay_file), MAX_OVERLAY_BYTES)
            if overlay_file
            else os.environ.get("SHIFTER_CONFIG_OVERLAY_JSON", "")
        )
        apply_overlay(args.config, raw_overlay)
    except (ConfigOverlayError, OSError):
        parser.error("could not apply the bounded deployment configuration overlay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
