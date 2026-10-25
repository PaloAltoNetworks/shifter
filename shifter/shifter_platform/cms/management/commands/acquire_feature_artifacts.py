"""Request acquisition of every registered pack's declared feature artifacts (ADR-034-R12).

Run during deploy content bootstrap so recipe-acquired artifacts (#2463) are ready
before the first range needs them. It only claims acquisitions; the provisioner
launcher runs the isolated acquisition Jobs. A deployment without an acquisition
Job image requests nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Claim feature-artifact acquisition for every registered pack (deploy bootstrap)."""

    help = "Request acquisition of registered packs' declared feature artifacts"

    def handle(self, *args: Any, **options: Any) -> None:
        """Request each pack's artifacts; one unassessable pack never blocks the rest."""
        from cms.models import RaesPackageSource
        from cms.raes.feature_artifacts import acquisition_enabled, request_pack_feature_artifacts

        if not acquisition_enabled():
            self.stdout.write("feature artifact acquisition is not enabled on this deployment")
            return
        requested = 0
        for scenario_id in RaesPackageSource.objects.order_by("scenario_id").values_list("scenario_id", flat=True):
            try:
                requested += request_pack_feature_artifacts(scenario_id)
            except Exception as exc:
                # One unassessable pack never blocks the others or the deploy.
                logger.warning(
                    "acquire_feature_artifacts: skipped scenario_id=%s error=%s", scenario_id, type(exc).__name__
                )
        self.stdout.write(f"requested {requested} feature artifact acquisition(s)")
