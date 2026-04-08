"""CTF Range service.

Provides integration with Shifter's range infrastructure for CTF events.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFEvent, CTFParticipant

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def provision_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Provision a range for a participant.

    Uses the event's scenario_id to create a range via CMS.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with range instance ID and initial status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If range provisioning fails.
    """
    logger.info("Provisioning range for participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.select_related("event", "user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if participant.user is None:
        raise CTFRangeError(
            "Participant must be registered before provisioning a range",
            details={"participant_id": str(participant_id)},
        )

    if participant.range_instance_id:
        raise CTFRangeError(
            "Participant already has a range assigned",
            details={
                "participant_id": str(participant_id),
                "range_instance_id": participant.range_instance_id,
            },
        )

    event = participant.event
    agents_by_os = event.range_config.get("agents_by_os", {}) if event.range_config else {}
    ngfw_enabled = event.range_config.get("ngfw_enabled", False) if event.range_config else False

    try:
        from ctf.bridges import cms_create_range, cms_find_range_instance_id

        result = cms_create_range(
            user=participant.user,
            scenario=event.scenario_id,
            agents_by_os=agents_by_os,
            ngfw_enabled=ngfw_enabled,
        )
    except Exception as e:
        logger.exception("Range provisioning failed for participant %s", participant_id)
        raise CTFRangeError(
            f"Range provisioning failed: {e}",
            details={"participant_id": str(participant_id)},
        ) from e

    # Store the RangeInstance reference
    range_instance_id = cms_find_range_instance_id(result.request_id)

    if range_instance_id:
        participant.range_instance_id = range_instance_id
    participant.range_status = "provisioning"
    participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])

    return {
        "participant_id": str(participant_id),
        "range_instance_id": participant.range_instance_id,
        "status": "provisioning",
    }


def provision_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Provision ranges for all participants in an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of successful, failed, and pending provisions.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Bulk provisioning ranges for event %s", event_id)

    try:
        CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event_id=event_id,
        range_instance_id__isnull=True,
    )

    successful = 0
    failed = 0
    errors = []

    for participant in participants:
        try:
            provision_participant_range_with_retry(participant.pk)
            successful += 1
        except Exception as e:
            failed += 1
            errors.append({"participant_id": str(participant.pk), "error": str(e)})
            logger.error(
                "Failed to provision range for participant %s: %s",
                participant.pk,
                e,
            )

    # Notify organizer of failures
    if errors:
        from ctf.services.notification import notify_organizer_provision_failure

        notify_organizer_provision_failure(event_id, errors)

    return {
        "event_id": str(event_id),
        "total": successful + failed,
        "successful": successful,
        "failed": failed,
        "errors": errors,
    }


def provision_event_ranges_throttled(
    event_id: UUID,
    spinup_window_seconds: int,
    shutdown_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Provision ranges for all participants with throttled pacing.

    Pacing strategy adapts to the cloud provider:
    - **AWS (default)**: Sequential provisioning with even delays across the
      spinup window (clamped to [5, 120]s). Avoids overwhelming ECS/Terraform.
    - **GCP (K8s)**: Batch provisioning with smaller inter-batch delays. K8s
      scheduler handles VM placement concurrently and the cluster autoscaler
      adds nodes as needed, so we can submit more aggressively.

    Args:
        event_id: UUID of the event.
        spinup_window_seconds: Total window (seconds) over which to spread requests.
        shutdown_check: Optional callable returning True when the caller
            wants to abort (e.g. SIGTERM received by management command).

    Returns:
        Dict with counts of successful, failed, and whether interrupted.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    from django.conf import settings

    logger.info(
        "Throttled provisioning for event %s (window=%ds)",
        event_id,
        spinup_window_seconds,
    )

    try:
        CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = list(
        CTFParticipant.objects.filter(
            event_id=event_id,
            range_instance_id__isnull=True,
        )
    )

    count = len(participants)
    if count == 0:
        return {
            "event_id": str(event_id),
            "total": 0,
            "successful": 0,
            "failed": 0,
            "errors": [],
            "interrupted": False,
        }

    cloud_provider = getattr(settings, "CLOUD_PROVIDER", "aws")

    if cloud_provider == "gcp":
        return _provision_throttled_gcp(
            event_id,
            participants,
            count,
            spinup_window_seconds,
            shutdown_check,
        )

    return _provision_throttled_sequential(
        event_id,
        participants,
        count,
        spinup_window_seconds,
        shutdown_check,
    )


def _provision_throttled_sequential(
    event_id: UUID,
    participants: list,
    count: int,
    spinup_window_seconds: int,
    shutdown_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Sequential provisioning for AWS — one at a time with even delays."""
    raw_delay = spinup_window_seconds / max(count, 1)
    delay = max(5.0, min(120.0, raw_delay))

    successful = 0
    failed = 0
    errors: list[dict[str, str]] = []
    interrupted = False

    for i, participant in enumerate(participants):
        if shutdown_check and shutdown_check():
            logger.info(
                "Throttled provisioning interrupted at %d/%d for event %s",
                i,
                count,
                event_id,
            )
            interrupted = True
            break

        try:
            provision_participant_range_with_retry(participant.pk)
            successful += 1
        except Exception as e:
            failed += 1
            errors.append({"participant_id": str(participant.pk), "error": str(e)})
            logger.error(
                "Failed to provision range for participant %s: %s",
                participant.pk,
                e,
            )

        logger.info(
            "Throttled provisioning progress for event %s: %d/%d (%d ready, %d failed)",
            event_id,
            i + 1,
            count,
            successful,
            failed,
        )

        if i < count - 1 and not (shutdown_check and shutdown_check()):
            time.sleep(delay)

    if errors:
        from ctf.services.notification import notify_organizer_provision_failure

        notify_organizer_provision_failure(event_id, errors)

    return {
        "event_id": str(event_id),
        "total": successful + failed,
        "successful": successful,
        "failed": failed,
        "errors": errors,
        "interrupted": interrupted,
    }


def _provision_throttled_gcp(
    event_id: UUID,
    participants: list,
    count: int,
    spinup_window_seconds: int,
    shutdown_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Batch provisioning for GCP — submit in batches with shorter delays.

    K8s handles scheduling concurrency, so we submit ranges in batches rather
    than one-by-one. The cluster autoscaler reacts to pending pods within
    ~30-60 seconds, so we pace batches to give it time to scale.

    Batch sizing:
    - batch_size = max(5, count // 10), capped at 20
    - inter-batch delay = max(10, spinup_window / number_of_batches), capped at 60s

    This means a 50-participant event with a 30-minute window processes in
    ~10 batches of 5, with ~3-minute gaps — but the K8s scheduler works on
    all 5 per batch concurrently.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from django.conf import settings as django_settings

    min_batch = getattr(django_settings, "CTF_GCP_BATCH_SIZE", 5)
    max_batch = getattr(django_settings, "CTF_GCP_MAX_BATCH_SIZE", 20)
    min_delay = getattr(django_settings, "CTF_GCP_MIN_BATCH_DELAY", 10)
    max_delay = getattr(django_settings, "CTF_GCP_MAX_BATCH_DELAY", 60)

    batch_size = max(min_batch, min(max_batch, count // 10 or min_batch))
    num_batches = (count + batch_size - 1) // batch_size
    raw_delay = spinup_window_seconds / max(num_batches, 1)
    batch_delay = max(float(min_delay), min(float(max_delay), raw_delay))

    logger.info(
        "GCP batch provisioning: event=%s count=%d batch_size=%d batches=%d delay=%.1fs",
        event_id,
        count,
        batch_size,
        num_batches,
        batch_delay,
    )

    successful = 0
    failed = 0
    errors: list[dict[str, str]] = []
    interrupted = False

    for batch_idx in range(num_batches):
        if shutdown_check and shutdown_check():
            logger.info(
                "GCP batch provisioning interrupted at batch %d/%d for event %s",
                batch_idx,
                num_batches,
                event_id,
            )
            interrupted = True
            break

        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, count)
        batch = participants[batch_start:batch_end]

        # Submit batch concurrently
        batch_results: list[tuple[str, bool, str]] = []
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(_provision_single, p.pk): p for p in batch}
            for future in as_completed(futures):
                participant = futures[future]
                try:
                    future.result()
                    batch_results.append((str(participant.pk), True, ""))
                except Exception as e:
                    batch_results.append((str(participant.pk), False, str(e)))

        for pid, ok, err in batch_results:
            if ok:
                successful += 1
            else:
                failed += 1
                errors.append({"participant_id": pid, "error": err})

        logger.info(
            "GCP batch provisioning progress for event %s: batch %d/%d complete, %d/%d ready, %d failed",
            event_id,
            batch_idx + 1,
            num_batches,
            successful,
            count,
            failed,
        )

        # Sleep between batches (skip after the last one)
        if batch_idx < num_batches - 1 and not (shutdown_check and shutdown_check()):
            time.sleep(batch_delay)

    if errors:
        from ctf.services.notification import notify_organizer_provision_failure

        notify_organizer_provision_failure(event_id, errors)

    return {
        "event_id": str(event_id),
        "total": successful + failed,
        "successful": successful,
        "failed": failed,
        "errors": errors,
        "interrupted": interrupted,
    }


def _provision_single(participant_id: UUID) -> dict[str, Any]:
    """Provision a single participant range (for use in thread pool)."""
    return provision_participant_range_with_retry(participant_id)


def get_range_status(participant_id: UUID) -> dict[str, Any]:
    """Get range status for a participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with range status information.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if not participant.range_instance_id:
        return {
            "participant_id": str(participant_id),
            "status": "not_assigned",
            "range_instance_id": None,
        }

    # Query CMS for fresh status via bridge
    from ctf.bridges import cms_get_range_status

    fresh_status = cms_get_range_status(participant.range_instance_id)

    # Update cached status if changed
    if fresh_status != participant.range_status:
        participant.range_status = fresh_status
        participant.save(update_fields=["range_status", "updated_at"])

    return {
        "participant_id": str(participant_id),
        "status": participant.range_status,
        "range_instance_id": participant.range_instance_id,
    }


def _get_participant_with_range(participant_id: UUID) -> CTFParticipant:
    """Load participant, validate it has a range and a linked user."""
    try:
        participant = CTFParticipant.objects.select_related("user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if not participant.range_instance_id:
        raise CTFRangeError(
            "No range assigned to participant",
            details={"participant_id": str(participant_id)},
        )

    if participant.user is None:
        raise CTFRangeError(
            "Participant has no linked user",
            details={"participant_id": str(participant_id)},
        )

    return participant


def stop_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Stop (pause) a participant's range."""
    logger.info("Stopping range for participant %s", participant_id)
    participant = _get_participant_with_range(participant_id)

    from ctf.bridges import cms_stop_range

    assert participant.range_instance_id is not None  # guaranteed by _get_participant_with_range
    cms_stop_range(participant.user, participant.range_instance_id)
    participant.range_status = "stopping"
    participant.save(update_fields=["range_status", "updated_at"])
    return {"participant_id": str(participant_id), "status": "stopping"}


def start_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Start (resume) a participant's stopped range."""
    logger.info("Starting range for participant %s", participant_id)
    participant = _get_participant_with_range(participant_id)

    from ctf.bridges import cms_start_range

    assert participant.range_instance_id is not None  # guaranteed by _get_participant_with_range
    cms_start_range(participant.user, participant.range_instance_id)
    participant.range_status = "resuming"
    participant.save(update_fields=["range_status", "updated_at"])
    return {"participant_id": str(participant_id), "status": "resuming"}


def restart_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Restart a participant's range (stop then start)."""
    logger.info("Restarting range for participant %s", participant_id)
    stop_participant_range(participant_id)
    return start_participant_range(participant_id)


def provision_participant_range_with_retry(
    participant_id: UUID,
    max_retries: int = 3,
    base_delay: int = 30,
) -> dict[str, Any]:
    """Provision a range with exponential backoff retry.

    Args:
        participant_id: UUID of the participant.
        max_retries: Maximum retry attempts after initial failure.
        base_delay: Base delay in seconds between retries (doubled each attempt).

    Returns:
        Dict with range instance ID, status, and retry count.
    """
    last_error = None

    for attempt in range(1 + max_retries):
        try:
            result = provision_participant_range(participant_id)
            if attempt > 0:
                logger.info(
                    "Provisioning succeeded on attempt %d for participant %s",
                    attempt + 1,
                    participant_id,
                )
            result["retries"] = attempt
            return result
        except CTFRangeError as e:
            # Don't retry validation errors (no user, already assigned)
            if "must be registered" in str(e) or "already has a range" in str(e):
                raise
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Provisioning attempt %d failed for participant %s, retrying in %ds: %s",
                    attempt + 1,
                    participant_id,
                    delay,
                    e,
                )
                time.sleep(delay)

    # All retries exhausted — mark as error
    try:
        participant = CTFParticipant.objects.get(pk=participant_id)
        participant.range_status = "error"
        participant.save(update_fields=["range_status", "updated_at"])
    except CTFParticipant.DoesNotExist:
        pass

    logger.error(
        "Provisioning failed after %d attempts for participant %s: %s",
        1 + max_retries,
        participant_id,
        last_error,
    )
    raise CTFRangeError(
        f"Provisioning failed after {1 + max_retries} attempts: {last_error}",
        details={"participant_id": str(participant_id), "retries": max_retries},
    ) from last_error


def cleanup_event_ranges(event_id: UUID) -> dict[str, Any]:
    """Cleanup (destroy) all ranges for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of destroyed and failed cleanups.

    Raises:
        CTFNotFoundError: If event doesn't exist.
    """
    logger.info("Cleaning up ranges for event %s", event_id)

    try:
        event = CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None

    participants = CTFParticipant.objects.filter(
        event=event,
        range_instance_id__isnull=False,
    ).select_related("user")

    destroyed = 0
    failed = 0

    for participant in participants:
        try:
            _destroy_single_range(participant, participant.user)
            destroyed += 1
        except Exception as e:
            failed += 1
            logger.error(
                "Failed to destroy range for participant %s: %s",
                participant.pk,
                e,
            )

    return {
        "event_id": str(event_id),
        "total": destroyed + failed,
        "destroyed": destroyed,
        "failed": failed,
    }


def destroy_participant_range(participant_id: UUID) -> dict[str, Any]:
    """Destroy range for a single participant.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with destruction status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
        CTFRangeError: If no range assigned.
    """
    logger.info("Destroying range for participant %s", participant_id)

    try:
        participant = CTFParticipant.objects.select_related("user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None

    if not participant.range_instance_id:
        raise CTFRangeError(
            "No range assigned to participant",
            details={"participant_id": str(participant_id)},
        )

    _destroy_single_range(participant, participant.user)

    return {
        "participant_id": str(participant_id),
        "status": "destroyed",
    }


def update_participant_range_status(participant_id: UUID) -> dict[str, Any]:
    """Poll CMS for fresh range status and update cached value.

    Args:
        participant_id: UUID of the participant.

    Returns:
        Dict with updated status.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    return get_range_status(participant_id)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _destroy_single_range(participant: CTFParticipant, user) -> None:
    """Destroy a single participant's range and clear fields."""
    from ctf.bridges import cms_destroy_range

    if participant.range_instance_id is None:
        logger.warning("No range_instance_id for participant %s, skipping destroy", participant.pk)
        return
    if user is None:
        logger.warning("No user for participant %s, skipping destroy", participant.pk)
        return
    cms_destroy_range(user, participant.range_instance_id)
    participant.range_instance_id = None
    participant.range_status = ""
    participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
