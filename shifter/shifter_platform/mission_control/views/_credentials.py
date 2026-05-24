"""Credential management views (HTML pages + JSON API)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from cms.services import (
    create_credential as cms_create_credential,
)
from cms.services import (
    delete_credential as cms_delete_credential,
)
from cms.services import (
    get_credential as cms_get_credential,
)
from cms.services import (
    list_credentials as cms_list_credentials,
)
from shared.exceptions import CMSError

from ._common import _get_user, _render_via_pkg

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas import CredentialRef, DeploymentProfileSpec, SCMCredentialSpec

    CredentialSpec = SCMCredentialSpec | DeploymentProfileSpec

logger = logging.getLogger(__name__)


class _CredentialError(Exception):
    """Internal exception carrying a JsonResponse for early-return guards."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


@login_required
@require_GET
def credentials_list(request: HttpRequest) -> HttpResponse:
    """List user's credentials."""
    credentials = cms_list_credentials(_get_user(request))

    scm_count = sum(1 for c in credentials if c.credential_type == "scm")
    profile_count = sum(1 for c in credentials if c.credential_type == "deployment_profile")

    context = {
        "page_title": "Credentials",
        "active_nav": "credentials",
        "credentials": credentials,
        "scm_count": scm_count,
        "profile_count": profile_count,
    }
    return _render_via_pkg(request, "mission_control/credentials/list.html", context)


@login_required
@require_GET
def credential_detail(request: HttpRequest, credential_id: int) -> HttpResponse:
    """View credential details."""
    try:
        credential = cms_get_credential(_get_user(request), credential_id)
    except CMSError:
        raise Http404("Credential not found") from None

    context = {
        "page_title": credential.name,
        "active_nav": "credentials",
        "credential": credential,
    }
    return _render_via_pkg(request, "mission_control/credentials/detail.html", context)


@login_required
@require_GET
def credential_add(request: HttpRequest) -> HttpResponse:
    """Add credential form (unified page with type selector)."""
    context = {
        "page_title": "Add Credential",
        "active_nav": "credentials",
    }
    return _render_via_pkg(request, "mission_control/credentials/add.html", context)


def _validate_credential_spec(data: dict[str, Any], credential_type_slug: str) -> CredentialSpec:
    """Validate the create-credential payload via the matching Pydantic spec."""
    from pydantic import ValidationError as PydanticValidationError

    from shared.schemas import DeploymentProfileSpec, SCMCredentialSpec

    spec_class = SCMCredentialSpec if credential_type_slug == "scm" else DeploymentProfileSpec
    try:
        return spec_class.model_validate(data)
    except PydanticValidationError as e:
        errors = e.errors()
        raise _CredentialError(
            JsonResponse(
                {"error": errors[0]["msg"] if errors else "Validation failed"},
                status=400,
            )
        ) from e


def _persist_credential(user: User, credential_type_slug: str, kwargs: dict[str, Any]) -> CredentialRef:
    """Create the credential record, mapping service errors to ``_CredentialError``."""
    try:
        return cms_create_credential(user, credential_type_slug, **kwargs)
    except (CMSError, ValueError) as e:
        raise _CredentialError(JsonResponse({"error": str(e)}, status=400)) from e
    except ValidationError as e:
        msg = e.message_dict.get("__all__", [str(e)])[0] if hasattr(e, "message_dict") else str(e)
        if "unique_active_credential_name_per_user" in msg:
            msg = "A credential with this name already exists"
        raise _CredentialError(JsonResponse({"error": msg}, status=400)) from e


@login_required
@require_POST
def api_credential_create(request: HttpRequest) -> JsonResponse:
    """Create a new credential.

    Accepts JSON with credential_type ('scm' or 'deployment_profile') and
    type-specific fields. Validates via Pydantic specs, creates via service.
    """
    user = _get_user(request)
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            raise _CredentialError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e

        credential_type_slug = data.get("credential_type")
        if credential_type_slug not in ("scm", "deployment_profile"):
            raise _CredentialError(
                JsonResponse(
                    {"error": f"Invalid credential type: {credential_type_slug}"},
                    status=400,
                )
            )

        data["user_id"] = user.id
        spec = _validate_credential_spec(data, credential_type_slug)
        kwargs = spec.model_dump(exclude={"user_id"})
        cred_ref = _persist_credential(user, credential_type_slug, kwargs)
    except _CredentialError as err:
        return err.response

    logger.info(
        "Credential created: user=%s credential_id=%s type=%s",
        user.email,
        cred_ref.credential_id,
        credential_type_slug,
    )
    return JsonResponse(
        {
            "id": cred_ref.credential_id,
            "name": spec.name,
            "credential_type": credential_type_slug,
        },
        status=201,
    )


@login_required
@require_POST
def api_credential_delete(request: HttpRequest, credential_id: int) -> JsonResponse:
    """Soft-delete a credential."""
    user = _get_user(request)
    try:
        cms_delete_credential(user, credential_id)
    except CMSError:
        raise Http404("Credential not found") from None

    logger.info(
        "Credential deleted: user=%s credential_id=%s",
        user.email,
        credential_id,
    )
    return JsonResponse({"success": True})
