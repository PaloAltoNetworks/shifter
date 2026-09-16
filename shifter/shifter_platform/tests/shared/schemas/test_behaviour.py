"""Behaviour schema projection contracts."""

from pydantic import TypeAdapter

from shared.schemas.behaviour import AttackBehaviourContext, BehaviourContext


def test_single_behaviour_context_builds_a_type_adapter_and_validates():
    adapter = TypeAdapter(BehaviourContext)

    context = adapter.validate_python({"behaviour_id": 7, "name": "Initial foothold", "behaviour_type": "attack"})

    assert isinstance(context, AttackBehaviourContext)
    assert context.behaviour_id == 7
