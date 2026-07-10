"""Compatibility exports for Mission Control DRF views."""

from __future__ import annotations

from mission_control.api.aces import (
    AcesOperationReceiptListView,
    AcesOperationStatusListView,
    AcesRuntimeSnapshotListView,
)
from mission_control.api.aces_participant import (
    AcesParticipantImplementationListView,
    AcesParticipantRuntimeListView,
)
from mission_control.api.guacamole import (
    GuacamoleBootstrapOpenView,
    GuacamoleBootstrapStatusView,
    GuacamoleNGFWSSHURLView,
    GuacamoleRangeSSHURLView,
    GuacamoleRDPURLView,
)
from mission_control.api.ranges import (
    AgentListView,
    CancelRangeView,
    CurrentRangeView,
    DestroyRangeView,
    LaunchRangeView,
    PauseRangeView,
    ResumeRangeView,
    ScenarioListView,
)
from mission_control.api.resources import (
    CredentialCreateView,
    CredentialDeleteView,
    NGFWCreateView,
    NGFWDestroyView,
    NGFWListView,
)
from mission_control.api.uploads import UploadCancelView, UploadCompleteView, UploadInitiateView
from mission_control.views._guacamole import _get_guac_settings

# Legacy ``mission_control.views`` export names. These remain callables so
# existing direct imports and URL names keep working while the implementation is
# DRF underneath.
get_range = CurrentRangeView.as_view()
launch_range = LaunchRangeView.as_view()
cancel_range = CancelRangeView.as_view()
destroy_range = DestroyRangeView.as_view()
pause_range = PauseRangeView.as_view()
resume_range = ResumeRangeView.as_view()
list_agents = AgentListView.as_view()
list_scenarios = ScenarioListView.as_view()
initiate_upload = UploadInitiateView.as_view()
complete_upload = UploadCompleteView.as_view()
cancel_upload = UploadCancelView.as_view()
guacamole_rdp_url = GuacamoleRDPURLView.as_view()
guacamole_ssh_url = GuacamoleRangeSSHURLView.as_view()
api_ngfw_ssh_url = GuacamoleNGFWSSHURLView.as_view()
guacamole_bootstrap_status = GuacamoleBootstrapStatusView.as_view()
guacamole_bootstrap_open = GuacamoleBootstrapOpenView.as_view()
api_ngfw_create = NGFWCreateView.as_view()
api_ngfw_list = NGFWListView.as_view()
api_ngfw_destroy = NGFWDestroyView.as_view()
api_credential_create = CredentialCreateView.as_view()
api_credential_delete = CredentialDeleteView.as_view()

__all__ = (
    "AcesOperationReceiptListView",
    "AcesOperationStatusListView",
    "AcesParticipantImplementationListView",
    "AcesParticipantRuntimeListView",
    "AcesRuntimeSnapshotListView",
    "AgentListView",
    "CancelRangeView",
    "CredentialCreateView",
    "CredentialDeleteView",
    "CurrentRangeView",
    "DestroyRangeView",
    "GuacamoleBootstrapOpenView",
    "GuacamoleBootstrapStatusView",
    "GuacamoleNGFWSSHURLView",
    "GuacamoleRDPURLView",
    "GuacamoleRangeSSHURLView",
    "LaunchRangeView",
    "NGFWCreateView",
    "NGFWDestroyView",
    "NGFWListView",
    "PauseRangeView",
    "ResumeRangeView",
    "ScenarioListView",
    "UploadCancelView",
    "UploadCompleteView",
    "UploadInitiateView",
    "_get_guac_settings",
    "api_credential_create",
    "api_credential_delete",
    "api_ngfw_create",
    "api_ngfw_destroy",
    "api_ngfw_list",
    "api_ngfw_ssh_url",
    "cancel_range",
    "cancel_upload",
    "complete_upload",
    "destroy_range",
    "get_range",
    "guacamole_bootstrap_open",
    "guacamole_bootstrap_status",
    "guacamole_rdp_url",
    "guacamole_ssh_url",
    "initiate_upload",
    "launch_range",
    "list_agents",
    "list_scenarios",
    "pause_range",
    "resume_range",
)
