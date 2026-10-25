"""Explicit S2 route coverage; legacy application cutover belongs to S8."""

from shared.authorization import action_definition
from workspaces.api.urls import urlpatterns

# Every introduced surface names its action or its authenticated-only exemption.
# Mutation services additionally authorize the submitted effect's own actions.
SURFACES = {
    ("authorization-catalog", "get"): None,
    ("authorization-predefined-catalog", "get"): None,
    ("authorization-groups", "get"): "workspace.manage_authorization",
    ("authorization-groups", "post"): "workspace.manage_authorization",
    ("authorization-policies", "get"): "workspace.manage_authorization",
    ("authorization-policies", "post"): "workspace.manage_authorization",
    ("authorization-group-memberships", "post"): "workspace.manage_authorization",
    ("authorization-policy-assignments", "post"): "workspace.manage_authorization",
    ("authorization-policy-actions", "post"): "workspace.manage_authorization",
    ("authorization-direct-assignments", "post"): "workspace.manage_authorization",
    ("authorization-predefined-assignments", "post"): "workspace.manage_authorization",
    ("authorization-operation", "get"): "workspace.manage_authorization",
    ("authorization-operation", "post"): "workspace.manage_authorization",
}


def test_every_authorization_route_and_method_has_explicit_catalog_coverage() -> None:
    actual = {
        (route.name, method)
        for route in urlpatterns
        if "authorization/" in str(route.pattern)
        for method in ("get", "post", "put", "patch", "delete")
        if callable(getattr(route.callback.cls, method, None))
    }
    assert actual == set(SURFACES), "Authorization route coverage drift: classify every new surface explicitly"
    for action in SURFACES.values():
        if action is not None:
            assert action_definition(action).target_type == "workspace"
