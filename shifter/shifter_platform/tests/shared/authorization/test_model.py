from shared.authorization import ACTION_CATALOG, APPLICATION_ADMINISTRATOR_ACTIONS
from shared.authorization.model import (
    MODEL_DSL,
    MODEL_SDK_VERSION,
    MODEL_SERVER_VERSION,
    decision_relation_for_action,
    grant_relation_for_action,
    validate_model_coverage,
)


def test_model_and_sdk_versions_are_pinned() -> None:
    assert MODEL_SERVER_VERSION == "1.20.0"
    assert MODEL_SDK_VERSION == "0.10.4"


def test_model_uses_concrete_resource_types_and_native_usersets() -> None:
    for object_type in ("installation", "account", "organization", "workspace", "event", "range"):
        assert f"type {object_type}\n" in MODEL_DSL
    assert "type resource\n" not in MODEL_DSL
    assert "group#member" in MODEL_DSL
    assert "role#assignee" in MODEL_DSL
    assert "type authorization_binding" in MODEL_DSL
    assert "define active: candidate but not superseded" in MODEL_DSL


def test_every_action_has_explicit_grant_and_decision_relations() -> None:
    validate_model_coverage()

    for action in ACTION_CATALOG:
        assert f"define {grant_relation_for_action(action.code)}:" in MODEL_DSL
        assert f"define {decision_relation_for_action(action.code)}:" in MODEL_DSL


def test_administrator_reachability_matches_only_administrative_catalog_actions() -> None:
    for action in ACTION_CATALOG:
        relation = decision_relation_for_action(action.code)
        line = next(item for item in MODEL_DSL.splitlines() if f"define {relation}:" in item)
        if action.administrative:
            assert "administrator" in line
        else:
            assert "administrator" not in line


def test_installation_operator_covers_every_administrative_action_without_wildcard() -> None:
    assert "define direct_operator: [principal, group#member, role#assignee, authorization_binding#active]" in MODEL_DSL
    assert "define operator: direct_operator but not deny_operator" in MODEL_DSL
    assert "define administrator: direct_administrator but not deny_administrator" in MODEL_DSL
    assert "*" not in MODEL_DSL
    assert APPLICATION_ADMINISTRATOR_ACTIONS
