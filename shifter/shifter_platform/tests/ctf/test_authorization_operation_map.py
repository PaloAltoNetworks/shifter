"""Every published CTF operation has an explicit S5 authorization contract."""

import json
from pathlib import Path

from ctf.api.operation_policy import (
    API_OPERATION_POLICY,
    CTF_COMMAND_POLICY,
    CTF_DJANGO_ADMIN_POLICY,
    CTF_SCHEDULED_EFFECT_POLICY,
    NON_API_ROUTE_POLICY,
)
from shared.authorization import action_definition


def test_every_published_ctf_operation_has_one_registered_action_or_exemption() -> None:
    schema = json.loads((Path(__file__).resolve().parents[2] / "openapi" / "v1.json").read_text())
    published = {
        operation["operationId"]
        for path, methods in schema["paths"].items()
        if path.startswith("/api/v1/ctf/")
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert len(published) >= 114
    assert set(API_OPERATION_POLICY) == published
    for binding in API_OPERATION_POLICY.values():
        assert binding.actions or binding.exemption
        if binding.actions and binding.exemption:
            assert binding.selector == "publication_or_participation"
        if binding.actions:
            assert binding.target in {"event", "parent", "range"}
            assert binding.locator
            assert len(binding.actions) == 1 or binding.selector in {
                "validated_parent_placement",
                "file_audience",
            }
            for action in binding.actions:
                definition = action_definition(action)
                assert definition.target_type == binding.target or binding.target == "parent"
        if binding.exemption:
            assert binding.exemption in {"scoreboard_publication", "cms_model_access"}
    scoreboard = API_OPERATION_POLICY["ctf_events_scoreboard_retrieve"]
    assert scoreboard.actions == ("event.participate",)
    assert scoreboard.exemption == "scoreboard_publication"


def test_ctf_browser_routes_and_commands_have_explicit_effect_classification() -> None:
    from ctf.urls import urlpatterns

    names = {route.name for route in urlpatterns if route.name}
    command_dir = Path(__file__).resolve().parents[2] / "ctf" / "management" / "commands"
    commands = {path.stem for path in command_dir.glob("*.py") if path.stem != "__init__"}
    assert set(NON_API_ROUTE_POLICY) == names
    assert set(CTF_COMMAND_POLICY) == commands
    assert all(
        value in {"public_registration", "login", "temporary_login", "spa_shell"}
        for value in NON_API_ROUTE_POLICY.values()
    )
    assert all(value in {"system_event", "system_maintenance"} for value in CTF_COMMAND_POLICY.values())


def test_scheduled_effects_are_classified_at_the_dispatch_boundary() -> None:
    from ctf.enums import ScheduledTaskType
    from ctf.management.commands.run_ctf_scheduler import TASK_HANDLERS

    task_types = {item.value for item in ScheduledTaskType}
    assert set(CTF_SCHEDULED_EFFECT_POLICY) == task_types == set(TASK_HANDLERS)
    assert CTF_SCHEDULED_EFFECT_POLICY["release_communication"] == "reauthorize_initiator"
    assert CTF_SCHEDULED_EFFECT_POLICY["send_notification"] == "retired"
    assert set(CTF_SCHEDULED_EFFECT_POLICY.values()) == {
        "system_event_lifecycle",
        "reauthorize_initiator",
        "retired",
    }


def test_django_admin_models_and_inlines_have_event_effect_bindings() -> None:
    from django.contrib import admin

    from ctf.admin import CTFEventAdmin  # noqa: F401 - register admin classes

    registered = {
        model.__name__: model_admin
        for model, model_admin in admin.site._registry.items()
        if model._meta.app_label == "ctf"
    }
    assert set(CTF_DJANGO_ADMIN_POLICY) == set(registered)
    for model_name, binding in CTF_DJANGO_ADMIN_POLICY.items():
        assert binding.actions
        assert binding.locator
        for action in binding.actions:
            assert action_definition(action).target_type == "event" or (
                model_name == "CTFEvent" and action.endswith(".create_event")
            )
        for inline in registered[model_name].inlines:
            assert inline.model.__name__ in CTF_DJANGO_ADMIN_POLICY
