"""The portal must reach Guacamole's in-cluster token API under default deny."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
NETWORK_POLICIES = REPO_ROOT / "platform" / "k8s" / "gcp" / "base" / "networkpolicies.yaml"


def _policy(name: str) -> dict:
    policies = yaml.safe_load_all(NETWORK_POLICIES.read_text(encoding="utf-8"))
    return next(policy for policy in policies if policy.get("metadata", {}).get("name") == name)


def test_portal_can_reach_guacamole_token_api_under_default_deny() -> None:
    """Both halves of the pod-to-pod path must allow only portal to client:8080."""
    ingress = _policy("allow-portal-to-guacamole-client")["spec"]
    assert ingress == {
        "podSelector": {"matchLabels": {"app.kubernetes.io/component": "guacamole-client"}},
        "policyTypes": ["Ingress"],
        "ingress": [
            {
                "from": [{"podSelector": {"matchLabels": {"app.kubernetes.io/component": "portal"}}}],
                "ports": [{"protocol": "TCP", "port": 8080}],
            }
        ],
    }

    egress = _policy("allow-portal-egress-to-guacamole-client")["spec"]
    assert egress == {
        "podSelector": {"matchLabels": {"app.kubernetes.io/component": "portal"}},
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/component": "guacamole-client"}}}],
                "ports": [{"protocol": "TCP", "port": 8080}],
            }
        ],
    }
