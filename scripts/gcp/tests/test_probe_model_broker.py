"""Onboarding cannot credit unknown or unexpectedly allowed effective IAM."""

import importlib.util
from pathlib import Path

import pytest


def load_module():
    path = Path(__file__).resolve().parents[1] / "probe_model_broker.py"
    spec = importlib.util.spec_from_file_location("probe_model_broker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("observed", ["CAN_ACCESS", "UNKNOWN_INFO_DENIED", "UNKNOWN_CONDITIONAL"])
def test_negative_permission_probe_fails_closed(observed):
    module = load_module()
    with pytest.raises(ValueError):
        module.assert_permission_state({"overallAccessState": observed}, allowed=False)


def test_positive_and_negative_controls_are_distinct():
    module = load_module()
    module.assert_permission_state({"overallAccessState": "CAN_ACCESS"}, allowed=True)
    module.assert_permission_state({"overallAccessState": "CANNOT_ACCESS"}, allowed=False)
    with pytest.raises(ValueError):
        module.assert_permission_state({"overallAccessState": "CANNOT_ACCESS"}, allowed=True)


@pytest.mark.parametrize("failure", [None, "ownership", "billing", "api", "disabled", "keys", "inherited"])
def test_onboarding_checks_actual_readbacks_and_inherited_permissions(monkeypatch, failure):
    from types import SimpleNamespace

    module = load_module()
    calls = []

    def readback(*args):
        calls.append(args)
        if args[:2] == ("projects", "describe"):
            return {"labels": {"shifter-deployment": "foreign" if failure == "ownership" else "test-deploy"}}
        if args[:3] == ("billing", "projects", "describe"):
            return {"billingEnabled": failure != "billing"}
        if args[:2] == ("services", "list"):
            return [
                {"config": {"name": api}}
                for api in (
                    ["aiplatform.googleapis.com"]
                    if failure == "api"
                    else ["aiplatform.googleapis.com", "iamcredentials.googleapis.com"]
                )
            ]
        if args[:3] == ("iam", "service-accounts", "describe"):
            return {"disabled": failure == "disabled"}
        if args[:4] == ("iam", "service-accounts", "keys", "list"):
            return [{"keyType": "USER_MANAGED"}] if failure == "keys" else []
        if args[:3] == ("policy-intelligence", "troubleshoot-policy", "iam"):
            permission = args[args.index("--permission") + 1]
            positive = permission in {"iam.serviceAccounts.getAccessToken", "aiplatform.endpoints.predict"}
            unexpected = failure == "inherited" and permission == "iam.serviceAccountKeys.create"
            return {"overallAccessState": "CAN_ACCESS" if positive or unexpected else "CANNOT_ACCESS"}
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(module, "_gcloud", readback)
    settings = SimpleNamespace(model_projects={"models-example": "model-invoke"})
    kwargs = {"broker_gsa": "model-broker@platform-example.iam.gserviceaccount.com", "deployment": "test-deploy"}
    if failure:
        with pytest.raises(ValueError):
            module.probe_projects(settings, **kwargs)
    else:
        result = module.probe_projects(settings, **kwargs)
        assert result == [
            {
                "project": "models-example",
                "identity": "model-invoke@models-example.iam.gserviceaccount.com",
                "onboarding": "passed",
            }
        ]
        permission_calls = [args for args in calls if args[0] == "policy-intelligence"]
        assert len(permission_calls) == 10
        token = next(args for args in permission_calls if args[-1] == "iam.serviceAccounts.getAccessToken")
        assert (
            token[3] == "//iam.googleapis.com/projects/models-example/serviceAccounts/"
            "model-invoke@models-example.iam.gserviceaccount.com"
        )
        assert token[token.index("--principal-email") + 1] == kwargs["broker_gsa"]
