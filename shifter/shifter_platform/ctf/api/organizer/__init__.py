"""Canonical DRF organizer views for the CTF API.

Proper DRF replacements for the transitional ``legacy_api_view`` wrappers: each
view validates a request serializer, calls the authoritative ``ctf.services.*``
facade, and returns a typed response serializer, so the ``/api/v1/ctf/`` surface
carries real generated OpenAPI types for the SPA. Domain correctness
(validation, ownership, state machine, range teardown) stays in the service
layer; these views own only HTTP shape, permission/scope enforcement, and
per-event ownership resolution.

The views are split across cohesive modules (``events``, ``challenges``,
``attachments``, ``play``, ``participants``, ``moderation``, ``staff``, ``ranges``,
``notifications``, ``scoreboard``) over the shared helpers in :mod:`ctf.api.organizer._base`. This
package re-exports every view class so ``ctf.api.urls`` and any other importer
can reference them as ``organizer.<View>``.
"""

from __future__ import annotations

from ctf.api.organizer.attachments import (
    ChallengeFileDeleteView,
    ChallengeFilesView,
    ChallengePrerequisitesView,
    FileDownloadView,
    PrerequisiteDeleteView,
)
from ctf.api.organizer.awards import AwardRevokeView, ParticipantAwardsView
from ctf.api.organizer.challenges import (
    AddFlagView,
    ChallengeDetailView,
    ChallengeHintsView,
    ChallengeListView,
    HintDeleteView,
    RemoveFlagView,
)
from ctf.api.organizer.events import (
    EventDetailView,
    EventListView,
    ForceDeleteEventView,
    ScenarioListView,
)
from ctf.api.organizer.insights import (
    EventAnalyticsView,
    EventPageDetailView,
    EventPagesView,
)
from ctf.api.organizer.lifecycle import (
    EventCleanupControlView,
    EventLifecycleView,
    EventTasksView,
    TaskRunNowView,
)
from ctf.api.organizer.moderation import (
    ParticipantBanView,
    ParticipantDisqualifyView,
    ParticipantHiddenView,
    ParticipantRequalifyView,
    ParticipantRoleView,
    ParticipantUnbanView,
    ParticipantUsernameView,
)
from ctf.api.organizer.notifications import (
    EventEmailTemplateView,
    NotificationCancelScheduleView,
    NotificationListView,
    NotificationSendView,
    SendInvitationsView,
)
from ctf.api.organizer.participants import (
    AssignBracketView,
    ParticipantDetailView,
    ParticipantImportView,
    ParticipantListView,
    ParticipantResendInviteView,
)
from ctf.api.organizer.play import (
    RateChallengeView,
    SubmissionListView,
    SubmitFlagView,
    UseHintView,
)
from ctf.api.organizer.ranges import (
    EventRangeListView,
    EventRangeProvisionView,
    EventSpareProvisionView,
    ParticipantRangeAccessView,
    ParticipantRangeDestroyView,
    ParticipantRangeProvisionView,
    ParticipantRangeRecoverView,
    ParticipantRangeRestartView,
    ParticipantRangeStartView,
    ParticipantRangeStatusView,
    ParticipantRangeStopView,
    ParticipantVpnProfileView,
)
from ctf.api.organizer.scoreboard import (
    OrganizerScoreboardView,
    ScoreTimelineView,
)
from ctf.api.organizer.staff import EventStaffMemberView, EventStaffView
from ctf.api.organizer.transfer import (
    ChallengeExportView,
    ChallengeImportView,
    EventResultsExportView,
    EventWebhooksView,
    WebhookDetailView,
)

__all__ = [
    "AddFlagView",
    "AssignBracketView",
    "AwardRevokeView",
    "ChallengeDetailView",
    "ChallengeExportView",
    "ChallengeFileDeleteView",
    "ChallengeFilesView",
    "ChallengeHintsView",
    "ChallengeImportView",
    "ChallengeListView",
    "ChallengePrerequisitesView",
    "EventAnalyticsView",
    "EventCleanupControlView",
    "EventDetailView",
    "EventEmailTemplateView",
    "EventLifecycleView",
    "EventListView",
    "EventPageDetailView",
    "EventPagesView",
    "EventRangeListView",
    "EventRangeProvisionView",
    "EventResultsExportView",
    "EventSpareProvisionView",
    "EventStaffMemberView",
    "EventStaffView",
    "EventTasksView",
    "EventWebhooksView",
    "FileDownloadView",
    "ForceDeleteEventView",
    "HintDeleteView",
    "NotificationCancelScheduleView",
    "NotificationListView",
    "NotificationSendView",
    "OrganizerScoreboardView",
    "ParticipantAwardsView",
    "ParticipantBanView",
    "ParticipantDetailView",
    "ParticipantDisqualifyView",
    "ParticipantHiddenView",
    "ParticipantImportView",
    "ParticipantListView",
    "ParticipantRangeAccessView",
    "ParticipantRangeDestroyView",
    "ParticipantRangeProvisionView",
    "ParticipantRangeRecoverView",
    "ParticipantRangeRestartView",
    "ParticipantRangeStartView",
    "ParticipantRangeStatusView",
    "ParticipantRangeStopView",
    "ParticipantRequalifyView",
    "ParticipantResendInviteView",
    "ParticipantRoleView",
    "ParticipantUnbanView",
    "ParticipantUsernameView",
    "ParticipantVpnProfileView",
    "PrerequisiteDeleteView",
    "RateChallengeView",
    "RemoveFlagView",
    "ScenarioListView",
    "ScoreTimelineView",
    "SendInvitationsView",
    "SubmissionListView",
    "SubmitFlagView",
    "TaskRunNowView",
    "UseHintView",
    "WebhookDetailView",
]
