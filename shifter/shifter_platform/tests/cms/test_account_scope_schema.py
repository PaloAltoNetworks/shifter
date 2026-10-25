"""Transitional CMS scope persistence keeps legacy IDs and admits direct accounts."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from cms.models import Request

pytestmark = pytest.mark.django_db


def _request(**scope):
    user = get_user_model().objects.create_user(username=f"scope-{uuid4()}")
    return Request.objects.create(request_id=uuid4(), request_type="range", user=user, **scope)


def test_direct_account_scope_requires_explicit_kind_and_account_identity():
    request = _request(scope_kind="account", account_id=42, workspace_id=None)
    assert request.account_id == 42
    assert request.workspace_id is None
    with pytest.raises(IntegrityError), transaction.atomic():
        _request(scope_kind="account", workspace_id=None)


def test_missing_scope_never_becomes_installation_scope():
    with pytest.raises(IntegrityError), transaction.atomic():
        _request(workspace_id=None)
    legacy = _request(workspace_id=71)
    assert legacy.scope_kind == ""
    assert legacy.workspace_id == 71


def test_explicit_installation_scope_rejects_customer_ids():
    installation = _request(scope_kind="installation", workspace_id=None)
    assert installation.account_id is None
    with pytest.raises(IntegrityError), transaction.atomic():
        _request(scope_kind="installation", account_id=42, workspace_id=None)


def test_workspace_scope_requires_organization_when_account_is_explicit():
    with pytest.raises(IntegrityError), transaction.atomic():
        _request(scope_kind="account", account_id=42, workspace_id=71)
    nested = _request(scope_kind="account", account_id=42, organization_id=5, workspace_id=71)
    assert nested.organization_id == 5
