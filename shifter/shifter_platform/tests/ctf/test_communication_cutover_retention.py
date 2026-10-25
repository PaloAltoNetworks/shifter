"""Migrated content obeys the same physical retention window as the ledger."""

import pytest
from django.utils import timezone

from ctf.models import CommunicationCampaign, CTFNotification, LegacyCommunication, MessageRevision
from ctf.services.communication.cutover import activate_cutover, migrate_legacy_batch, start_cutover
from ctf.services.communication.retention import purge_expired_communications

pytestmark = pytest.mark.django_db


def test_expired_migrated_content_is_erased_and_cannot_be_remigrated(organizer_user, ctf_event):
    row = CTFNotification.objects.create(
        event=ctf_event,
        created_by=organizer_user,
        notification_type="announcement",
        subject="Old notice",
        body="retained-content-canary",
    )
    start_cutover(legacy_producers_stopped=True)
    migrate_legacy_batch()
    activate_cutover()
    result = purge_expired_communications(now=ctf_event.event_end + timezone.timedelta(days=31), retention_days=30)
    assert result["campaigns_purged"] == 1
    assert not CTFNotification.all_objects.filter(pk=row.pk).exists()
    assert not LegacyCommunication.objects.exists()
    assert not MessageRevision.objects.exists()
    assert not CommunicationCampaign.all_objects.exists()
    assert migrate_legacy_batch() == 0
