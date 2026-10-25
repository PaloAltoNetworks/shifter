"""Retry-safe launch behavior for ``LaunchRangeView`` (#2086, ADR-063).

Split out of ``mission_control.api.ranges`` (Sonar S104) so the view module stays
within its size budget. ``RetrySafeLaunchMixin`` implements the Idempotency-Key
path: recover-before-catalog-validation, first-use dispatch+bind, and projecting
the *bound* range on the response. It composes onto ``MissionControlAPIView`` via
``LaunchRangeView`` and calls back into that view's ``_launch_range`` /
``_launch_failure_response`` and the base ``bad_request`` / ``error_response``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.contrib.auth.models import User
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import (
    RetryKeyConflict,
    RetrySafeLaunchOutcome,
    bind_first_use_launch,
    get_range_by_request_id,
    resolve_retry_recovery,
)
from mission_control.api._base import _raw_request
from mission_control.views._common import _audit_range_lifecycle
from shared.audit import AuditAction
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LaunchChoices:
    """Validated workspace, agent selection, and model-source launch intent."""

    workspace_uuid: str | UUID | None = None
    agents_selection: dict[str, Any] = field(default_factory=dict)
    model_sources: dict[str, Any] | None = None


class RetrySafeLaunchMixin:
    """Idempotency-Key launch handling for ``LaunchRangeView``."""

    # Caller-supplied idempotency key; bounded so it can never overflow the binding
    # column or become a log/label hazard.
    _RETRY_KEY_HEADER = "Idempotency-Key"
    _MAX_CALLER_KEY_LEN = 200

    if TYPE_CHECKING:
        # Provided by the composed ``LaunchRangeView`` (MissionControlAPIView base +
        # the view's own launch helpers); declared here only so the type checker
        # resolves the cross-object calls on this mixin.
        def bad_request(self, message: str) -> Response: ...

        def error_response(self, *, code: str, message: str, status_code: int) -> Response: ...

        def _launch_range(
            self, request: Request, user: User, data: dict[str, Any], caller_key: str | None = ...
        ) -> Response: ...

        def _launch_failure_response(self, exc: CMSError, user: User, scenario: str) -> Response: ...

    def _retry_key(self, request: Request) -> str | Response | None:
        """Return a bounded caller retry key, ``None`` when absent, or a 400 Response when invalid."""
        key = (request.headers.get(self._RETRY_KEY_HEADER) or "").strip()
        if not key:
            return None
        if len(key) > self._MAX_CALLER_KEY_LEN:
            return self.bad_request(f"{self._RETRY_KEY_HEADER} must be at most {self._MAX_CALLER_KEY_LEN} characters.")
        return key

    @staticmethod
    def _agents_selection(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize the raw caller agent selection for the retry digest (not catalog-resolved)."""
        if "agents" in data:
            agents = cast(dict[str, int], data["agents"])
            return {"agents": {str(key): int(value) for key, value in sorted(agents.items())}}
        return {"agent_id": data.get("agent_id")}

    def _dispatch_launch(self, request: Request, user: User, data: dict[str, Any]) -> Response:
        """Route a validated launch: recover a retry key before catalog validation, else create."""
        caller_key = self._retry_key(request)
        if isinstance(caller_key, Response):
            return caller_key
        if caller_key is not None:
            recovered = self._try_recover(user, data, caller_key)
            if recovered is not None:
                return recovered
        return self._launch_range(request, user, data, caller_key)

    def _try_recover(self, user: User, data: dict[str, Any], caller_key: str) -> Response | None:
        """Return a recovered/409 response, or ``None`` for first use (no catalog check)."""
        try:
            outcome = resolve_retry_recovery(
                user,
                scenario=str(data.get("scenario", "basic")),
                agents_selection=self._agents_selection(data),
                workspace_uuid=data.get("workspace_uuid"),
                caller_key=caller_key,
                model_sources=data.get("model_sources"),
            )
        except RetryKeyConflict:
            logger.info("Retry key conflict: user=%s", user.pk)
            return self.error_response(
                code="retry_key_conflict",
                message="This idempotency key is already bound to a different launch request.",
                status_code=409,
            )
        if outcome is None:
            return None
        return self._bound_range_response(user, outcome, recovered=True)

    def _create_range_first_use(
        self,
        request: Request,
        user: User,
        scenario: str,
        agents_by_os: dict[str, int] | None,
        caller_key: str,
        choices: LaunchChoices,
    ) -> Response:
        """First use of a retry key: dispatch, bind, and audit exactly once (#2086, ADR-063).

        A concurrent contender that wins the key rolls this dispatch back and its
        bound operation is recovered instead (or conflicts, 409). Recovery is not
        reached here (it short-circuits before catalog validation).
        """
        try:
            outcome = bind_first_use_launch(
                user,
                scenario=scenario,
                agents_selection=choices.agents_selection,
                agents_by_os=agents_by_os or {},
                workspace_uuid=choices.workspace_uuid,
                caller_key=caller_key,
                model_sources=choices.model_sources,
            )
        except RetryKeyConflict:
            logger.info("Retry key conflict: user=%s scenario=%s", user.pk, safe_log_value(scenario))
            return self.error_response(
                code="retry_key_conflict",
                message="This idempotency key is already bound to a different launch request.",
                status_code=409,
            )
        except CMSError as exc:
            return self._launch_failure_response(exc, user, scenario)

        if outcome.created:
            logger.info(
                "Range launched (retry-safe): user=%s request_id=%s scenario=%s",
                safe_log_value(user.email),
                outcome.request_id,
                safe_log_value(scenario),
            )
            _audit_range_lifecycle(
                _raw_request(request),
                AuditAction.PROVISION,
                range_request_id=outcome.request_id,
                extra_state={"scenario": scenario, "agents": agents_by_os, "retry_safe": True},
            )
        return self._bound_range_response(user, outcome, recovered=not outcome.created)

    @staticmethod
    def _bound_range_response(user: User, outcome: RetrySafeLaunchOutcome, *, recovered: bool) -> Response:
        """Project the BOUND range (terminal-aware), never the caller's current active range."""
        try:
            range_ctx = get_range_by_request_id(user, outcome.request_id, include_terminal=True)
            range_payload: dict[str, Any] | None = range_ctx.model_dump(mode="json")
        except CMSError:
            range_payload = None
        return Response({"success": True, "recovered": recovered, "range": range_payload})
