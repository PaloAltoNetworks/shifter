"""PostgreSQL semantics proof for Range.allocate_subnet_index serialization (#997).

``Range.allocate_subnet_index()`` takes a table-level
``LOCK TABLE mission_control_range IN EXCLUSIVE MODE`` so two concurrent
allocators cannot both read the same free index and hand it out twice. That lock
is *explicitly skipped under SQLite* (``engine/models/_range.py``), so the
sequential SQLite tests -- ``test_allocates_distinct_indices_for_multiple_ranges``
and the ``allocate_subnet_index`` integration suite -- cannot exercise the
contention path at all. Only real PostgreSQL can prove the lock actually blocks a
second allocator, the same pattern the subnet-coordination suite uses for its
reservation coordinator (``test_the_table_lock_blocks_a_concurrent_reserver``).
"""

from __future__ import annotations

import threading
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from engine.models import Range

# Opaque #1325 workspace scope binding (ADR-046-R3); this suite does not
# exercise tenancy.
_WORKSPACE_ID = 1

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


class TestSubnetIndexSerialization:
    def test_the_table_lock_blocks_a_concurrent_allocator(self):
        """A second allocator must wait for the lock holder, not race it.

        While one transaction holds the EXCLUSIVE table lock and commits the
        first allocation (index 1), a concurrent ``allocate_subnet_index()``
        makes no progress; once the lock is released it observes the committed
        row and returns a disjoint index (2). A lock-free read-then-write would
        let the second allocator read the still-empty table concurrently and
        return 1 as well -- the duplicate this lock exists to prevent.
        """
        user = get_user_model().objects.create_user(username="subnet-alloc@example.com")
        started = threading.Event()
        finished = threading.Event()
        result: dict[str, object] = {}

        def _second_allocator():
            started.wait(timeout=10)
            try:
                result["index"] = Range.allocate_subnet_index()
            except Exception as exc:  # surfaced by the assertions below
                result["error"] = exc
            finally:
                finished.set()
                connection.close()

        worker = threading.Thread(target=_second_allocator, daemon=True)
        worker.start()

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE mission_control_range IN EXCLUSIVE MODE")
            # The first allocator's effect, published only when this transaction
            # commits: index 1 becomes taken.
            Range.objects.create(
                workspace_id=_WORKSPACE_ID,
                uuid=uuid.uuid4(),
                user=user,
                status=Range.Status.READY,
                subnet_index=1,
            )
            started.set()
            # The worker is now blocked on the EXCLUSIVE lock this open
            # transaction holds; if it were not, it would finish here.
            assert not finished.wait(timeout=2), "second allocator was not blocked by the table lock"

        assert finished.wait(timeout=30), "second allocator never completed after the lock was released"
        worker.join(timeout=30)

        assert "error" not in result, f"second allocator failed: {result.get('error')}"
        assert result["index"] == 2
