"""CMS signal receivers for engine events.

These receivers replace the SQS worker handler (cms.handlers.process_event).
They connect to Django signals emitted by the engine provisioner.
"""

from __future__ import annotations

import logging

from django.dispatch import receiver

from engine.signals import ngfw_status_changed, range_status_changed
from shared.enums import ResourceStatus

logger = logging.getLogger(__name__)


@receiver(range_status_changed)
def on_range_status_changed(sender, **kwargs) -> None:
    """Update CMS RangeInstance status when range status changes.

    Replaces cms.handlers.process_range_event.
    """
    from cms.models import RangeInstance

    request_id = kwargs.get("request_id")
    range_id = kwargs.get("range_id")
    user_id = kwargs.get("user_id")
    new_status = kwargs.get("new_status")

    if new_status is None:
        logger.warning("on_range_status_changed: missing new_status")
        return

    try:
        ResourceStatus(new_status)
    except ValueError:
        logger.error("on_range_status_changed: invalid status=%s", new_status)
        return

    # Look up RangeInstance — prefer request_id, fall back to range_id
    instance = None
    try:
        if request_id:
            instance = RangeInstance.objects.get(request__request_id=request_id)
        elif range_id is not None:
            instance = RangeInstance.objects.get(range_id=range_id)
        else:
            logger.warning("on_range_status_changed: missing both request_id and range_id")
            return
    except RangeInstance.DoesNotExist:
        logger.warning(
            "on_range_status_changed: RangeInstance not found request_id=%s range_id=%s",
            request_id,
            range_id,
        )
        return

    if instance.user_id != user_id:
        logger.error(
            "on_range_status_changed: user_id mismatch signal=%s instance=%s",
            user_id,
            instance.user_id,
        )
        return

    previous_status = instance.status
    instance.status = new_status

    try:
        instance.save(update_fields=["status"])
    except Exception:
        logger.exception("on_range_status_changed: DB error saving RangeInstance")
        return

    logger.info(
        "CMS updated RangeInstance: request_id=%s range_id=%s status=%s->%s",
        request_id,
        range_id,
        previous_status,
        new_status,
    )


@receiver(ngfw_status_changed)
def on_ngfw_status_changed(sender, **kwargs) -> None:
    """Update CMS Instance and App status on NGFW events.

    Replaces cms.handlers.process_ngfw_event / _handle_ngfw_event.
    """
    from cms.models import App, Instance

    instance_id = kwargs.get("instance_id")
    app_id = kwargs.get("app_id")
    status = kwargs.get("status")
    serial_number = kwargs.get("serial_number")

    if not instance_id or not app_id:
        logger.warning(
            "on_ngfw_status_changed: missing required fields instance_id=%s app_id=%s",
            instance_id,
            app_id,
        )
        return

    if status:
        try:
            ResourceStatus(status)
        except ValueError:
            logger.error("on_ngfw_status_changed: invalid status=%s", status)
            return

    # Update CMS Instance
    previous_instance_status = None
    try:
        cms_instance = Instance.objects.get(id=instance_id)
        previous_instance_status = cms_instance.status
        if status:
            cms_instance.status = status
            cms_instance.save(update_fields=["status"])
    except Instance.DoesNotExist:
        logger.warning("on_ngfw_status_changed: CMS Instance not found id=%s", instance_id)
    except Exception:
        logger.exception("on_ngfw_status_changed: DB error saving CMS Instance id=%s", instance_id)
        return

    # Update CMS App
    previous_app_status = None
    try:
        app = App.objects.get(id=app_id)
        previous_app_status = app.status
        update_fields = []

        if status:
            app.status = status
            update_fields.append("status")

        if serial_number:
            app.data = {**app.data, "serial_number": serial_number}
            update_fields.append("data")

        if update_fields:
            app.save(update_fields=update_fields)
    except App.DoesNotExist:
        logger.warning("on_ngfw_status_changed: CMS App not found id=%s", app_id)
    except Exception:
        logger.exception("on_ngfw_status_changed: DB error saving CMS App id=%s", app_id)
        return

    logger.info(
        "CMS processed NGFW signal: instance_id=%s (%s->%s) app_id=%s (%s->%s) serial=%s",
        instance_id,
        previous_instance_status,
        status or previous_instance_status,
        app_id,
        previous_app_status,
        status or previous_app_status,
        serial_number or "N/A",
    )
