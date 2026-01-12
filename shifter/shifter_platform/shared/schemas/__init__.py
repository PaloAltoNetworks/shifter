"""Pydantic schemas for data contracts."""

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
    BehaviourSpecBase,
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
    }
    # InstanceSpec needs NGFWAppSpec resolved
    InstanceSpec.model_rebuild(_types_namespace=_types_namespace)
    # SubnetSpec needs InstanceSpec resolved
    SubnetSpec.model_rebuild(_types_namespace=_types_namespace)
    # RangeSpecBase and RangeSpec need SubnetSpec resolved
    RangeSpecBase.model_rebuild(_types_namespace=_types_namespace)
    RangeSpec.model_rebuild(_types_namespace=_types_namespace)


_rebuild_all_models()

__all__ = [
    "AgentAppContext",
    "AgentAppSpec",
    "AgentDetails",
    "AppContext",
    "AppContextBase",
    "AppRef",
    "AppSpecBase",
    "AttackBehaviourContext",
    "AttackBehaviourSpec",
    "BehaviourContext",
    "BehaviourContextBase",
    "BehaviourRef",
    "BehaviourSpecBase",
    "CredentialContext",
    "CredentialContextBase",
    "CredentialRef",
    "CredentialSpecBase",
    "DCConfig",
    "DeploymentProfileContext",
    "DeploymentProfileSpec",
    "InstanceContext",
    "InstanceContextBase",
    "InstanceRef",
    "InstanceSpec",
    "LinkedRangeContext",
    "NGFWAppContext",
    "NGFWAppRef",
    "NGFWAppSpec",
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
    "SubnetContext",
    "SubnetRef",
    "SubnetSpec",
]
