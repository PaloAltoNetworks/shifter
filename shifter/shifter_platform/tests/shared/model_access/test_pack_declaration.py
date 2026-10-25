import pytest
from pydantic import ValidationError

from shared.model_access import PackModelNeedsDeclaration


def _payload():
    return {
        "contract_version": "model-access-pack/v1",
        "needs": {
            "participant": {
                "workload_role": "participant",
                "profile_id": "coding",
                "required": True,
                "required_capabilities": ["messages"],
                "allowed_capabilities": ["messages"],
                "allowed_strategies": ["fixed-v1"],
                "data_regions": ["us-central1"],
                "limits": {
                    "max_request_seconds": 120,
                    "max_request_bytes": 1_000_000,
                    "max_input_tokens": 8_000,
                    "max_output_tokens": 2_000,
                    "max_requests_per_window": 60,
                    "request_window_seconds": 60,
                    "max_spend_micro_units": 5_000_000,
                    "currency": "USD",
                    "max_concurrent_requests": 2,
                },
            }
        },
    }


def test_pack_model_need_binds_only_to_the_verified_digest():
    declaration = PackModelNeedsDeclaration.model_validate(_payload())
    digest = "sha256:" + "a" * 64
    bound = declaration.bind_to_digest(digest)
    assert bound["participant"]["scenario_digest"] == digest
    assert bound["participant"]["contract_version"] == "model-access-scenario/v1"


@pytest.mark.parametrize("mutation", ["extra", "role", "capability"])
def test_pack_model_need_is_closed_and_consistent(mutation):
    payload = _payload()
    need = payload["needs"]["participant"]
    if mutation == "extra":
        need["provider"] = "gcp"
    elif mutation == "role":
        need["workload_role"] = "other"
    else:
        need["required_capabilities"] = ["tools"]
    with pytest.raises(ValidationError):
        PackModelNeedsDeclaration.model_validate(payload)
