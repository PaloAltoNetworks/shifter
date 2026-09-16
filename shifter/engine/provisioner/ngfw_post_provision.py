"""NGFW post-provision strategy contract and local-dev adapter.

The post-provision step after NGFW Terraform apply runs one of two substitutable
strategies, selected once at the operation seam by
``ngfw_terraform._resolve_ngfw_post_provision``:

- the live PAN-OS SSH bring-up (``ngfw_terraform._run_pan_os_post_provision``),
  which stays in ``ngfw_terraform`` because it is coupled to the Terraform and
  SSH machinery there; and
- the local-dev short-circuit adapter defined here, used when PAN-OS is not
  reachable over SSH.

Both satisfy the :class:`_NgfwPostProvision` call signature, so the provider
provision paths invoke whichever strategy they are handed without branching.
"""

import logging
from typing import Any, Protocol

from shared.operation_results import ResultStep

from events import STATUS_PAUSED, STATUS_READY
from ngfw_runtime import update_instance_state
from ngfw_terraform_state import _build_provider_state

logger = logging.getLogger(__name__)


class _NgfwPostProvision(Protocol):
    """Post-Terraform NGFW bring-up strategy, resolved once at the operation seam.

    Substitutes environment-specific behaviour without an environment branch in
    the provisioning flow: production runs the live PAN-OS SSH bring-up, local
    dev runs the short-circuit adapter. Both share this call signature so the
    provider provision functions invoke the resolved collaborator without
    knowing which one they hold.
    """

    def __call__(
        self,
        *,
        request_id: str,
        instance_id: str,
        output_data: dict[str, Any],
        sls_region: str,
        operation_id: str | None = None,
    ) -> None:
        """Run the post-Terraform NGFW bring-up for one provision request."""


def _short_circuit_local_dev_post_provision(
    *,
    request_id: str,
    output_data: dict[str, Any],
    operation_id: str | None = None,
    **_unused: Any,
) -> None:
    """Mark a local-dev NGFW as ready-then-paused without touching the device.

    Substituted for the live PAN-OS bring-up by
    ``ngfw_terraform._resolve_ngfw_post_provision`` when running in local dev,
    where PAN-OS is not reachable over SSH. We still emit the ready and paused
    state transitions so the platform UI reflects the expected lifecycle. The
    live path's ``instance_id`` and ``sls_region`` seam arguments are absorbed
    by ``**_unused``; the short-circuit path needs neither.
    """
    logger.info("LOCAL DEV MODE: Skipping post-infrastructure NGFW configuration")
    ready_state = _build_provider_state(output_data)
    update_instance_state(
        request_id,
        STATUS_READY,
        step=ResultStep.NGFW_PROVISION_READY,
        operation_id=operation_id,
        operation="provision",
        ngfw_state=ready_state,
    )
    logger.info("LOCAL DEV MODE: Setting NGFW status to paused")
    update_instance_state(
        request_id,
        STATUS_PAUSED,
        step=ResultStep.NGFW_PROVISION_AUTOSTOP,
        operation_id=operation_id,
        operation="provision",
    )
