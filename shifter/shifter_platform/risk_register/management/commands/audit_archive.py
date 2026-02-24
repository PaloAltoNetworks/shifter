"""Management command to archive old audit logs to S3."""

import gzip
import json
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from risk_register.models import AuditLog


class Command(BaseCommand):
    """Archive audit logs older than retention period to S3.

    Exports records to JSON Lines format, uploads to S3, then deletes
    from database.

    Usage:
        python manage.py audit_archive
        python manage.py audit_archive --dry-run
        python manage.py audit_archive --retention-days 30
        python manage.py audit_archive --no-delete
    """

    help = "Archive old audit logs to S3"

    def add_arguments(self, parser):
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
            help="Archive but don't delete from database",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10000,
            help="Number of records to process per batch (default: 10000)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        retention_days = options["retention_days"]
        no_delete = options["no_delete"]
        batch_size = options["batch_size"]

        cutoff_date = timezone.now() - timedelta(days=retention_days)

        self.stdout.write("Audit log archive started")
        self.stdout.write(f"  Retention: {retention_days} days")
        self.stdout.write(f"  Cutoff date: {cutoff_date.isoformat()}")
        self.stdout.write(f"  Dry run: {dry_run}")
        self.stdout.write(f"  Delete after archive: {not no_delete}")

        # Count records to archive
        queryset = AuditLog.objects.filter(timestamp__lt=cutoff_date)
        total_count = queryset.count()

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("No audit logs to archive"))
            return

        self.stdout.write(f"  Records to archive: {total_count}")

        if dry_run:
            # Show sample of what would be archived
            sample = queryset.order_by("timestamp")[:5]
            self.stdout.write("\nSample records that would be archived:")
            for record in sample:
                self.stdout.write(
                    f"  - {record.timestamp.isoformat()} | {record.action} {record.entity_type} {record.entity_id}"
                )
            self.stdout.write(self.style.WARNING("\nDry run - no changes made"))
            return

        # Get S3 bucket from settings or environment
        # Uses the existing logs bucket from log-aggregation infrastructure
        # Falls back to AUDIT_ARCHIVE_BUCKET for backward compatibility
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
            return

        try:
            import boto3
            from botocore.exceptions import ClientError

            s3_client = boto3.client("s3")
        except ImportError:
            self.stdout.write(self.style.ERROR("boto3 not installed. Install with: pip install boto3"))
            return

        # Process in batches
        archived_count = 0
        deleted_count = 0
        batch_num = 0

        while True:
            batch = list(queryset.order_by("timestamp")[:batch_size])
            if not batch:
                break

            batch_num += 1
            first_ts = batch[0].timestamp
            last_ts = batch[-1].timestamp

            # Generate S3 key based on date range
            s3_key = (
                f"audit-archive/{first_ts.year}/{first_ts.month:02d}/"
                f"audit_{first_ts.strftime('%Y%m%d_%H%M%S')}_"
                f"{last_ts.strftime('%Y%m%d_%H%M%S')}.jsonl.gz"
            )

            # Convert to JSON Lines format
            lines = []
            record_ids = []
            for record in batch:
                record_ids.append(record.id)
                lines.append(
                    json.dumps(
                        {
                            "id": record.id,
                            "entity_type": record.entity_type,
                            "entity_id": record.entity_id,
                            "action": record.action,
                            "actor_type": record.actor_type,
                            "actor_id": record.actor_id,
                            "timestamp": record.timestamp.isoformat(),
                            "previous_state": record.previous_state,
                            "new_state": record.new_state,
                            "context": record.context,
                            "source_ip": record.source_ip,
                            "user_agent": record.user_agent,
                            "request_id": record.request_id,
                        },
                        default=str,
                    )
                )

            # Compress and upload
            content = "\n".join(lines).encode("utf-8")
            compressed = gzip.compress(content)

            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=s3_key,
                    Body=compressed,
                    ContentType="application/x-ndjson",
                    ContentEncoding="gzip",
                )
                archived_count += len(batch)
                self.stdout.write(f"  Batch {batch_num}: Uploaded {len(batch)} records to s3://{bucket_name}/{s3_key}")
            except ClientError as e:
                self.stdout.write(self.style.ERROR(f"  Batch {batch_num}: S3 upload failed: {e}"))
                break

            # Delete from database if not --no-delete
            if not no_delete:
                AuditLog.objects.filter(id__in=record_ids).delete()
                deleted_count += len(record_ids)
                self.stdout.write(f"  Batch {batch_num}: Deleted {len(record_ids)} records from database")

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Archive complete:"))
        self.stdout.write(f"  Records archived: {archived_count}")
        self.stdout.write(f"  Records deleted: {deleted_count}")
