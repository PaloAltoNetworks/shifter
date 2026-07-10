"""Runtime-safe ACES profile and operation sidecar constants.

The manifest builder imports the ACES SDL tooling; normal Django runtime paths
must not. Keep constants that model validators need here so sidecar persistence
can check Shifter's supported profile/version set without importing the builder.
"""

from __future__ import annotations

SHIFTER_BACKEND_NAME = "shifter"
SHIFTER_BACKEND_PROFILE = "provisioning-only"

SHIFTER_SUPPORTED_CONTRACT_VERSIONS = frozenset(
    {
        "backend-manifest-v2",
        "operation-receipt-v1",
        "operation-status-v1",
        "runtime-snapshot-v1",
    }
)

SHIFTER_SUPPORTED_SIDECAR_REFERENCE_VERSIONS = frozenset({"execution-plan-ref-v1"})

SHIFTER_SUPPORTED_OPERATION_RECORD_VERSIONS = (
    SHIFTER_SUPPORTED_CONTRACT_VERSIONS | SHIFTER_SUPPORTED_SIDECAR_REFERENCE_VERSIONS
) - {"backend-manifest-v2"}

OPERATION_RECORD_KIND_TO_CONTRACT_VERSIONS = {
    "operation_receipt": frozenset({"operation-receipt-v1"}),
    "operation_status": frozenset({"operation-status-v1"}),
    "runtime_snapshot": frozenset({"runtime-snapshot-v1"}),
    "execution_plan_ref": frozenset({"execution-plan-ref-v1"}),
}

# Participant-runtime sidecar record kinds (#1288, extended #1289). See
# ``shared.schemas.aces_participant_runtime`` for validation and
# ``shared.aces.participant_runtime`` for persistence. ``participant_evidence``
# and ``participant_behavior_history`` (#1289) are append/reference-oriented
# record kinds that cite scripts, prompts, dispatch receipts, transcripts,
# artifacts, and behavior events by ref + digest -- never their bodies.
PARTICIPANT_RECORD_KIND_TO_CONTRACT_VERSIONS = {
    "participant_implementation": frozenset({"participant-implementation-v1"}),
    "participant_runtime": frozenset({"participant-runtime-v1"}),
    "participant_behavior_history": frozenset({"participant-behavior-history-v1"}),
    "participant_evidence": frozenset({"participant-evidence-v1"}),
}

#: Participant-runtime profiles Shifter supports as a sidecar-writing backend.
#: A single value today; the extensibility seam is a new frozenset member.
SHIFTER_SUPPORTED_PARTICIPANT_RUNTIME_PROFILES = frozenset({"shifter-provisioning"})
