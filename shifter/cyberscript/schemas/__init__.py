"""Pydantic schemas for data contracts."""

from .action import (
    ActionContext,
    ActionContextBase,
    ActionRef,
    ActionSpec,
    ActionSpecBase,
    CommandActionContext,
    CommandActionSpec,
    FileActionContext,
    FileActionSpec,
    GenericActionContext,
    GenericActionSpec,
    NetworkActionContext,
    NetworkActionSpec,
)
from .app import (
    AgentAppContext,
    AgentAppSpec,
    AppContext,
    AppContextBase,
    AppRef,
    AppSpecBase,
    LinkedRangeContext,
    NGFWAppContext,
    NGFWAppRef,
    NGFWAppSpec,
    OSAppContext,
    OSAppSpec,
    OtherAppContext,
    OtherAppSpec,
)
from .base import SpecBase
from .behaviour import (
    AttackBehaviourContext,
    AttackBehaviourSpec,
    BehaviourContext,
    BehaviourContextBase,
    BehaviourRef,
    BehaviourResult,
    BehaviourSpec,
    BehaviourSpecBase,
    BehaviourStatus,
    CapabilityType,
    DefenderBehaviourContext,
    DefenderBehaviourSpec,
    SimulatedUserBehaviourContext,
    SimulatedUserBehaviourSpec,
)
from .credentials import (
    CredentialContext,
    CredentialContextBase,
    CredentialRef,
    CredentialSpecBase,
    DeploymentProfileContext,
    DeploymentProfileSpec,
    SCMCredentialContext,
    SCMCredentialSpec,
)
from .objective import (
    ObjectiveContext,
    ObjectivePriority,
    ObjectiveRef,
    ObjectiveResult,
    ObjectiveSpec,
    ObjectiveStatus,
    ObjectiveType,
)
from .range import (
    AgentDetails,
    DCConfig,
    InstanceContext,
    InstanceContextBase,
    InstanceRef,
    InstanceSpec,
    RangeContext,
    RangeContextBase,
    RangeRef,
    RangeSpec,
    RangeSpecBase,
)
from .request import RequestSpec
from .step import (
    FailureAction,
    StepContext,
    StepRef,
    StepResult,
    StepSpec,
    StepStatus,
)
from .subnet import SubnetContext, SubnetRef, SubnetSpec


# Rebuild models to resolve forward references after all imports complete
# This must be done here to avoid circular import issues
def _rebuild_all_models() -> None:
    """Rebuild all models with forward references."""
    # Build namespace with all types needed for forward references
    _types_namespace = {
        "NGFWAppSpec": NGFWAppSpec,
        "InstanceSpec": InstanceSpec,
        "SubnetSpec": SubnetSpec,
        "ActionSpec": ActionSpec,
        "StepSpec": StepSpec,
        "ObjectiveSpec": ObjectiveSpec,
    }
    # InstanceSpec needs NGFWAppSpec resolved
    InstanceSpec.model_rebuild(_types_namespace=_types_namespace)
    # SubnetSpec needs InstanceSpec resolved
    SubnetSpec.model_rebuild(_types_namespace=_types_namespace)
    # RangeSpecBase and RangeSpec need SubnetSpec resolved
    RangeSpecBase.model_rebuild(_types_namespace=_types_namespace)
    RangeSpec.model_rebuild(_types_namespace=_types_namespace)
    # StepSpec needs ActionSpec resolved
    StepSpec.model_rebuild(_types_namespace=_types_namespace)
    # BehaviourSpecBase needs StepSpec and ObjectiveSpec resolved
    BehaviourSpecBase.model_rebuild(_types_namespace=_types_namespace)
    AttackBehaviourSpec.model_rebuild(_types_namespace=_types_namespace)
    DefenderBehaviourSpec.model_rebuild(_types_namespace=_types_namespace)
    SimulatedUserBehaviourSpec.model_rebuild(_types_namespace=_types_namespace)


_rebuild_all_models()

__all__ = [
    # Action schemas
    "ActionContext",
    "ActionContextBase",
    "ActionRef",
    "ActionSpec",
    "ActionSpecBase",
    "CommandActionContext",
    "CommandActionSpec",
    "FileActionContext",
    "FileActionSpec",
    "GenericActionContext",
    "GenericActionSpec",
    "NetworkActionContext",
    "NetworkActionSpec",
    # App schemas
    "AgentAppContext",
    "AgentAppSpec",
    "AgentDetails",
    "AppContext",
    "AppContextBase",
    "AppRef",
    "AppSpecBase",
    # Behaviour schemas
    "AttackBehaviourContext",
    "AttackBehaviourSpec",
    "BehaviourContext",
    "BehaviourContextBase",
    "BehaviourRef",
    "BehaviourResult",
    "BehaviourSpec",
    "BehaviourSpecBase",
    "BehaviourStatus",
    "CapabilityType",
    "DefenderBehaviourContext",
    "DefenderBehaviourSpec",
    "SimulatedUserBehaviourContext",
    "SimulatedUserBehaviourSpec",
    # Credential schemas
    "CredentialContext",
    "CredentialContextBase",
    "CredentialRef",
    "CredentialSpecBase",
    "DCConfig",
    "DeploymentProfileContext",
    "DeploymentProfileSpec",
    # Range schemas
    "InstanceContext",
    "InstanceContextBase",
    "InstanceRef",
    "InstanceSpec",
    "LinkedRangeContext",
    "NGFWAppContext",
    "NGFWAppRef",
    "NGFWAppSpec",
    # Objective schemas
    "ObjectiveContext",
    "ObjectivePriority",
    "ObjectiveRef",
    "ObjectiveResult",
    "ObjectiveSpec",
    "ObjectiveStatus",
    "ObjectiveType",
    # App schemas (continued)
    "OSAppContext",
    "OSAppSpec",
    "OtherAppContext",
    "OtherAppSpec",
    "RangeContext",
    "RangeContextBase",
    "RangeRef",
    "RangeSpec",
    "RangeSpecBase",
    "RequestSpec",
    "SCMCredentialContext",
    "SCMCredentialSpec",
    "SpecBase",
    # Step schemas
    "FailureAction",
    "StepContext",
    "StepRef",
    "StepResult",
    "StepSpec",
    "StepStatus",
    # Subnet schemas
    "SubnetContext",
    "SubnetRef",
    "SubnetSpec",
]
