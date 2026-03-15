"""Simplify SubnetAllocation table.

Row exists = subnet occupied. No row = free. No status lifecycle.
Drop status, confirmed_at, released_at columns. Rename reserved_at → created_at.
Replace partial unique index with simple unique constraint on (vpc_id, cidr).
Grant DELETE permission to provisioner (needed for release on destroy).
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    """Apply schema changes and re-grant permissions."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        -- Drop old partial unique index and status index
        DROP INDEX IF EXISTS unique_active_cidr_per_vpc;
        DROP INDEX IF EXISTS engine_subn_vpc_id_d1c5a7_idx;

        -- Clear any existing rows (table was unused due to bugs)
        DELETE FROM engine_subnetallocation;

        -- Drop columns
        ALTER TABLE engine_subnetallocation DROP COLUMN IF EXISTS status;
        ALTER TABLE engine_subnetallocation DROP COLUMN IF EXISTS confirmed_at;
        ALTER TABLE engine_subnetallocation DROP COLUMN IF EXISTS released_at;

        -- Rename reserved_at → created_at
        ALTER TABLE engine_subnetallocation RENAME COLUMN reserved_at TO created_at;

        -- Allow NULLs for range_id and request_id (drift-discovered subnets)
        ALTER TABLE engine_subnetallocation ALTER COLUMN range_id SET DEFAULT 0;
        ALTER TABLE engine_subnetallocation ALTER COLUMN request_id SET DEFAULT '';

        -- Add simple unique constraint
        ALTER TABLE engine_subnetallocation
            ADD CONSTRAINT unique_cidr_per_vpc UNIQUE (vpc_id, cidr);

        -- Add vpc_id index for fast lookups
        CREATE INDEX engine_subn_vpc_id_idx
            ON engine_subnetallocation (vpc_id);

        -- Grant provisioner DELETE (needed for release_subnet_allocations)
        GRANT SELECT, INSERT, UPDATE, DELETE ON engine_subnetallocation TO provisioner_lambda;
        """
    )


def backwards(apps, schema_editor):
    """Revert to old schema."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        -- Drop new constraint and index
        ALTER TABLE engine_subnetallocation DROP CONSTRAINT IF EXISTS unique_cidr_per_vpc;
        DROP INDEX IF EXISTS engine_subn_vpc_id_idx;

        -- Rename back
        ALTER TABLE engine_subnetallocation RENAME COLUMN created_at TO reserved_at;

        -- Re-add columns
        ALTER TABLE engine_subnetallocation ADD COLUMN status VARCHAR(10) DEFAULT 'reserved';
        ALTER TABLE engine_subnetallocation ADD COLUMN confirmed_at TIMESTAMPTZ;
        ALTER TABLE engine_subnetallocation ADD COLUMN released_at TIMESTAMPTZ;

        -- Re-add old indexes
        CREATE INDEX engine_subn_vpc_id_d1c5a7_idx
            ON engine_subnetallocation (vpc_id, status);
        CREATE UNIQUE INDEX unique_active_cidr_per_vpc
            ON engine_subnetallocation (vpc_id, cidr)
            WHERE status IN ('reserved', 'active');

        -- Revoke DELETE
        REVOKE DELETE ON engine_subnetallocation FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0018_add_subnet_allocation"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
