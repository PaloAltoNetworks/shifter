"""Canonical DRF views for the CTF JSON API."""

from __future__ import annotations

from typing import Any

from django.http import JsonResponse
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView

from ctf.api._base import (
    CTF_ORGANIZER_PERMISSIONS,
    CTF_PARTICIPANT_PERMISSIONS,
    CTF_ROLE_PERMISSIONS,
    _canonical_error_response,
    legacy_api_view,
)
from shared.api_tokens import scopes

EVENT_READ = (scopes.CTF_EVENT_READ,)
EVENT_WRITE = (scopes.CTF_EVENT_WRITE,)
PLAY_READ = (scopes.CTF_PLAY_READ,)
PLAY_WRITE = (scopes.CTF_PLAY_WRITE,)
EVENT_OR_PLAY_READ = (scopes.CTF_EVENT_READ, scopes.CTF_PLAY_READ)

api_event_list = legacy_api_view(
    "EventListView",
    "ctf.views.api.events.api_event_list",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_event_detail = legacy_api_view(
    "EventDetailView",
    "ctf.views.api.events.api_event_detail",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_force_delete_event = legacy_api_view(
    "ForceDeleteEventView",
    "ctf.views.api.events.api_force_delete_event",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_scenarios = legacy_api_view(
    "ScenarioListView",
    "ctf.views.api.events.api_scenarios",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
)
api_challenge_list = legacy_api_view(
    "ChallengeListView",
    "ctf.views.api.challenges.api_challenge_list",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_challenge_detail = legacy_api_view(
    "ChallengeDetailView",
    "ctf.views.api.challenges.api_challenge_detail",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_submit_flag = legacy_api_view(
    "SubmitFlagView",
    "ctf.views.api.play.api_submit_flag",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    write_scopes=PLAY_WRITE,
)
api_use_hint = legacy_api_view(
    "UseHintView",
    "ctf.views.api.play.api_use_hint",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    write_scopes=PLAY_WRITE,
)
api_challenge_hints = legacy_api_view(
    "ChallengeHintListView",
    "ctf.views.api.hints.api_challenge_hints",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_hint_delete = legacy_api_view(
    "HintDeleteView",
    "ctf.views.api.hints.api_hint_delete",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_rate_challenge = legacy_api_view(
    "RateChallengeView",
    "ctf.views.api.play.api_rate_challenge",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    write_scopes=PLAY_WRITE,
)
api_submissions = legacy_api_view(
    "SubmissionListView",
    "ctf.views.api.play.api_submissions",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    read_scopes=PLAY_READ,
)
api_participant_list = legacy_api_view(
    "ParticipantListView",
    "ctf.views.api.participants.api_participant_list",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_participant_import = legacy_api_view(
    "ParticipantImportView",
    "ctf.views.api.participants.api_participant_import",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_participant_detail = legacy_api_view(
    "ParticipantDetailView",
    "ctf.views.api.participants.api_participant_detail",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_participant_resend_invite = legacy_api_view(
    "ParticipantResendInviteView",
    "ctf.views.api.participants.api_participant_resend_invite",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_range_status = legacy_api_view(
    "ParticipantRangeStatusView",
    "ctf.views.api.ranges.api_range_status",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    read_scopes=PLAY_READ,
)
api_range_access = legacy_api_view(
    "ParticipantRangeAccessView",
    "ctf.views.api.ranges.api_range_access",
    permission_classes=CTF_PARTICIPANT_PERMISSIONS,
    read_scopes=PLAY_READ,
    write_scopes=PLAY_READ,
)
api_range_list = legacy_api_view(
    "EventRangeListView",
    "ctf.views.api.ranges.api_range_list",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
)
api_provision_ranges = legacy_api_view(
    "EventRangeProvisionView",
    "ctf.views.api.ranges.api_provision_ranges",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_provision_participant_range = legacy_api_view(
    "ParticipantRangeProvisionView",
    "ctf.views.api.ranges.api_provision_participant_range",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_destroy_participant_range = legacy_api_view(
    "ParticipantRangeDestroyView",
    "ctf.views.api.ranges.api_destroy_participant_range",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_stop_participant_range = legacy_api_view(
    "ParticipantRangeStopView",
    "ctf.views.api.ranges.api_stop_participant_range",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_start_participant_range = legacy_api_view(
    "ParticipantRangeStartView",
    "ctf.views.api.ranges.api_start_participant_range",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_restart_participant_range = legacy_api_view(
    "ParticipantRangeRestartView",
    "ctf.views.api.ranges.api_restart_participant_range",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_assign_bracket = legacy_api_view(
    "AssignBracketView",
    "ctf.views.admin_brackets.api_assign_bracket",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_score_timeline = legacy_api_view(
    "ScoreTimelineView",
    "ctf.views.api.scoreboard.api_score_timeline",
    permission_classes=CTF_ROLE_PERMISSIONS,
    read_scopes=EVENT_OR_PLAY_READ,
)
api_notification_list = legacy_api_view(
    "NotificationListView",
    "ctf.views.api.notifications.api_notification_list",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_notification_send = legacy_api_view(
    "NotificationSendView",
    "ctf.views.api.notifications.api_notification_send",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_event_email_template = legacy_api_view(
    "EventEmailTemplateView",
    "ctf.views.api.notifications.api_event_email_template",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_send_invitations = legacy_api_view(
    "SendInvitationsView",
    "ctf.views.api.ranges.api_send_invitations",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_add_flag = legacy_api_view(
    "AddFlagView",
    "ctf.views.api.flags.api_add_flag",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_remove_flag = legacy_api_view(
    "RemoveFlagView",
    "ctf.views.api.flags.api_remove_flag",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_challenge_files = legacy_api_view(
    "ChallengeFileListView",
    "ctf.views.api.files.api_challenge_files",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_challenge_file_delete = legacy_api_view(
    "ChallengeFileDeleteView",
    "ctf.views.api.files.api_challenge_file_delete",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)
api_file_download = legacy_api_view(
    "ChallengeFileDownloadView",
    "ctf.views.api.files.api_file_download",
    permission_classes=CTF_ROLE_PERMISSIONS,
    read_scopes=EVENT_OR_PLAY_READ,
)
api_challenge_prerequisites = legacy_api_view(
    "ChallengePrerequisiteListView",
    "ctf.views.api.prerequisites.api_challenge_prerequisites",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    read_scopes=EVENT_READ,
    write_scopes=EVENT_WRITE,
)
api_prerequisite_delete = legacy_api_view(
    "PrerequisiteDeleteView",
    "ctf.views.api.prerequisites.api_prerequisite_delete",
    permission_classes=CTF_ORGANIZER_PERMISSIONS,
    write_scopes=EVENT_WRITE,
)


class PublicScoreboardView(APIView):
    """Public event scoreboard read surface."""

    versioning_class = None
    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, event_id: Any) -> JsonResponse:
        """Return the public scoreboard payload for an event."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.services import get_event
        from ctf.services.scoring import get_scoreboard, get_team_scoreboard
        from ctf.views import _parsing

        try:
            event = get_event(event_id)
        except CTFNotFoundError:
            response = JsonResponse({"error": "Event not found"}, status=404)
            return _canonical_error_response(request, response) or response

        if not event.scoreboard_visible:
            return JsonResponse({"scoreboard_hidden": True})

        freeze_at = event.scoreboard_freeze_at if event.is_scoreboard_frozen else None
        bracket_param = request.query_params.get("bracket")
        brackets, _selected_bracket, bracket_id = _parsing._resolve_bracket_filter(event.id, bracket_param)
        rankings = (
            get_team_scoreboard(event.id, freeze_at=freeze_at)
            if event.team_mode
            else get_scoreboard(event.id, freeze_at=freeze_at)
        )
        bracket_rankings = None
        if bracket_id:
            bracket_rankings = (
                get_team_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
                if event.team_mode
                else get_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
            )

        return JsonResponse(
            {
                "event_id": str(event.id),
                "team_mode": event.team_mode,
                "frozen": event.is_scoreboard_frozen,
                "rankings": rankings,
                "bracket_rankings": bracket_rankings,
                "brackets": [{"id": str(bracket.id), "name": bracket.name} for bracket in brackets],
            }
        )


api_scoreboard = PublicScoreboardView.as_view()

__all__ = [
    "api_add_flag",
    "api_assign_bracket",
    "api_challenge_detail",
    "api_challenge_file_delete",
    "api_challenge_files",
    "api_challenge_hints",
    "api_challenge_list",
    "api_challenge_prerequisites",
    "api_destroy_participant_range",
    "api_event_detail",
    "api_event_email_template",
    "api_event_list",
    "api_file_download",
    "api_force_delete_event",
    "api_hint_delete",
    "api_notification_list",
    "api_notification_send",
    "api_participant_detail",
    "api_participant_import",
    "api_participant_list",
    "api_participant_resend_invite",
    "api_prerequisite_delete",
    "api_provision_participant_range",
    "api_provision_ranges",
    "api_range_access",
    "api_range_list",
    "api_range_status",
    "api_rate_challenge",
    "api_remove_flag",
    "api_restart_participant_range",
    "api_scenarios",
    "api_score_timeline",
    "api_scoreboard",
    "api_send_invitations",
    "api_start_participant_range",
    "api_stop_participant_range",
    "api_submissions",
    "api_submit_flag",
    "api_use_hint",
]
