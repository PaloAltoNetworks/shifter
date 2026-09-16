"""CMS service exceptions.

Re-exports from shared.exceptions for backwards compatibility.
"""

from __future__ import annotations

import enum

from shared.exceptions import CMSError


class RangeScopeAdminError(CMSError):
    """A range-to-workspace scope administration outcome (PLAT-237, #1944).

    One typed, classified error under the existing ``CMSError`` hierarchy so the
    API maps outcomes to bounded status codes without string-matching a message.
    Every message is deliberately non-enumerating: it never reveals which
    specific fact (workspace existence, membership, role, archive state, or
    projection drift) produced the outcome. Callers catch the type and branch on
    :attr:`kind`, never on the message text.
    """

    class Kind(enum.Enum):
        """Bounded outcome classes the API maps to HTTP status codes."""

        NOT_FOUND = "not_found"
        """The range is absent, its projections disagree at read time, or the
        actor may not administer its source scope -> opaque 404."""

        TARGET_DENIED = "target_denied"
        """The target scope is ineligible (unknown, actor lacks authority,
        archived, or the range owner is not a member) -> opaque 409."""

        CONFLICT = "conflict"
        """Projection drift, duplicate projection, or a concurrent move made the
        binding inconsistent -> opaque 409."""

        NOT_REASSIGNABLE = "not_reassignable"
        """The range participates in a domain-owned immutable aggregate (for
        example an ADR-051 CTF event) and cannot be moved independently until the
        owning domain validates the target through its own seam -> opaque 409."""

    def __init__(self, kind: RangeScopeAdminError.Kind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class WorkspaceLaunchDenied(CMSError):
    """A launch's workspace selection is not available to the actor (ADR-046-R9).

    A subclass of ``CMSError`` so existing ``except CMSError`` sites keep treating
    it as a launch failure, while the launch command boundary can catch it
    specifically and map an authorized-shape-but-denied scope to an opaque 403 --
    distinct from the 400 a malformed UUID gets at input validation. The message
    stays non-enumerating: unknown workspace, non-membership, and a role that does
    not permit launching are deliberately indistinguishable. Never string-match
    this error; catch the type.
    """


class WorkspaceLaunchQuotaExceeded(CMSError):
    """A launch is blocked by an enforcing per-workspace concurrent-range quota (PLAT-239).

    A subclass of ``CMSError`` so existing ``except CMSError`` sites keep treating
    it as a launch failure, while the launch command boundary catches it
    specifically and maps hard exhaustion to a ``409 Conflict`` -- distinct from an
    authorization ``403`` (``WorkspaceLaunchDenied``) and a request-rate ``429``
    (ADR-046-R10). The message carries no tenant policy detail. Never string-match
    this error; catch the type.
    """


__all__ = ["CMSError", "RangeScopeAdminError", "WorkspaceLaunchDenied", "WorkspaceLaunchQuotaExceeded"]
