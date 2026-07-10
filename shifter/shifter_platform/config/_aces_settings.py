"""ACES operation sidecar retention/cleanup Django settings (#1277).

Extracted into a ``config/_*.py`` module like ``config/_guacamole_settings.py``
so ``config/settings.py`` stays under the 500-line cap (Sonar S104). Importing
this module has no side effects beyond binding the module-level constants used
in the re-export.

These are the operator-visible, non-secret knobs for ACES runtime-snapshot (and
adjacent operation-record) retention. ``AcesOperationRecord`` rows are bounded
operational observations, not an archive: each row is written with an indexed
``retention_expires_at`` derived from ``ACES_OPERATION_RECORD_RETENTION_DAYS``,
and the dedicated pruning service (``run_aces_operation_record_prune``) deletes
rows past that boundary in bounded batches. Setting the retention days to ``0``
(or negative) disables the expiry stamp, so no row is ever pruned -- an
opt-out-safe default. The interval/batch knobs mirror the guacamole bootstrap
prune service (``config/_guacamole_settings.py``); the reads use literal
``os.environ.get`` so the generated ``config/env-manifest.json`` picks them up.
The design contract lives in
``docs/architecture/aces-snapshot-retention-redaction-audit-preflight-1277.md``.
"""

from __future__ import annotations

import os

__all__ = [
    "ACES_NATIVE_PROVISIONING_ENABLED",
    "ACES_OPERATION_RECORD_PRUNE_BATCH_SIZE",
    "ACES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS",
    "ACES_OPERATION_RECORD_RETENTION_DAYS",
]

# Master feature flag for the ACES-native provisioning path (ADR-031). When
# False (the default), the ACES-native RuntimeTarget backend, dispatch, engine
# consumption, provisioner realization, and ACES catalog launchability are all
# inert, and the existing cyberscript scenario -> RangeSpec -> hydrate ->
# interpret -> provisioner path is unchanged and authoritative (PLAT-2008,
# ADR-031-R2). Flipping this to True is a deliberate, separately-authorized
# cutover step, not a routine deploy toggle. Read via the literal os.environ.get
# form so the generated config/env-manifest.json picks it up automatically.
ACES_NATIVE_PROVISIONING_ENABLED = os.environ.get("SHIFTER_ACES_NATIVE_PROVISIONING", "False").lower() == "true"

# Days a runtime snapshot / operation-record row is retained before it becomes
# eligible for pruning. Measured from the row's source_timestamp so idempotent
# replay is deterministic. Non-positive disables the expiry stamp (never pruned).
ACES_OPERATION_RECORD_RETENTION_DAYS = int(os.environ.get("ACES_OPERATION_RECORD_RETENTION_DAYS", "30"))
# Cadence and bounded batch size for the dedicated ACES operation-record pruning
# service (run_aces_operation_record_prune). Non-secret integers.
ACES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS = int(
    os.environ.get("ACES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS", "3600")
)
ACES_OPERATION_RECORD_PRUNE_BATCH_SIZE = int(os.environ.get("ACES_OPERATION_RECORD_PRUNE_BATCH_SIZE", "500"))
