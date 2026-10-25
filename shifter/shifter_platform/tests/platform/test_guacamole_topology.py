"""Guacamole client topology invariants (issue #928).

Guacamole auth tokens are minted server-side and held in the serving pod's
process memory. With more than one ``guacamole-client`` replica, a token minted
on one replica is invalid when the browser's sticky session lands on a different
replica, so first-click RDP redirects to the Guacamole login. The fix is to keep
the client (token/web) tier pinned to exactly one replica and scale ``guacd``
(the per-connection protocol worker) for capacity instead.

Guacamole runs as pods from the shared Helm chart on every cloud (the legacy AWS
ECS guacamole module was retired), so the single-client invariant is enforced by
pinning ``guacamoleClient.replicas`` to 1 in every deployment values file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CHART_DIR = REPO_ROOT / "platform" / "charts" / "shifter"
CLIENT_DEPLOYMENT = CHART_DIR / "templates" / "guacamole-client-deployment.yaml"

# Every deployment values file (all clouds, all environments): the token/task
# affinity fix (#928) must hold identically everywhere.
DEPLOYMENT_VALUES_FILES = (
    "values-aws-dev.yaml",
    "values-aws-prod.yaml",
    "values-gcp-dev.yaml",
    "values-gcp-prod.yaml",
)


def test_client_replicas_are_values_driven() -> None:
    """The chart must template the client replica count from values so each env pins it."""
    deployment = CLIENT_DEPLOYMENT.read_text(encoding="utf-8")
    assert "replicas: {{ .Values.guacamoleClient.replicas }}" in deployment, (
        "guacamole-client Deployment must set replicas from .Values.guacamoleClient.replicas "
        "so every environment's values file controls the single-client posture (#928)"
    )


@pytest.mark.parametrize("values_file", DEPLOYMENT_VALUES_FILES)
def test_every_environment_pins_single_guacamole_client_replica(values_file: str) -> None:
    """Every deployment values file must run exactly one guacamole-client replica."""
    values = yaml.safe_load((CHART_DIR / values_file).read_text(encoding="utf-8"))
    replicas = values.get("guacamoleClient", {}).get("replicas")
    assert replicas == 1, (
        f"{values_file} must pin guacamoleClient.replicas to 1 so the token/task affinity "
        f"fix stays consistent across environments (#928); found {replicas!r}"
    )
