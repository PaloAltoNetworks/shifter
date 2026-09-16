"""RAES operation sidecar retention/cleanup Django settings (#1277).

Extracted into a ``config/_*.py`` module like ``config/_guacamole_settings.py``
so ``config/settings.py`` stays under the 500-line cap (Sonar S104). Importing
this module has no side effects beyond binding the module-level constants used
in the re-export.

These are the operator-visible, non-secret knobs for RAES runtime-snapshot (and
adjacent operation-record) retention. ``RaesOperationRecord`` rows are bounded
operational observations, not an archive: each row is written with an indexed
``retention_expires_at`` derived from ``RAES_OPERATION_RECORD_RETENTION_DAYS``,
and the dedicated pruning service (``run_raes_operation_record_prune``) deletes
rows past that boundary in bounded batches. Setting the retention days to ``0``
(or negative) disables the expiry stamp, so no row is ever pruned -- an
opt-out-safe default. The interval/batch knobs mirror the guacamole bootstrap
prune service (``config/_guacamole_settings.py``); the reads use literal
``os.environ.get`` so the generated ``config/env-manifest.json`` picks them up.
The design contract lives in
``docs/adr/index.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES",
    "RAES_CONTENT_DELIVERY_PREFIX",
    "RAES_OPERATION_RECORD_PRUNE_BATCH_SIZE",
    "RAES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS",
    "RAES_OPERATION_RECORD_RETENTION_DAYS",
    "RAES_PACKAGE_BUCKET",
    "RAES_PACKAGE_MAX_ARCHIVE_BYTES",
    "RAES_PACKAGE_MAX_ENTRIES",
    "RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES",
    "RAES_PACKAGE_PREFIX",
    "RAES_PACKAGE_ROOT",
]

# Filesystem root under which an RAES package_ref is resolved to its pack root by
# registration and the native launch loader (#1479, #1578). Repo-relative pack
# roots are joined to this setting with containment enforcement; launch verifies
# their canonical content digest before selecting the single direct SDL entry.
# Defaults to
# the repo root so in-repo scenario packages (e.g. scenario-dev/...) resolve out
# of the box; override per environment when packages live elsewhere. Read via the
# literal os.environ.get form so config/env-manifest.json picks it up.
# In the source tree config/ sits at shifter/shifter_platform/config, so
# parents[3] is the repo root (where in-repo scenario packages like scenario-dev/
# live). In the deployed container the tree is flattened to /app, so parents[3]
# does not exist; fall back to the app root instead of raising IndexError at
# import (which would break every image build / settings load). The default is
# only a starting point anyway — override SHIFTER_RAES_PACKAGE_ROOT per env.
_raes_settings_parents = Path(__file__).resolve().parents
_raes_default_package_root = _raes_settings_parents[3] if len(_raes_settings_parents) > 3 else _raes_settings_parents[1]
RAES_PACKAGE_ROOT = os.environ.get("SHIFTER_RAES_PACKAGE_ROOT", str(_raes_default_package_root))

# Object-storage location for object-backed RAES packages (#1567, ADR-034-R5).
# An ``object`` source row's ``package_ref`` names a single immutable archive
# object; the native launch resolver downloads it from this bucket (optionally
# under a fixed key prefix), safely extracts it into a private temp dir, and
# verifies its canonical content digest before SDL resolution or dispatch. An
# empty bucket keeps object-backed packs non-launchable (fail closed) — object
# launchability requires this to be configured. Read via the literal
# os.environ.get form so config/env-manifest.json picks it up.
RAES_PACKAGE_BUCKET = os.environ.get("SHIFTER_RAES_PACKAGE_BUCKET", "")
RAES_PACKAGE_PREFIX = os.environ.get("SHIFTER_RAES_PACKAGE_PREFIX", "")

# Fail-closed bounds for object-backed package retrieval and extraction (defense
# in depth against oversized downloads and archive bombs). Non-secret integers;
# override per environment. Defaults: 256 MiB archive, 1 GiB total uncompressed,
# 20000 members.
RAES_PACKAGE_MAX_ARCHIVE_BYTES = int(os.environ.get("SHIFTER_RAES_PACKAGE_MAX_ARCHIVE_BYTES", "268435456"))
RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES = int(os.environ.get("SHIFTER_RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES", "1073741824"))
RAES_PACKAGE_MAX_ENTRIES = int(os.environ.get("SHIFTER_RAES_PACKAGE_MAX_ENTRIES", "20000"))

# Object-storage delivery of source-backed RAES content (#1564, ADR-032-R3,
# ADR-034-R6). While a registered, digest-verified pack is live, materialized
# source-backed content payloads (file bytes / a deterministic directory tar) are
# promoted content-addressed under the existing STORAGE_BUCKET_NAME assets bucket
# with this key prefix; the provisioner reads them by the normalized key carried
# in the byte-free delivery binding (never a bucket/URL in the binding). The byte
# cap is defense-in-depth against an oversized materialized payload. Non-secret;
# override per environment. Read via the literal os.environ.get form so
# config/env-manifest.json picks them up. Default 256 MiB payload cap.
RAES_CONTENT_DELIVERY_PREFIX = os.environ.get("SHIFTER_RAES_CONTENT_DELIVERY_PREFIX", "raes/content-delivery")
RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES = int(
    os.environ.get("SHIFTER_RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES", "268435456")
)

# Days a runtime snapshot / operation-record row is retained before it becomes
# eligible for pruning. Measured from the row's source_timestamp so idempotent
# replay is deterministic. Non-positive disables the expiry stamp (never pruned).
RAES_OPERATION_RECORD_RETENTION_DAYS = int(os.environ.get("RAES_OPERATION_RECORD_RETENTION_DAYS", "30"))
# Cadence and bounded batch size for the dedicated RAES operation-record pruning
# service (run_raes_operation_record_prune). Non-secret integers.
RAES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS = int(
    os.environ.get("RAES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS", "3600")
)
RAES_OPERATION_RECORD_PRUNE_BATCH_SIZE = int(os.environ.get("RAES_OPERATION_RECORD_PRUNE_BATCH_SIZE", "500"))
