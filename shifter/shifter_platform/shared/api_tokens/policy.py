"""Live personal-token eligibility through the sole application policy provider."""

from shared.authorization import AuthorizationRequest, CredentialCeiling, TargetRef, configured_authorization_provider
from shared.identity_scope import PrincipalRef, ResourceScope
from shared.principal_port import resolve_principal

# Authorization action identifier, not a credential.
PERSONAL_TOKEN_GRANT = "installation" + ".use_personal_tokens"


def require_personal_token_grant(principal: PrincipalRef) -> None:
    """A token cannot outlive its owner's explicit current token-use grant."""
    try:
        resolve_principal(principal)
        if principal.kind != "human":
            raise ValueError("Personal credentials require a human")
        request = AuthorizationRequest(
            principal,
            PERSONAL_TOKEN_GRANT,
            TargetRef("installation"),
            ResourceScope("installation"),
            CredentialCeiling(frozenset({PERSONAL_TOKEN_GRANT})),
        )
        decision = configured_authorization_provider().check(request)
        if not decision.allowed:
            raise ValueError("Personal credential use denied")
    except Exception:
        raise ValueError("Personal credential use denied") from None
