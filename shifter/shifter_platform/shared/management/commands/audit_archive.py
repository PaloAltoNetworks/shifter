"""Management command to archive old audit logs to S3."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from shared.models import AuditLog

if TYPE_CHECKING:
    from botocore.client import BaseClient


class Command(BaseCommand):
    """Export audit logs older than the retention threshold to S3.

    The legacy bucket is not a verified write-once checkpoint, so this command
    never deletes hot-ledger rows (#327).

    Usage:
        python manage.py audit_archive
        python manage.py audit_archive --dry-run
        python manage.py audit_archive --retention-days 30
        python manage.py audit_archive --no-delete
    """

    help = "Archive old audit logs to S3"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be archived without actually doing it",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            default=90,
            help="Number of days to retain in database (default: 90)",
        )
        parser.add_argument(
            "--no-delete",
            action="store_true",
            help="Compatibility flag; chained audit evidence is always retained",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10000,
            help="Number of records to process per batch (default: 10000)",
        )

    def _resolve_archive_bucket(self) -> str | None:
        """Resolve the destination S3 bucket name. Emit an error to stdout on miss."""
        bucket_name = (
            getattr(settings, "LOGS_BUCKET_NAME", None)
            or os.environ.get("LOGS_BUCKET_NAME")
            or getattr(settings, "AUDIT_ARCHIVE_BUCKET", None)
            or os.environ.get("AUDIT_ARCHIVE_BUCKET")
        )
        if not bucket_name:
            self.stdout.write(
                self.style.ERROR("LOGS_BUCKET_NAME not configured. Set via Terraform log-aggregation module output.")
            )
        return bucket_name

    def _resolve_expected_bucket_owner(self) -> str:
        """Return the AWS account ID to pass as `ExpectedBucketOwner`, or ''.

        Defence-in-depth against a bucket-name collision where an attacker
        pre-creates a bucket with the same name in a different account.
        Explicit env var wins; STS fallback discovers the caller's account
        at runtime; on failure we log a warning and skip the check — never
        hard-fail the archive on this defence-in-depth knob.
        """
        expected_bucket_owner = os.environ.get("AWS_ACCOUNT_ID", "")
        if expected_bucket_owner:
            return expected_bucket_owner
        try:
            import boto3

            sts_client = boto3.client("sts")
            return sts_client.get_caller_identity()["Account"]
        except Exception:
            self.stdout.write(self.style.WARNING("  ExpectedBucketOwner check disabled (STS GetCallerIdentity failed)"))
            return ""

    @staticmethod
    def _serialize_batch(batch: list[AuditLog]) -> bytes:
        """Render deterministic canonical JSONL+gzip bytes."""
        lines = []
        for record in batch:
            lines.append(
                json.dumps(
                    {
                        "id": record.id,
                        "event_id": str(record.event_id),
                        "deployment_scope": record.deployment_scope,
                        "chain_generation": record.chain_generation,
                        "sequence": record.sequence,
                        "canonicalization_version": record.canonicalization_version,
                        "previous_digest": record.previous_digest,
                        "record_digest": record.record_digest,
                        "entity_type": record.entity_type,
                        "entity_id": record.entity_id,
                        "entity_ref": record.entity_ref,
                        "action": record.action,
                        "actor_type": record.actor_type,
                        "actor_id": record.actor_id,
                        "actor_principal_uuid": str(record.actor_principal_uuid)
                        if record.actor_principal_uuid
                        else None,
                        "timestamp": record.timestamp.isoformat(),
                        "previous_state": record.previous_state,
                        "new_state": record.new_state,
                        "context": record.context,
                        "source_ip": record.source_ip,
                        "user_agent": record.user_agent,
                        "request_id": record.request_id,
                    },
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        return gzip.compress("\n".join(lines).encode("utf-8"), mtime=0)

    def _archive_one_batch(
        self,
        s3_client: BaseClient,
        batch: list[AuditLog],
        bucket_name: str,
        expected_bucket_owner: str,
        batch_num: int,
        no_delete: bool,
    ) -> tuple[int, int, bool]:
        """Compress and upload one batch without deleting source rows.

        Returns (archived, deleted, ok). `ok=False` signals the caller should
        break out of the loop because S3 upload failed.
        """
        from botocore.exceptions import ClientError

        first = batch[0]
        last = batch[-1]
        s3_key = (
            f"audit-archive/v1/{first.deployment_scope}/"
            f"{first.sequence:020d}-{last.sequence:020d}-{last.record_digest}.jsonl.gz"
        )
        compressed = self._serialize_batch(batch)
        checksum = base64.b64encode(hashlib.sha256(compressed).digest()).decode("ascii")
        put_kwargs = {
            "Bucket": bucket_name,
            "Key": s3_key,
            "Body": compressed,
            "ContentType": "application/x-ndjson",
            "ContentEncoding": "gzip",
            "ChecksumAlgorithm": "SHA256",
            "ChecksumSHA256": checksum,
            "IfNoneMatch": "*",
        }
        if expected_bucket_owner:
            put_kwargs["ExpectedBucketOwner"] = expected_bucket_owner
        try:
            s3_client.put_object(**put_kwargs)
        except ClientError as e:
            error_code = str(e.response.get("Error", {}).get("Code", ""))
            if error_code not in {"PreconditionFailed", "412"}:
                self.stdout.write(self.style.ERROR(f"  Batch {batch_num}: S3 upload failed"))
                upload_ok = False
            else:
                upload_ok = self._existing_archive_matches(
                    s3_client,
                    bucket_name,
                    s3_key,
                    expected_bucket_owner,
                    checksum,
                    batch_num,
                )
        else:
            upload_ok = True

        if upload_ok:
            self.stdout.write(f"  Batch {batch_num}: Uploaded {len(batch)} records to s3://{bucket_name}/{s3_key}")
            if not no_delete:
                self.stdout.write(
                    self.style.WARNING(
                        "  Hot-ledger deletion disabled: no verified write-once checkpoint is configured"
                    )
                )
        return (len(batch), 0, True) if upload_ok else (0, 0, False)

    def _existing_archive_matches(
        self,
        s3_client: BaseClient,
        bucket_name: str,
        s3_key: str,
        expected_bucket_owner: str,
        checksum: str,
        batch_num: int,
    ) -> bool:
        """Verify that an immutable pre-existing object has the expected bytes."""
        from botocore.exceptions import ClientError

        head_kwargs = {"Bucket": bucket_name, "Key": s3_key, "ChecksumMode": "ENABLED"}
        if expected_bucket_owner:
            head_kwargs["ExpectedBucketOwner"] = expected_bucket_owner
        try:
            existing = s3_client.head_object(**head_kwargs)
        except ClientError:
            self.stdout.write(self.style.ERROR(f"  Batch {batch_num}: existing object could not be verified"))
            return False
        matches = existing.get("ChecksumSHA256") == checksum
        if not matches:
            self.stdout.write(self.style.ERROR(f"  Batch {batch_num}: immutable object checksum mismatch"))
        return matches

    def _prepare_upload(self) -> tuple[BaseClient, str, str] | None:
        """Resolve the bucket, import boto3, and build the S3 client + owner check.

        Returns ``(s3_client, bucket_name, expected_bucket_owner)`` or ``None`` when
        the archive cannot proceed (bucket unset or boto3 unavailable).
        """
        bucket_name = self._resolve_archive_bucket()
        if not bucket_name:
            return None

        try:
            import boto3
        except ImportError:
            self.stdout.write(self.style.ERROR("boto3 not installed. Install with: pip install boto3"))
            return None
        s3_client = boto3.client("s3")
        expected_bucket_owner = self._resolve_expected_bucket_owner()
        return s3_client, bucket_name, expected_bucket_owner

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        retention_days = options["retention_days"]
        no_delete = options["no_delete"]
        batch_size = options["batch_size"]

        cutoff_date = timezone.now() - timedelta(days=retention_days)
        self.stdout.write("Audit log archive started")
        self.stdout.write(f"  Retention: {retention_days} days")
        self.stdout.write(f"  Cutoff date: {cutoff_date.isoformat()}")
        self.stdout.write(f"  Dry run: {dry_run}")
        self.stdout.write("  Delete after archive: False (integrity retention guard)")

        queryset = AuditLog.objects.filter(timestamp__lt=cutoff_date)
        total_count = queryset.count()
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("No audit logs to archive"))
            return

        self.stdout.write(f"  Records to archive: {total_count}")

        if dry_run:
            sample = queryset.order_by("timestamp")[:5]
            self.stdout.write("\nSample records that would be archived:")
            for record in sample:
                self.stdout.write(
                    f"  - {record.timestamp.isoformat()} | {record.action} {record.entity_type} {record.entity_id}"
                )
            self.stdout.write(self.style.WARNING("\nDry run - no changes made"))
            return

        prepared = self._prepare_upload()
        if prepared is None:
            return
        s3_client, bucket_name, expected_bucket_owner = prepared

        archived_count = 0
        deleted_count = 0
        batch_num = 0
        offset = 0
        while True:
            batch = list(queryset.order_by("sequence")[offset : offset + batch_size])
            if not batch:
                break
            batch_num += 1
            archived, deleted, ok = self._archive_one_batch(
                s3_client,
                batch,
                bucket_name,
                expected_bucket_owner,
                batch_num,
                no_delete,
            )
            archived_count += archived
            deleted_count += deleted
            if not ok:
                break
            offset += len(batch)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Archive complete:"))
        self.stdout.write(f"  Records archived: {archived_count}")
        self.stdout.write(f"  Records deleted: {deleted_count}")
