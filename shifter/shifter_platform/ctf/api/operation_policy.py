"""Explicit action and scope locator inventory for canonical CTF API operations.

This S5 contract is used by coverage validation. S8 wires these bindings to
live admission after the coordinated authority cutover in ADR-066.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    """One operation's registered action and SQL-owned target locator."""

    actions: tuple[str, ...]
    target: str | None
    locator: str | None
    exemption: str | None = None
    selector: str | None = None


_MANAGE_AWARDS = "event.manage_awards"
_MANAGE_CHALLENGES = "event.manage_challenges"
_MANAGE_COMMUNICATIONS = "event.manage_communications"
_MANAGE_CONFIG = "event.manage_config"
_MANAGE_CONTENT = "event.manage_content"
_MANAGE_LIFECYCLE = "event.manage_lifecycle"
_MANAGE_PARTICIPANTS = "event.manage_participants"
_MANAGE_RANGES = "event.manage_ranges"
_MANAGE_SCORING = "event.manage_scoring"
_MANAGE_STAFF = "event.manage_staff"
_DELETE_EVENT = "event.delete"
_PARTICIPATE = "event.participate"


API_OPERATION_POLICY: dict[str, OperationPolicy] = {
    "ctf_awards_delete_create": OperationPolicy((_MANAGE_AWARDS,), "event", "award"),
    "ctf_challenges_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_update": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_destroy": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_files_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_files_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_flags_add_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_hint_create": OperationPolicy((_PARTICIPATE,), "event", "challenge"),
    "ctf_challenges_hints_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_hints_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_prerequisites_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_prerequisites_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "ctf_challenges_rate_create": OperationPolicy((_PARTICIPATE,), "event", "challenge"),
    "ctf_challenges_submit_create": OperationPolicy((_PARTICIPATE,), "event", "challenge"),
    "ctf_communications_list": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign_collection"),
    "ctf_communications_create": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign_collection"),
    "ctf_communications_retrieve": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign"),
    "ctf_communications_cancel_create": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign"),
    "ctf_communications_release_create": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign"),
    "ctf_communications_revisions_create": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "campaign"),
    "ctf_events_list": OperationPolicy(("event.read",), "event", "event_discovery"),
    "ctf_events_create": OperationPolicy(
        ("account.create_event", "organization.create_event", "workspace.create_event"),
        "parent",
        "parent",
        selector="validated_parent_placement",
    ),
    "ctf_events_retrieve": OperationPolicy(("event.read",), "event", "event"),
    "ctf_events_update": OperationPolicy((_MANAGE_CONFIG,), "event", "event"),
    "ctf_events_destroy": OperationPolicy((_DELETE_EVENT,), "event", "event"),
    "ctf_events_analytics_retrieve": OperationPolicy((_MANAGE_SCORING,), "event", "event"),
    "ctf_events_challenges_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "event"),
    "ctf_events_challenges_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "event"),
    "ctf_events_challenges_export_retrieve": OperationPolicy((_MANAGE_CHALLENGES,), "event", "event"),
    "ctf_events_challenges_import_pack_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "event"),
    "ctf_events_cleanup_create": OperationPolicy((_MANAGE_LIFECYCLE,), "event", "event"),
    "ctf_events_content_refresh_create": OperationPolicy((_MANAGE_CONTENT,), "event", "event"),
    "ctf_events_email_templates_retrieve": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_events_email_templates_update": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_events_email_templates_destroy": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_events_force_delete_create": OperationPolicy((_DELETE_EVENT,), "event", "event"),
    "ctf_events_lifecycle_create": OperationPolicy((_MANAGE_LIFECYCLE,), "event", "event"),
    "ctf_events_model_access_assessment_retrieve": OperationPolicy((_MANAGE_CONFIG,), "event", "event"),
    "ctf_events_notifications_retrieve": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_organizer_scoreboard": OperationPolicy((_MANAGE_SCORING,), "event", "event"),
    "ctf_events_pages_retrieve": OperationPolicy((_MANAGE_CONTENT,), "event", "event"),
    "ctf_events_pages_create": OperationPolicy((_MANAGE_CONTENT,), "event", "event"),
    "ctf_events_participants_retrieve": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "event"),
    "ctf_events_participants_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "event"),
    "ctf_events_participants_import_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "event"),
    "ctf_events_principal_participants_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "event"),
    "ctf_events_ranges_retrieve": OperationPolicy((_MANAGE_RANGES,), "event", "event"),
    "ctf_events_ranges_provision_create": OperationPolicy((_MANAGE_RANGES,), "event", "event"),
    "ctf_events_registration_requests_retrieve": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "event"),
    "ctf_events_results_export_retrieve": OperationPolicy((_MANAGE_SCORING,), "event", "event"),
    "ctf_events_scoreboard_retrieve": OperationPolicy(
        (_PARTICIPATE,),
        "event",
        "event",
        "scoreboard_publication",
        "publication_or_participation",
    ),
    "ctf_events_spares_create": OperationPolicy((_MANAGE_RANGES,), "event", "event"),
    "ctf_events_staff_retrieve": OperationPolicy((_MANAGE_STAFF,), "event", "event"),
    "ctf_events_staff_create": OperationPolicy((_MANAGE_STAFF,), "event", "event"),
    "ctf_events_staff_destroy": OperationPolicy((_MANAGE_STAFF,), "event", "event"),
    "ctf_events_tasks_retrieve": OperationPolicy((_MANAGE_LIFECYCLE,), "event", "event"),
    "ctf_events_tasks_run_create": OperationPolicy((_MANAGE_LIFECYCLE,), "event", "event"),
    "ctf_events_transfer_ownership_create": OperationPolicy(("event.transfer_ownership",), "event", "event"),
    "ctf_events_webhooks_retrieve": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_events_webhooks_create": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "event"),
    "ctf_files_delete_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "file"),
    "ctf_files_download_retrieve": OperationPolicy(
        (_MANAGE_CHALLENGES, _PARTICIPATE), "event", "file", selector="file_audience"
    ),
    "ctf_flags_remove_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "flag"),
    "ctf_hints_delete_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "hint"),
    "ctf_me_announcements_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_briefing_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_challenges_list": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_challenges_retrieve": OperationPolicy((_PARTICIPATE,), "event", "challenge"),
    "ctf_me_event_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_communication_inbox_list": OperationPolicy((_PARTICIPATE,), "event", "event"),
    "ctf_me_events_communications_retrieve": OperationPolicy((_PARTICIPATE,), "event", "event"),
    "ctf_me_events_communications_acknowledge_create": OperationPolicy((_PARTICIPATE,), "event", "event"),
    "ctf_me_events_communications_read_create": OperationPolicy((_PARTICIPATE,), "event", "event"),
    "ctf_me_events_participant_retrieve": OperationPolicy((_PARTICIPATE,), "event", "event"),
    "ctf_me_model_access_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_pages_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_profile_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_profile_partial_update": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_create_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_disband_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_join_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_leave_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_regenerate_code_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_remove_member_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_rename_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_team_transfer_captaincy_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_me_username_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_pages_update": OperationPolicy((_MANAGE_CONTENT,), "event", "page"),
    "ctf_pages_destroy": OperationPolicy((_MANAGE_CONTENT,), "event", "page"),
    "ctf_participants_retrieve": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_destroy": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_awards_retrieve": OperationPolicy((_MANAGE_AWARDS,), "event", "participant"),
    "ctf_participants_awards_create": OperationPolicy((_MANAGE_AWARDS,), "event", "participant"),
    "ctf_participants_ban_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_bracket_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_disqualify_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_hidden_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_password_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_range_destroy_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_range_provision_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_range_recover_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_range_restart_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_range_start_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_range_stop_create": OperationPolicy((_MANAGE_RANGES,), "event", "participant"),
    "ctf_participants_requalify_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_role_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_score_timeline_retrieve": OperationPolicy((_MANAGE_SCORING,), "event", "participant"),
    "ctf_participants_unban_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_participants_username_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "ctf_prerequisites_delete_create": OperationPolicy((_MANAGE_CHALLENGES,), "event", "prerequisite"),
    "ctf_range_access_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_range_status_retrieve": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_range_vpn_profile_create": OperationPolicy((_PARTICIPATE,), "event", "active_event"),
    "ctf_registration_requests_disposition_create": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "request"),
    "ctf_scenarios_retrieve": OperationPolicy((), None, None, "cms_model_access"),
    "ctf_submissions_retrieve": OperationPolicy(("event.manage_submissions",), "event", "submission_collection"),
    "ctf_webhooks_destroy": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "webhook"),
}


# The named browser routes render an SPA shell; protected data and effects live
# behind the API map above. The three non-shell handlers keep their own origin,
# password-change and event-publication checks.
_TEMPORARY_LOGIN_ROUTE_CATEGORY = "temporary_login"
NON_API_ROUTE_POLICY: dict[str, str] = {
    **dict.fromkeys(
        (
            "participant_dashboard",
            "participant_event",
            "challenges",
            "challenge_detail",
            "participant_range",
            "participant_terminal",
            "scoreboard",
            "participant_solve_history",
            "participant_team",
            "team_join",
            "ctf_help",
            "admin_dashboard",
            "admin_event_list",
            "admin_event_create",
            "admin_event_detail",
            "admin_event_edit",
            "admin_event_force_delete",
            "admin_challenge_list",
            "admin_challenge_create",
            "admin_challenge_detail",
            "admin_challenge_edit",
            "admin_participant_list",
            "admin_participant_import",
            "admin_participant_batch",
            "admin_participant_add",
            "admin_participant_detail",
            "admin_participant_rename",
            "admin_participant_email",
            "admin_participant_password",
            "admin_team_list",
            "admin_scoreboard",
            "admin_bracket_list",
            "admin_bracket_create",
            "admin_bracket_edit",
            "admin_bracket_delete",
            "admin_range_list",
            "admin_notification_list",
            "admin_notification_create",
            "admin_event_email_templates",
            "admin_analytics",
            "admin_challenge_file_upload",
        ),
        "spa_shell",
    ),
    "public_event_registration": "public_registration",
    "ctf_login": "login",
    "ctf_change_password": _TEMPORARY_LOGIN_ROUTE_CATEGORY,
}


CTF_COMMAND_POLICY: dict[str, str] = {
    "run_ctf_scheduler": "system_event",
    "drain_ctf_communication_deliveries": "system_event",
    "ctf_recompute_leaderboard": "system_event",
    "cutover_ctf_communications": "system_maintenance",
    "prune_ctf_communications": "system_maintenance",
}


# Scheduler rows are typed, event-bound execution facts. Lifecycle tasks are
# intrinsic effects of the event's committed schedule; they do not borrow the
# creator's later authority. A communication release carries its own durable
# initiating actor/token and reauthorizes inside the locked admission service.
# The retired notification handler fails closed for old rows.
CTF_SCHEDULED_EFFECT_POLICY: dict[str, str] = {
    "spin_up_ranges": "system_event_lifecycle",
    "cleanup_ranges": "system_event_lifecycle",
    "cleanup_warning": "system_event_lifecycle",
    "send_reminder": "system_event_lifecycle",
    "send_notification": "retired",
    "event_start": "system_event_lifecycle",
    "event_end": "system_event_lifecycle",
    "release_challenge": "system_event_lifecycle",
    "release_communication": "reauthorize_initiator",
}


# These are service entry points rather than HTTP operations. Their proof is
# the owning event/participant/receipt or trusted signal registration, never an
# actor id inferred from missing request state.
CTF_EXTERNAL_EFFECT_POLICY: dict[str, str] = {
    "submission_receipt": "signed_receipt_and_live_participant",
    "range_status_changed": "trusted_cms_signal_and_event_binding",
    "webhook_delivery": "committed_event_effect_and_pinned_destination",
    "communication_delivery": "admitted_intent_and_claim_fence",
}


# Django admin is a separate, session-only maintenance surface. These are its
# model and inline effect families; S8 must route each add/change/delete field
# operation through the same CTF service decision or close that write path.
CTF_DJANGO_ADMIN_POLICY: dict[str, OperationPolicy] = {
    "CTFEvent": OperationPolicy(
        (
            "account.create_event",
            "organization.create_event",
            "workspace.create_event",
            _MANAGE_CONFIG,
            _MANAGE_LIFECYCLE,
            "event.transfer_ownership",
            _DELETE_EVENT,
        ),
        "event",
        "event_or_parent",
        selector="field_and_placement",
    ),
    "CTFChallenge": OperationPolicy((_MANAGE_CHALLENGES,), "event", "challenge"),
    "CTFBracket": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "bracket"),
    "CTFTeam": OperationPolicy(("event.manage_teams",), "event", "team"),
    "CTFParticipant": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "participant"),
    "CTFSubmission": OperationPolicy(("event.manage_submissions",), "event", "submission"),
    "CTFAward": OperationPolicy((_MANAGE_AWARDS,), "event", "award"),
    "CTFPublicRegistrationRequest": OperationPolicy((_MANAGE_PARTICIPANTS,), "event", "request"),
    "CTFNotification": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "notification"),
    "CTFScheduledTask": OperationPolicy((_MANAGE_LIFECYCLE,), "event", "task"),
    "CTFChallengeFile": OperationPolicy((_MANAGE_CHALLENGES,), "event", "file"),
    "CTFChallengePrerequisite": OperationPolicy((_MANAGE_CHALLENGES,), "event", "prerequisite"),
    "CTFEmailTemplate": OperationPolicy((_MANAGE_COMMUNICATIONS,), "event", "email_template"),
}
