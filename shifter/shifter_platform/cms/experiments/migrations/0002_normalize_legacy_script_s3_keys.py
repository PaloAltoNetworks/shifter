"""Normalize legacy ScriptAsset.s3_key values to satisfy the execution validator.

Background: issue #700 introduces a strict execution-time S3 key contract
(`cyberscript.script_context.S3KeySegment`) that rejects spaces, quotes,
shell metacharacters, unicode, and `..` traversal sequences. Keys produced
by the pre-#700 `sanitize_s3_filename` path may contain those characters
because the legacy sanitizer only stripped path separators and control
bytes. Without this migration, any experiment referencing a legacy script
would fail at plan time with a `script_s3_key: …` validation error.

Operation order per row (critical for correctness):

1. Detect: skip if the current key already passes the inline validator.
2. Compute the target key by re-normalizing each path segment, defusing
   `..`, and appending `-pk<asset.pk>` to guarantee per-asset uniqueness
   (otherwise two legacy keys differing only by disallowed punctuation
   could collapse to the same destination and overwrite each other in S3).
3. Skip the row entirely if object storage is unavailable — a DB-only
   rename without the corresponding S3 copy leaves the row pointing at a
   non-existent key, which is strictly worse than leaving the legacy key
   in place.
4. Copy the object server-side (no data flows through this process).
5. Persist the DB rename. If the save fails, the legacy object still
   exists at its original key — no data loss.
6. Only after the DB write commits, delete the legacy object.

The reverse migration is a no-op — legacy keys are not reconstructable.

This migration intentionally does NOT import application code at runtime
(per Django's "historical state" guarantee for migrations): the
normalization logic and validator are frozen inline.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline (frozen) validator and normalizer
#
# These are copies of `cyberscript.script_context._S3_KEY_PATTERN` and
# `cms.experiments.s3.normalize_legacy_script_s3_key` as of issue #700.
# They are intentionally NOT imported from application code so that a
# future refactor cannot retroactively change this migration's behavior.
# ---------------------------------------------------------------------------

_S3_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._/=+-]+$")
_S3_KEY_NORMALIZE = re.compile(r"[^A-Za-z0-9._=+-]+")
_MAX_S3_KEY = 500


def _is_valid_s3_key(key: str) -> bool:
    return (
        bool(key)
        and len(key) <= _MAX_S3_KEY
        and not key.startswith("/")
        and ".." not in key
        and bool(_S3_KEY_PATTERN.fullmatch(key))
    )


def _normalize_segment(segment: str) -> str:
    cleaned = _S3_KEY_NORMALIZE.sub("_", segment)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    return cleaned.strip("_")


def _normalize_key(legacy_key: str, asset_pk: int) -> str:
    """Frozen copy of the normalization logic used to rename legacy keys.

    `asset_pk` is appended as `-pk<id>` to guarantee that two legacy keys
    differing only in disallowed characters cannot collide on the same
    destination key. Truncation enforces the validator's full-key cap
    across the entire path (cycle-5 #3 — earlier versions only sliced
    the trailing path segment, which could produce keys >500 chars when
    the parent path consumed the budget).
    """
    if not legacy_key:
        body = "unnamed"
    else:
        segments: list[str] = []
        for segment in legacy_key.lstrip("/").split("/"):
            cleaned = _normalize_segment(segment)
            if cleaned:
                segments.append(cleaned)
        body = "/".join(segments) or "unnamed"
    suffix = f"-pk{asset_pk}"
    max_body = _MAX_S3_KEY - len(suffix)
    if max_body < 1:
        # Suffix alone consumes the cap — very large asset_pk. Truncate
        # the suffix itself; uniqueness within the truncation is preserved
        # by the suffix's per-pk prefix.
        return suffix[:_MAX_S3_KEY]
    if len(body) > max_body:
        body = body[:max_body]
        # Truncation can leave dangling path separators or dots; clean up
        # so the resulting body still satisfies the validator.
        body = body.rstrip("/").rstrip(".")
        if not body:
            body = "unnamed"[:max_body]
    return body + suffix


def _get_storage_and_bucket():
    """Return (storage_adapter, bucket_name) or (None, None) on any failure."""
    bucket = getattr(settings, "AWS_S3_BUCKET_NAME", None)
    if not bucket:
        return None, None
    try:
        from shared.cloud import get_object_storage

        return get_object_storage(), bucket
    except Exception:  # pragma: no cover - defensive
        logger.exception(
            "normalize_legacy_script_s3_keys: could not initialize object storage"
        )
        return None, None


class _LegacyKeyMigrationError(RuntimeError):
    """Raised when unreconciled ScriptAsset.s3_key rows remain at end of run."""


def _process_one_asset(asset, storage, bucket):
    """Process a single ScriptAsset row.

    Returns one of: "renamed", "valid", "failed". Each row runs in its own
    `transaction.atomic()` block (the Migration class sets `atomic = False`
    so this nested atomic actually commits), and the legacy S3 delete runs
    only after the per-row transaction commits via `transaction.on_commit`.
    """
    from django.db import transaction

    current = asset.s3_key or ""
    if _is_valid_s3_key(current):
        return "valid"
    new_key = _normalize_key(current, asset.pk)
    if not _is_valid_s3_key(new_key) or new_key == current:
        logger.warning(
            "normalize_legacy_script_s3_keys: could not derive a valid new key for "
            "asset pk=%s; skipping",
            asset.pk,
        )
        return "failed"

    # Refuse to overwrite an existing destination object. The -pk<id>
    # suffix is uniqueness-by-construction in theory, but a partial
    # previous migration run can leave the destination already populated.
    # `object_exists` distinguishes a confirmed miss (False — safe to copy)
    # from any other error (auth, network — raise and fail closed). Earlier
    # versions wrapped `head_object` in `except Exception: pass`, which
    # treated transient errors as "object missing" and could overwrite
    # destination content (cycle-5 #2).
    try:
        dst_exists = storage.object_exists(bucket=bucket, key=new_key)
    except Exception:
        logger.exception(
            "normalize_legacy_script_s3_keys: destination existence check failed "
            "for asset pk=%s (dst=%s); failing closed",
            asset.pk,
            new_key,
        )
        return "failed"
    if dst_exists:
        # Idempotency path (cycle-5 #4): a previous attempt copied the
        # object successfully but failed before the DB commit. The
        # destination is already populated by us, so adopt it: skip the
        # copy and proceed to the DB rename. The legacy object is still
        # the source-of-truth content; we only need to commit the rename.
        logger.info(
            "normalize_legacy_script_s3_keys: destination already exists for "
            "asset pk=%s (dst=%s); adopting existing copy and proceeding to "
            "DB rename",
            asset.pk,
            new_key,
        )
    else:
        try:
            storage.copy_object(bucket=bucket, src_key=current, dst_key=new_key)
        except Exception:
            logger.exception(
                "normalize_legacy_script_s3_keys: S3 copy failed for asset pk=%s; "
                "key left as-is",
                asset.pk,
            )
            return "failed"

    try:
        with transaction.atomic():
            asset.s3_key = new_key
            asset.save(update_fields=["s3_key"])

            def _delete_old(legacy_key=current, asset_pk=asset.pk):
                try:
                    storage.delete_object(bucket=bucket, key=legacy_key)
                except Exception:
                    logger.exception(
                        "normalize_legacy_script_s3_keys: failed to delete legacy "
                        "key for asset pk=%s (old=%s); DB rename committed, legacy "
                        "object will be left for manual cleanup",
                        asset_pk,
                        legacy_key,
                    )

            transaction.on_commit(_delete_old)
    except Exception:
        logger.exception(
            "normalize_legacy_script_s3_keys: DB save failed for asset pk=%s; "
            "legacy object preserved at %s, copied object at %s will be left as "
            "an orphan for manual cleanup",
            asset.pk,
            current,
            new_key,
        )
        return "failed"
    return "renamed"


def normalize_legacy_script_s3_keys(apps, schema_editor):
    ScriptAsset = apps.get_model("experiments", "ScriptAsset")
    storage, bucket = _get_storage_and_bucket()

    if storage is None or bucket is None:
        count = ScriptAsset.objects.filter(s3_key__regex=r".*").count()
        # Only block the migration if there is real data to migrate. An
        # empty table means a fresh deploy that has nothing to reconcile.
        invalid_count = sum(
            1 for asset in ScriptAsset.objects.all().iterator()
            if not _is_valid_s3_key(asset.s3_key or "")
        )
        if invalid_count == 0:
            logger.info(
                "normalize_legacy_script_s3_keys: object storage not configured "
                "and no legacy keys to migrate (total=%d, invalid=0)",
                count,
            )
            return
        raise _LegacyKeyMigrationError(
            "normalize_legacy_script_s3_keys: object storage is required to "
            f"rewrite {invalid_count} legacy ScriptAsset.s3_key row(s) but "
            "AWS_S3_BUCKET_NAME is not configured / get_object_storage failed. "
            "Run the migration in an environment with the configured bucket "
            "accessible."
        )

    renamed = 0
    skipped_valid = 0
    failed_assets: list[int] = []

    for asset in ScriptAsset.objects.all().iterator():
        outcome = _process_one_asset(asset, storage, bucket)
        if outcome == "renamed":
            renamed += 1
        elif outcome == "valid":
            skipped_valid += 1
        else:
            failed_assets.append(asset.pk)

    logger.info(
        "normalize_legacy_script_s3_keys: renamed=%d skipped_valid=%d failed=%d",
        renamed,
        skipped_valid,
        len(failed_assets),
    )

    # Final verification: every ScriptAsset row must now satisfy the validator.
    # If any do not, fail the migration so Django does NOT mark it applied —
    # operators must reconcile the listed rows (re-upload, repair, or delete)
    # before the deploy proceeds.
    remaining_invalid = [
        asset.pk
        for asset in ScriptAsset.objects.all().iterator()
        if not _is_valid_s3_key(asset.s3_key or "")
    ]
    if remaining_invalid:
        raise _LegacyKeyMigrationError(
            "normalize_legacy_script_s3_keys: "
            f"{len(remaining_invalid)} ScriptAsset row(s) still have invalid "
            f"s3_key after the migration pass: pks={remaining_invalid}. "
            "Reconcile (re-upload, repair, or delete) before re-running."
        )


def reverse_noop(apps, schema_editor):
    """Reverse migration is a no-op — legacy keys are not reconstructable."""


class Migration(migrations.Migration):
    # Non-atomic so each per-asset `transaction.atomic()` block commits and
    # its `on_commit` hook (the legacy S3 delete) actually fires. If the
    # whole migration were wrapped in one transaction, every "commit" would
    # be staged inside the parent transaction and the deletes would either
    # fire prematurely or be batched at the very end.
    atomic = False

    dependencies = [
        ("experiments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_legacy_script_s3_keys, reverse_noop),
    ]
