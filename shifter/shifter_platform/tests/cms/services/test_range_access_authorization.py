"""Range-instance access authorization resolves realized engine instances.

Regression cover for the interactive-access gate in
``cms.services._range_access``. The gate previously resolved ownership from
``cms.models.Instance``, but realized range instances are rows of
``engine.models.Instance`` -- the CMS table is written only by NGFW
provisioning. Every terminal/RDP/SSH open therefore failed with
"Instance not found" before the workspace check was ever reached, on every
provisioned range. Nothing covered the gate against a realized instance, so
the regression shipped silently; these tests pin that seam.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model

from cms.services._range_access import _authorize_instance_access


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="range-owner", password="pw-not-used")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="range-stranger", password="pw-not-used")


def _realized_instance(user, *, workspace_id=99):
    """Create an engine Instance owned by ``user``, as provisioning does."""
    from cms.models import Request as CmsRequest
    from engine.models import Instance, Request

    request_ref = uuid.uuid4()
    request = Request.objects.create(request_id=request_ref, request_type="range", user=user)
    # The workspace binding lives on the CMS request row, correlated by the
    # shared ``request_id`` UUID rather than by primary key: engine and CMS
    # keep separate request tables.
    CmsRequest.objects.create(request_id=request_ref, request_type="range", user=user, workspace_id=workspace_id)
    instance = Instance.objects.create(
        uuid=str(uuid.uuid4()),
        request=request,
        role="attacker",
        os_type="kali",
        status="ready",
    )
    return instance


@pytest.mark.django_db
def test_authorizes_a_realized_engine_instance(owner, monkeypatch):
    """The owner of a realized range instance passes the access gate.

    This is the case the CMS-table lookup could never satisfy: provisioning
    writes ``engine.models.Instance``, never ``cms.models.Instance``.
    """
    instance = _realized_instance(owner)
    monkeypatch.setattr(
        "cms.services._range_access.authorize_range_workspace",
        lambda *args, **kwargs: None,
    )

    _authorize_instance_access(owner, instance.uuid)


@pytest.mark.django_db
def test_rejects_an_instance_owned_by_another_user(owner, other_user, monkeypatch):
    """Ownership is still enforced -- the gate is not merely an existence check."""
    instance = _realized_instance(owner)
    monkeypatch.setattr(
        "cms.services._range_access.authorize_range_workspace",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ValueError, match="Instance not found"):
        _authorize_instance_access(other_user, instance.uuid)


@pytest.mark.django_db
def test_rejects_an_unknown_instance(owner):
    with pytest.raises(ValueError, match="Instance not found"):
        _authorize_instance_access(owner, str(uuid.uuid4()))


@pytest.mark.django_db
def test_passes_the_requests_workspace_binding_to_the_workspace_gate(owner, monkeypatch):
    """The workspace id checked is the one recorded on the request row."""
    instance = _realized_instance(owner, workspace_id=4242)
    seen: dict[str, object] = {}

    def _capture(user, workspace_id, operation):
        seen["user"] = user
        seen["workspace_id"] = workspace_id
        seen["operation"] = operation

    monkeypatch.setattr("cms.services._range_access.authorize_range_workspace", _capture)

    _authorize_instance_access(owner, instance.uuid)

    assert seen["workspace_id"] == 4242
    assert seen["user"] == owner


@pytest.mark.django_db
def test_workspace_denial_is_a_permission_error(owner, monkeypatch):
    """A refused workspace surfaces as PermissionError, not "not found"."""
    from cms.exceptions import CMSError

    instance = _realized_instance(owner)

    def _deny(*args, **kwargs):
        raise CMSError("denied")

    monkeypatch.setattr("cms.services._range_access.authorize_range_workspace", _deny)

    with pytest.raises(PermissionError):
        _authorize_instance_access(owner, instance.uuid)
