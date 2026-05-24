"""Tests for cms.services._ngfws (list/get/create/destroy NGFW)."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def mock_user():
    """Authenticated user with id."""
    user = MagicMock()
    user.id = 42
    user.pk = 42
    user.email = "u@example.com"
    return user


def _make_credential(slug):
    """Build a credential mock with credential_type.slug == slug."""
    cred = MagicMock()
    cred.id = 7
    cred.pk = 7
    ct = MagicMock()
    ct.slug = slug
    cred.credential_type = ct
    return cred


def _make_app(*, app_id=None, name="NGFW", status="ready", serial="X-1"):
    """Build a CMS App mock for NGFW projections."""
    app = MagicMock()
    app.id = app_id or uuid4()
    app.name = name
    app.status = status
    app.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    app.data = {"serial_number": serial}
    inst = MagicMock()
    inst.id = uuid4()
    app.instance = inst
    req = MagicMock()
    req.request_id = uuid4()
    inst.request = req
    return app


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidateNgfwUser:
    """Internal helper that protects every public NGFW entrypoint."""

    def test_raises_typeerror_for_none(self):
        from cms.services._ngfws import _validate_ngfw_user

        with pytest.raises(TypeError):
            _validate_ngfw_user(None)

    def test_raises_valueerror_for_unsaved_user(self):
        from cms.services._ngfws import _validate_ngfw_user

        unsaved = MagicMock()
        unsaved.id = None
        with pytest.raises(ValueError):
            _validate_ngfw_user(unsaved)


class TestValidateNgfwName:
    def test_strips_and_returns(self):
        from cms.services._ngfws import _validate_ngfw_name

        assert _validate_ngfw_name("  Box  ") == "Box"

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_raises_for_empty(self, bad):
        from cms.services._ngfws import _validate_ngfw_name

        with pytest.raises(ValueError):
            _validate_ngfw_name(bad)


class TestValidateAppId:
    def test_accepts_uuid(self):
        from cms.services._ngfws import _validate_app_id

        u = uuid4()
        assert _validate_app_id(u) == u

    def test_parses_uuid_string(self):
        from cms.services._ngfws import _validate_app_id

        u = uuid4()
        assert _validate_app_id(str(u)) == u

    def test_raises_typeerror_for_none(self):
        from cms.services._ngfws import _validate_app_id

        with pytest.raises(TypeError):
            _validate_app_id(None)

    def test_raises_typeerror_for_int(self):
        from cms.services._ngfws import _validate_app_id

        with pytest.raises(TypeError):
            _validate_app_id(123)

    def test_raises_valueerror_for_bad_uuid_string(self):
        from cms.services._ngfws import _validate_app_id

        with pytest.raises(ValueError):
            _validate_app_id("not-a-uuid")


class TestResolveDeploymentProfile:
    def test_requires_id(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_deployment_profile

        with pytest.raises(ValueError):
            _resolve_ngfw_deployment_profile(mock_user, 0, MagicMock())

    def test_returns_when_slug_matches(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_deployment_profile

        cred = _make_credential("deployment_profile")
        model = MagicMock()
        model.objects.select_related.return_value.get.return_value = cred
        result = _resolve_ngfw_deployment_profile(mock_user, 7, model)
        assert result is cred

    def test_raises_cms_error_when_not_found(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services._ngfws import _resolve_ngfw_deployment_profile

        model = MagicMock()
        model.DoesNotExist = type("DNE", (Exception,), {})
        model.objects.select_related.return_value.get.side_effect = model.DoesNotExist
        with pytest.raises(CMSError, match="Deployment profile not found"):
            _resolve_ngfw_deployment_profile(mock_user, 7, model)

    def test_raises_cms_error_when_wrong_type(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services._ngfws import _resolve_ngfw_deployment_profile

        cred = _make_credential("scm")
        model = MagicMock()
        model.objects.select_related.return_value.get.return_value = cred
        with pytest.raises(CMSError, match="must reference a deployment profile"):
            _resolve_ngfw_deployment_profile(mock_user, 7, model)


class TestResolveNgfwRegistration:
    def test_invalid_method(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_registration

        with pytest.raises(ValueError, match="registration_method"):
            _resolve_ngfw_registration(mock_user, "bogus", None, None, None, MagicMock())

    def test_otp_requires_value_and_folder(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_registration

        with pytest.raises(ValueError, match="otp"):
            _resolve_ngfw_registration(mock_user, "otp", None, None, None, MagicMock())

    def test_otp_returns_none(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_registration

        assert _resolve_ngfw_registration(mock_user, "otp", None, "OTP123", "folder/", MagicMock()) is None

    def test_pin_requires_scm_credential_id(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_registration

        with pytest.raises(ValueError, match="scm_credential_id"):
            _resolve_ngfw_registration(mock_user, "pin", None, None, None, MagicMock())

    def test_pin_returns_scm_credential(self, mock_user):
        from cms.services._ngfws import _resolve_ngfw_registration

        cred = _make_credential("scm")
        model = MagicMock()
        model.objects.select_related.return_value.get.return_value = cred
        result = _resolve_ngfw_registration(mock_user, "pin", 7, None, None, model)
        assert result is cred

    def test_pin_raises_when_credential_not_found(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services._ngfws import _resolve_ngfw_registration

        model = MagicMock()
        model.DoesNotExist = type("DNE", (Exception,), {})
        model.objects.select_related.return_value.get.side_effect = model.DoesNotExist
        with pytest.raises(CMSError, match="SCM credential not found"):
            _resolve_ngfw_registration(mock_user, "pin", 7, None, None, model)

    def test_pin_raises_when_wrong_type(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services._ngfws import _resolve_ngfw_registration

        cred = _make_credential("deployment_profile")
        model = MagicMock()
        model.objects.select_related.return_value.get.return_value = cred
        with pytest.raises(CMSError, match="must reference an SCM credential"):
            _resolve_ngfw_registration(mock_user, "pin", 7, None, None, model)


# ---------------------------------------------------------------------------
# Public list/get
# ---------------------------------------------------------------------------


class TestListNgfws:
    def test_returns_projection_list(self, mock_user):
        from cms.services import list_ngfws

        apps = [_make_app(name="A"), _make_app(name="B")]
        qs = MagicMock()
        qs.select_related.return_value.order_by.return_value = apps
        with patch("cms.models.App.objects.filter", return_value=qs):
            result = list_ngfws(mock_user)

        assert len(result) == 2
        assert {r.name for r in result} == {"A", "B"}

    def test_validates_user(self):
        from cms.services import list_ngfws

        with pytest.raises(TypeError):
            list_ngfws(None)


class TestGetNgfw:
    def test_returns_projection(self, mock_user):
        from cms.services import get_ngfw

        app = _make_app(name="N1")
        with patch(
            "cms.models.App.objects.select_related",
        ) as mock_sr:
            mock_sr.return_value.get.return_value = app
            result = get_ngfw(mock_user, app.id)
        assert result.name == "N1"
        assert result.app_id == app.id

    def test_raises_cms_error_when_missing(self, mock_user):
        from cms.exceptions import CMSError
        from cms.models import App
        from cms.services import get_ngfw

        with patch("cms.models.App.objects.select_related") as mock_sr:
            mock_sr.return_value.get.side_effect = App.DoesNotExist
            with pytest.raises(CMSError, match="NGFW not found"):
                get_ngfw(mock_user, uuid4())


# ---------------------------------------------------------------------------
# create_ngfw end-to-end (mocked DB / engine)
# ---------------------------------------------------------------------------


@pytest.fixture
def create_ngfw_ctx(mock_user):
    """Patch every external call create_ngfw makes; yield the mock handles."""
    deployment = _make_credential("deployment_profile")
    scm = _make_credential("scm")

    instance = MagicMock()
    instance.id = uuid4()
    app = MagicMock()
    app.id = uuid4()
    request_obj = MagicMock()
    request_obj.request_id = uuid4()

    cred_model = MagicMock()
    cred_model.DoesNotExist = type("DNE", (Exception,), {})

    def cred_get(*, id, user):
        return deployment if id == 5 else scm

    cred_model.objects.select_related.return_value.get.side_effect = cred_get

    from shared.schemas import InstanceSpec

    ngfw_spec = InstanceSpec(
        name="ngfw-vm",
        uuid=str(uuid4()),
        role="ngfw",
        os_type="panos",
    )

    with ExitStack() as stack:
        # Reject existing -> none
        stack.enter_context(
            patch(
                "cms.models.App.objects.filter",
                return_value=MagicMock(exclude=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),
            )
        )
        # Credential class import inside create_ngfw
        stack.enter_context(patch("cms.services._ngfws.cast", lambda _t, v: v))
        m_cred = stack.enter_context(patch("cms.models.Credential", cred_model))
        m_req_create = stack.enter_context(patch("cms.models.Request.objects.create", return_value=request_obj))
        m_inst_type_get = stack.enter_context(patch("cms.models.InstanceType.objects.get", return_value=MagicMock()))
        m_app_type_get = stack.enter_context(patch("cms.models.AppType.objects.get", return_value=MagicMock()))
        m_inst_create = stack.enter_context(patch("cms.models.Instance.objects.create", return_value=instance))
        m_app_create = stack.enter_context(patch("cms.models.App.objects.create", return_value=app))
        m_hydrate = stack.enter_context(patch("cms.scenarios.hydrator.hydrate_ngfw", return_value=ngfw_spec))
        m_engine = stack.enter_context(patch("engine.services.create_ngfw"))
        m_audit = stack.enter_context(patch("cms.services.audit_log"))
        yield {
            "deployment": deployment,
            "scm": scm,
            "instance": instance,
            "app": app,
            "request": request_obj,
            "hydrate": m_hydrate,
            "engine": m_engine,
            "audit": m_audit,
            "cred_model": m_cred,
            "req_create": m_req_create,
            "inst_create": m_inst_create,
            "app_create": m_app_create,
            "inst_type_get": m_inst_type_get,
            "app_type_get": m_app_type_get,
        }


class TestCreateNgfw:
    def test_returns_ref_on_success(self, mock_user, create_ngfw_ctx):
        from cms.services import create_ngfw
        from shared.schemas.app import NGFWAppRef

        ref = create_ngfw(
            user=mock_user,
            name="MyNGFW",
            deployment_profile_id=5,
            registration_method="pin",
            scm_credential_id=6,
        )
        assert isinstance(ref, NGFWAppRef)
        assert ref.app_id == create_ngfw_ctx["app"].id
        assert ref.is_deleted is False
        create_ngfw_ctx["engine"].assert_called_once()
        create_ngfw_ctx["audit"].assert_called_once()

    def test_rejects_when_existing_active(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import create_ngfw

        existing = MagicMock(id=uuid4())
        with (
            patch(
                "cms.models.App.objects.filter",
                return_value=MagicMock(
                    exclude=MagicMock(return_value=MagicMock(first=MagicMock(return_value=existing)))
                ),
            ),
            pytest.raises(CMSError, match="already have an active NGFW"),
        ):
            create_ngfw(
                user=mock_user,
                name="X",
                deployment_profile_id=5,
                registration_method="otp",
                otp_value="V",
                otp_folder="F",
            )

    def test_validates_user(self):
        from cms.services import create_ngfw

        with pytest.raises(TypeError):
            create_ngfw(user=None, name="X", deployment_profile_id=1, registration_method="pin")


# ---------------------------------------------------------------------------
# destroy_ngfw
# ---------------------------------------------------------------------------


@pytest.fixture
def destroy_ngfw_app(mock_user):
    """A CMS App mock matching the destroy_ngfw query."""
    app = _make_app(name="ToKill")
    app.save = MagicMock()
    app.instance.save = MagicMock()
    return app


class TestDestroyNgfw:
    def test_happy_path_sets_destroying_and_audits(self, mock_user, destroy_ngfw_app):
        from cms.services import destroy_ngfw
        from shared.schemas.app import NGFWAppRef

        with (
            patch("cms.models.App.objects.select_related") as mock_sr,
            patch("engine.services.destroy_ngfw") as mock_destroy,
            patch("cms.services.audit_log") as mock_audit,
        ):
            mock_sr.return_value.get.return_value = destroy_ngfw_app
            ref = destroy_ngfw(mock_user, destroy_ngfw_app.id, "ToKill")

        assert isinstance(ref, NGFWAppRef)
        assert ref.is_deleted is True
        mock_destroy.assert_called_once_with(destroy_ngfw_app.instance.request.request_id)
        mock_audit.assert_called_once()
        # status updated
        assert destroy_ngfw_app.status == "destroying"
        destroy_ngfw_app.save.assert_called_once()

    def test_raises_when_not_found(self, mock_user):
        from cms.exceptions import CMSError
        from cms.models import App
        from cms.services import destroy_ngfw

        with patch("cms.models.App.objects.select_related") as mock_sr:
            mock_sr.return_value.get.side_effect = App.DoesNotExist
            with pytest.raises(CMSError, match="NGFW not found"):
                destroy_ngfw(mock_user, uuid4(), "anything")

    def test_raises_on_name_mismatch(self, mock_user, destroy_ngfw_app):
        from cms.services import destroy_ngfw

        with patch("cms.models.App.objects.select_related") as mock_sr:
            mock_sr.return_value.get.return_value = destroy_ngfw_app
            with pytest.raises(ValueError, match="Name confirmation"):
                destroy_ngfw(mock_user, destroy_ngfw_app.id, "wrong")

    def test_propagates_engine_error_as_cms_error(self, mock_user, destroy_ngfw_app):
        import engine.services as eng
        from cms.exceptions import CMSError
        from cms.services import destroy_ngfw

        with (
            patch("cms.models.App.objects.select_related") as mock_sr,
            patch("engine.services.destroy_ngfw", side_effect=eng.EngineError("boom")),
        ):
            mock_sr.return_value.get.return_value = destroy_ngfw_app
            with pytest.raises(CMSError, match="boom"):
                destroy_ngfw(mock_user, destroy_ngfw_app.id, "ToKill")
