"""PostgreSQL semantics proof for the subnet-coordination boundary (#1838).

ADR-043-R6 moves reservation behind an Engine-owned coordination routine without
weakening what guarded it. Only real PostgreSQL can prove that: the EXCLUSIVE
table lock actually blocks a second reserver, a rolled-back transaction leaves no
reservation, the uniqueness constraint is a real backstop, and the routine is
reachable by EXECUTE alone. A SQLite or mock-backed test can assert none of it.
"""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from engine.models import OperationInput, Range, Request, SubnetAllocation
from engine.services import (
    read_subnet_reservation,
    release_subnet_reservation,
    reserve_subnet_cidrs,
)
from shared.operation_envelope import build_operation_envelope
from shared.subnet_coordination import (
    REASON_CONFLICT,
    REASON_EXHAUSTED,
    REASON_OPERATION_NOT_PERMITTED,
    REASON_STALE_GENERATION,
    REASON_UNKNOWN_OPERATION,
    SubnetCoordinationError,
    build_reservation_request,
)

# Opaque #1325 workspace scope binding (ADR-046-R3); this suite does not
# exercise tenancy.
_WORKSPACE_ID = 1
_NETWORK_ID = "range-network-test"
_NETWORK_CIDR = "10.1.0.0/16"
# Any well-formed fingerprint: these two tests exercise locking and rollback,
# not retry identity.
_FIRST_SHAPE = "sha256:" + "0" * 64

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _seed_range(
    *, current: bool = True, operation: str = "provision", resource: str = "range"
) -> tuple[str, str, Range]:
    """Create a Request/Range/OperationInput trio for one authorized operation.

    The operation input is what lets the routines check *which* operation is in
    flight, not merely that one is.
    """
    operation_id = uuid4()
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type=resource, user=user)
    range_row = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.PROVISIONING,
        provisioner_operation_id=operation_id if current else uuid4(),
    )
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=request_id,
        resource=resource,
        operation=operation,
        payload={"range_spec": {}},
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=request_id,
        resource=resource,
        operation=operation,
        contract_version=envelope["contract_version"],
        envelope=envelope,
    )
    return str(operation_id), str(request_id), range_row


def _request(operation_id: str, request_id: str, **overrides):
    base = {
        "operation_id": operation_id,
        "request_id": request_id,
        "network_id": _NETWORK_ID,
        "network_cidr": _NETWORK_CIDR,
        "prefix_length": 28,
        "subnets": ("0:attack", "1:victim"),
        "observed_cidrs": (),
    }
    base.update(overrides)
    return build_reservation_request(**base)


class TestReservation:
    def test_reserves_the_requested_batch_and_persists_it(self):
        operation_id, request_id, range_row = _seed_range()

        cidrs = reserve_subnet_cidrs(_request(operation_id, request_id))

        assert cidrs == ("10.1.2.0/28", "10.1.2.16/28")
        rows = SubnetAllocation.objects.filter(request_id=request_id).order_by("id")
        assert [row.cidr for row in rows] == list(cidrs)
        assert {row.range_id for row in rows} == {range_row.id}
        assert {row.subnet_size for row in rows} == {28}

    def test_skips_cidrs_already_reserved_by_another_range(self):
        first_op, first_req, _ = _seed_range()
        reserve_subnet_cidrs(_request(first_op, first_req))

        second_op, second_req, _ = _seed_range()
        cidrs = reserve_subnet_cidrs(_request(second_op, second_req))

        assert cidrs == ("10.1.2.32/28", "10.1.2.48/28")

    def test_skips_cidrs_observed_in_the_provider_but_untracked(self):
        # Drift repair: a subnet that exists in the cloud but not in the table
        # must become occupancy evidence, not get handed out again.
        operation_id, request_id, _ = _seed_range()

        cidrs = reserve_subnet_cidrs(
            _request(operation_id, request_id, subnets=("0:attack",), observed_cidrs=("10.1.2.0/28",))
        )

        assert cidrs == ("10.1.2.16/28",)
        drift = SubnetAllocation.objects.get(vpc_id=_NETWORK_ID, cidr="10.1.2.0/28")
        assert drift.range_id == 0
        assert drift.request_id == ""

    def test_skips_candidates_overlapping_a_wider_observed_network(self):
        # A /24 observed in the provider covers sixteen /28 candidates; overlap,
        # not string equality, is what makes them unavailable.
        operation_id, request_id, _ = _seed_range()

        cidrs = reserve_subnet_cidrs(
            _request(operation_id, request_id, subnets=("0:attack",), observed_cidrs=("10.1.2.0/24",))
        )

        assert cidrs == ("10.1.3.0/28",)

    def test_reserves_slash24_subnets_when_asked(self):
        operation_id, request_id, _ = _seed_range()

        cidrs = reserve_subnet_cidrs(_request(operation_id, request_id, prefix_length=24))

        assert cidrs == ("10.1.2.0/24", "10.1.3.0/24")

    def test_reserves_nothing_when_the_batch_cannot_be_satisfied(self):
        # All-or-nothing: a batch that cannot be filled must leave no partial
        # reservation behind for the next caller to trip over.
        operation_id, request_id, _ = _seed_range()
        tiny = _request(operation_id, request_id, network_cidr="10.9.0.0/16")
        SubnetAllocation.objects.bulk_create(
            SubnetAllocation(
                vpc_id=_NETWORK_ID,
                cidr=f"10.9.{third}.{fourth}/28",
                subnet_size=28,
                range_id=0,
                request_id="",
            )
            for third in range(2, 255)
            for fourth in range(0, 256, 16)
        )

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(tiny)

        assert REASON_EXHAUSTED in str(exc.value)
        assert not SubnetAllocation.objects.filter(request_id=request_id).exists()


class TestRetryIdentity:
    def test_retry_with_the_same_shape_returns_the_same_cidrs(self):
        operation_id, request_id, _ = _seed_range()
        first = reserve_subnet_cidrs(_request(operation_id, request_id))

        second = reserve_subnet_cidrs(_request(operation_id, request_id))

        assert second == first
        assert SubnetAllocation.objects.filter(request_id=request_id).count() == len(first)

    def test_retry_with_a_different_count_is_a_conflict(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))

        candidate = _request(operation_id, request_id, subnets=("0:a", "1:b", "2:c"))

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_CONFLICT in str(exc.value)
        assert SubnetAllocation.objects.filter(request_id=request_id).count() == 2

    def test_retry_against_a_different_network_is_a_conflict(self):
        # Scoping the retry check to the requested network would make this look
        # like a first reservation: it would allocate a second batch and strand
        # the first with no owner able to release it.
        operation_id, request_id, _ = _seed_range()
        first = reserve_subnet_cidrs(_request(operation_id, request_id))

        candidate = _request(operation_id, request_id, network_id="range-network-other")

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_CONFLICT in str(exc.value)
        assert SubnetAllocation.objects.filter(request_id=request_id).count() == len(first)

    def test_retry_with_a_different_prefix_length_is_a_conflict(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))

        candidate = _request(operation_id, request_id, prefix_length=24)

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_CONFLICT in str(exc.value)


class TestGenerationFencing:
    def test_a_stale_generation_cannot_reserve(self):
        # The caller supplies the operation id, so the routine must check it
        # against the Range's current generation rather than trust it.
        _, request_id, _ = _seed_range(current=False)

        candidate = _request(str(uuid4()), request_id)

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_STALE_GENERATION in str(exc.value)
        assert not SubnetAllocation.objects.filter(request_id=request_id).exists()

    def test_an_unknown_request_cannot_reserve(self):
        candidate = _request(str(uuid4()), str(uuid4()))

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_UNKNOWN_OPERATION in str(exc.value)

    def test_a_stale_generation_cannot_release(self):
        operation_id, request_id, range_row = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))
        range_row.provisioner_operation_id = uuid4()
        range_row.save(update_fields=["provisioner_operation_id"])

        with pytest.raises(SubnetCoordinationError):
            release_subnet_reservation(operation_id=operation_id, request_id=request_id)

        assert SubnetAllocation.objects.filter(request_id=request_id).count() == 2


class TestReadAndRelease:
    def test_read_returns_the_reservation_in_order(self):
        operation_id, request_id, _ = _seed_range()
        reserved = reserve_subnet_cidrs(_request(operation_id, request_id, subnets=("0:a", "1:b", "2:c")))

        assert read_subnet_reservation(operation_id=operation_id, request_id=request_id) == reserved

    def test_read_returns_empty_when_nothing_is_reserved(self):
        operation_id, request_id, _ = _seed_range()

        assert read_subnet_reservation(operation_id=operation_id, request_id=request_id) == ()

    def test_release_removes_only_the_owned_rows(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id, subnets=("0:attack",), observed_cidrs=("10.1.2.0/28",)))
        other_op, other_req, _ = _seed_range()
        reserve_subnet_cidrs(_request(other_op, other_req, subnets=("0:attack",)))

        released = release_subnet_reservation(operation_id=operation_id, request_id=request_id)

        assert released == 1
        assert not SubnetAllocation.objects.filter(request_id=request_id).exists()
        # Drift evidence is unowned occupancy, not this range's to give back.
        assert SubnetAllocation.objects.filter(cidr="10.1.2.0/28", range_id=0).exists()
        assert SubnetAllocation.objects.filter(request_id=other_req).count() == 1

    def test_release_is_idempotent(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))
        release_subnet_reservation(operation_id=operation_id, request_id=request_id)

        assert release_subnet_reservation(operation_id=operation_id, request_id=request_id) == 0


class TestSerialization:
    def test_the_table_lock_blocks_a_concurrent_reserver(self):
        """A second reserver must wait for the first transaction, not race it.

        This is the invariant ADR-043-R6 forbids weakening. The proof is that the
        second connection makes no progress while the first holds the lock, and
        then allocates a disjoint batch once the first commits -- exactly what a
        row lock, advisory lock, or ON CONFLICT retry would not give.
        """
        first_op, first_req, _ = _seed_range()
        second_op, second_req, _ = _seed_range()
        started = threading.Event()
        finished = threading.Event()
        result: dict[str, object] = {}

        def _second_reserver():
            started.wait(timeout=10)
            try:
                result["cidrs"] = reserve_subnet_cidrs(_request(second_op, second_req))
            except Exception as exc:  # surfaced by the assertions below
                result["error"] = exc
            finally:
                finished.set()
                connection.close()

        worker = threading.Thread(target=_second_reserver, daemon=True)
        worker.start()

        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT ordinal, subnet_cidr FROM engine_reserve_subnet_cidrs("
                "%s, %s::uuid, %s::uuid, %s, %s::cidr, %s, %s, %s::cidr[], %s)",
                ["1", first_op, first_req, _NETWORK_ID, _NETWORK_CIDR, 28, 2, "{}", _FIRST_SHAPE],
            )
            first = [row[1] for row in cursor.fetchall()]
            started.set()
            # The second reserver is now blocked on the EXCLUSIVE lock this
            # open transaction holds; if it were not, it would finish here.
            assert not finished.wait(timeout=2), "second reserver was not blocked by the table lock"
            cursor.execute("COMMIT")

        assert finished.wait(timeout=30), "second reserver never completed after the lock was released"
        worker.join(timeout=30)

        assert "error" not in result, f"second reserver failed: {result.get('error')}"
        assert set(first).isdisjoint(set(result["cidrs"]))

    def test_a_rolled_back_reservation_leaves_no_rows(self):
        operation_id, request_id, _ = _seed_range()

        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT ordinal, subnet_cidr FROM engine_reserve_subnet_cidrs("
                "%s, %s::uuid, %s::uuid, %s, %s::cidr, %s, %s, %s::cidr[], %s)",
                ["1", operation_id, request_id, _NETWORK_ID, _NETWORK_CIDR, 28, 2, "{}", _FIRST_SHAPE],
            )
            assert len(cursor.fetchall()) == 2
            cursor.execute("ROLLBACK")

        assert not SubnetAllocation.objects.filter(request_id=request_id).exists()

    def test_the_uniqueness_constraint_still_backstops_collisions(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id, subnets=("0:attack",)))

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            SubnetAllocation.objects.create(
                vpc_id=_NETWORK_ID,
                cidr="10.1.2.0/28",
                subnet_size=28,
                range_id=0,
                request_id="",
            )


class TestOperationKindAuthorization:
    """A current generation says an operation is in flight, not which one.

    Without binding each verb to the persisted operation, any current generation
    accepted for the range is sufficient for every verb -- a destroy generation
    could reserve, and a provision generation could release live reservations out
    from under an in-flight build.
    """

    def test_a_destroy_generation_cannot_reserve(self):
        operation_id, request_id, _ = _seed_range(operation="destroy")

        candidate = _request(operation_id, request_id)

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_OPERATION_NOT_PERMITTED in str(exc.value)
        assert not SubnetAllocation.objects.filter(request_id=request_id).exists()

    def test_a_pause_generation_cannot_release(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))
        paused_op, paused_req, paused_range = _seed_range(operation="pause")

        with pytest.raises(SubnetCoordinationError) as exc:
            release_subnet_reservation(operation_id=paused_op, request_id=paused_req)

        assert REASON_OPERATION_NOT_PERMITTED in str(exc.value)
        assert paused_range is not None

    def test_a_pause_generation_cannot_read(self):
        operation_id, request_id, _ = _seed_range(operation="pause")

        with pytest.raises(SubnetCoordinationError) as exc:
            read_subnet_reservation(operation_id=operation_id, request_id=request_id)

        assert REASON_OPERATION_NOT_PERMITTED in str(exc.value)

    def test_a_destroy_generation_may_read_and_release(self):
        # Destroy legitimately needs both: it reads the CIDRs to tear the range
        # down, then releases them.
        operation_id, request_id, _ = _seed_range()
        reserved = reserve_subnet_cidrs(_request(operation_id, request_id))
        destroy_op, destroy_req, destroy_range = _seed_range(operation="destroy")
        SubnetAllocation.objects.filter(request_id=request_id).update(request_id=destroy_req, range_id=destroy_range.id)

        assert read_subnet_reservation(operation_id=destroy_op, request_id=destroy_req) == reserved
        assert release_subnet_reservation(operation_id=destroy_op, request_id=destroy_req) == len(reserved)

    def test_a_generation_with_no_operation_input_is_refused(self):
        # Fail closed: without the persisted input the routine cannot tell which
        # operation it is serving.
        operation_id, request_id, _ = _seed_range()
        OperationInput.objects.filter(request_id=request_id).delete()

        candidate = _request(operation_id, request_id)

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_UNKNOWN_OPERATION in str(exc.value)


class TestRaesRangeOperationKindAuthorization:
    """RAES open-network realization uses the same fenced coordination policy."""

    def test_a_raes_provision_generation_may_reserve_read_and_compensate(self):
        operation_id, request_id, _ = _seed_range(resource="raes-range")

        reserved = reserve_subnet_cidrs(_request(operation_id, request_id, subnets=("0:backend-default",)))

        assert read_subnet_reservation(operation_id=operation_id, request_id=request_id) == reserved
        assert release_subnet_reservation(operation_id=operation_id, request_id=request_id) == 1

    def test_a_raes_destroy_generation_may_read_and_release_the_provision_reservation(self):
        provision_id, request_id, range_row = _seed_range(resource="raes-range")
        reserved = reserve_subnet_cidrs(_request(provision_id, request_id, subnets=("0:backend-default",)))
        destroy_id = uuid4()
        range_row.provisioner_operation_id = destroy_id
        range_row.save(update_fields=["provisioner_operation_id"])
        envelope = build_operation_envelope(
            operation_id=destroy_id,
            request_id=request_id,
            resource="raes-range",
            operation="destroy",
            payload={"range_spec": {}},
        )
        OperationInput.objects.create(
            operation_id=destroy_id,
            request_id=request_id,
            resource="raes-range",
            operation="destroy",
            contract_version=envelope["contract_version"],
            envelope=envelope,
        )

        assert read_subnet_reservation(operation_id=str(destroy_id), request_id=request_id) == reserved
        assert release_subnet_reservation(operation_id=str(destroy_id), request_id=request_id) == 1


class TestRetryShapeIdentity:
    """The retry check compares the whole realized shape, not just a count."""

    def test_retry_with_a_reordered_authored_spec_is_a_conflict(self):
        # Same count, same network, same prefix -- but position binds a subnet to
        # its CIDR, so returning the first batch would hand each subnet the
        # other's network.
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id, subnets=("0:attack", "1:victim")))

        candidate = _request(operation_id, request_id, subnets=("0:victim", "1:attack"))

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_CONFLICT in str(exc.value)

    def test_retry_with_a_different_base_cidr_is_a_conflict(self):
        operation_id, request_id, _ = _seed_range()
        reserve_subnet_cidrs(_request(operation_id, request_id))

        candidate = _request(operation_id, request_id, network_cidr="10.2.0.0/16")

        with pytest.raises(SubnetCoordinationError) as exc:
            reserve_subnet_cidrs(candidate)

        assert REASON_CONFLICT in str(exc.value)

    def test_the_reservation_records_its_shape(self):
        operation_id, request_id, _ = _seed_range()
        request = _request(operation_id, request_id)

        reserve_subnet_cidrs(request)

        shapes = set(SubnetAllocation.objects.filter(request_id=request_id).values_list("reservation_shape", flat=True))
        assert shapes == {request.shape_fingerprint}
