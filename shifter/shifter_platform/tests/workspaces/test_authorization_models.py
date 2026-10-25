"""Persistence invariants for scoped authorization display metadata."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from workspaces.models import AuthorizationGroup, AuthorizationPolicy

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("model", [AuthorizationGroup, AuthorizationPolicy])
@pytest.mark.parametrize(
    "scope",
    [
        {"scope_kind": "installation"},
        {"scope_kind": "account", "account_uuid": uuid4()},
        {"scope_kind": "account", "account_uuid": uuid4(), "organization_uuid": uuid4()},
        {
            "scope_kind": "account",
            "account_uuid": uuid4(),
            "organization_uuid": uuid4(),
            "workspace_uuid": uuid4(),
        },
    ],
    ids=("installation", "account", "organization", "workspace"),
)
def test_name_is_unique_within_every_valid_scope_shape(model, scope) -> None:
    model.objects.create(**scope, name="Operators")

    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(**scope, name="Operators")


@pytest.mark.parametrize("model", [AuthorizationGroup, AuthorizationPolicy])
def test_same_name_is_available_in_distinct_scopes(model) -> None:
    model.objects.create(scope_kind="account", account_uuid=uuid4(), name="Operators")
    model.objects.create(scope_kind="account", account_uuid=uuid4(), name="Operators")

    assert model.objects.filter(name="Operators").count() == 2
