from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from config.openfga_authorization import (
    OpenFgaAuthorizationProvider,
    OpenFgaRuntimeSettings,
    runtime_settings_from_django,
)
from shared.authorization import (
    AuthorizationProviderError,
    AuthorizationRequest,
    CredentialCeiling,
    DecisionKind,
    PolicyEffect,
    PolicyRelationshipChange,
    RelationshipSubject,
    TargetRef,
    VersionedRelationshipChange,
)
from shared.identity_scope import PrincipalRef, ResourceScope

PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
MODEL_ID = "01J00000000000000000000000"
STORE_ID = "01J00000000000000000000001"


def _settings(**overrides: object) -> OpenFgaRuntimeSettings:
    values = {
        "api_url": "https://openfga.internal.example",
        "store_id": STORE_ID,
        "model_id": MODEL_ID,
        "api_token": "test-only-token",
        "ca_cert_path": "/run/secrets/openfga-ca/ca.crt",
        "timeout_ms": 1200,
    }
    values.update(overrides)
    return OpenFgaRuntimeSettings(**values)  # type: ignore[arg-type]


def _request() -> AuthorizationRequest:
    return AuthorizationRequest(
        principal=PrincipalRef(PRINCIPAL_ID, "human"),
        action="account.read",
        target=TargetRef("account", ACCOUNT_ID),
        scope=ResourceScope(kind="account", account_uuid=ACCOUNT_ID),
        credential=CredentialCeiling(frozenset({"account.read"})),
    )


class FakeClient:
    def __init__(
        self,
        *,
        allowed: bool = True,
        error: Exception | None = None,
        batch_result: object = None,
    ):
        self.allowed = allowed
        self.error = error
        self.batch_result = batch_result
        self.check_call: tuple[object, object] | None = None
        self.batch_call: tuple[object, object] | None = None
        self.write_call: tuple[object, object] | None = None
        self.read_calls: list[tuple[object, object]] = []
        self.read_changes_call: tuple[object, object] | None = None
        self.present_relations: set[str] = set()
        self.ancestry_parents = ("installation:root",)

    def check(self, body: object, options: object) -> object:
        self.check_call = (body, options)
        if self.error:
            raise self.error
        return SimpleNamespace(allowed=self.allowed)

    def batch_check(self, body: object, options: object) -> object:
        self.batch_call = (body, options)
        if self.error:
            raise self.error
        return SimpleNamespace(result=self.batch_result)

    def write(self, body: object, options: object) -> object:
        self.write_call = (body, options)
        if self.error:
            raise self.error
        return SimpleNamespace()

    def read(self, body: object, options: object) -> object:
        self.read_calls.append((body, options))
        if self.error:
            raise self.error
        if body.relation == "installation":
            return SimpleNamespace(
                tuples=[SimpleNamespace(key=SimpleNamespace(user=parent)) for parent in self.ancestry_parents],
                continuation_token="",
            )
        tuples = [SimpleNamespace()] if body.relation in self.present_relations else []
        return SimpleNamespace(tuples=tuples)

    def read_changes(self, body: object, options: object) -> object:
        self.read_changes_call = (body, options)
        if self.error:
            raise self.error
        return SimpleNamespace(changes=[SimpleNamespace()], continuation_token="next-page")


def test_runtime_settings_require_private_tls_auth_and_pins() -> None:
    with pytest.raises(ValueError, match="https"):
        _settings(api_url="http://openfga.internal")
    with pytest.raises(ValueError, match="token"):
        _settings(api_token="")
    with pytest.raises(ValueError, match="model"):
        _settings(model_id="")
    with pytest.raises(ValueError, match="model"):
        _settings(model_id="latest")
    with pytest.raises(ValueError, match="store"):
        _settings(store_id="not-a-store-id")
    with pytest.raises(ValueError, match="https"):
        _settings(api_url="https://user:password@openfga.internal")
    assert "test-only-token" not in repr(_settings())


def test_django_runtime_binding_reads_bounded_secret_file(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("mounted-token\n")

    with override_settings(
        OPENFGA_ENABLED=True,
        OPENFGA_API_URL="https://openfga.internal.example",
        OPENFGA_STORE_ID=STORE_ID,
        OPENFGA_MODEL_ID=MODEL_ID,
        OPENFGA_API_TOKEN_FILE=str(token_file),
        OPENFGA_CA_CERT_PATH="/run/secrets/openfga-ca/ca.crt",
        OPENFGA_TIMEOUT_MS=1200,
    ):
        bound = runtime_settings_from_django()

    assert bound.api_token == "mounted-token"
    assert bound.model_id == MODEL_ID


def test_django_runtime_binding_is_unavailable_until_enabled() -> None:
    with override_settings(OPENFGA_ENABLED=False), pytest.raises(ImproperlyConfigured, match="not enabled"):
        runtime_settings_from_django()


def test_diagnostic_change_read_is_bounded_and_returns_no_tuple_payload() -> None:
    client = FakeClient()
    provider = OpenFgaAuthorizationProvider(_settings(), client=client)

    page = provider.read_changes("workspace", page_size=50)

    assert page.change_count == 1
    assert page.continuation_token == "next-page"
    assert client.read_changes_call is not None
    body, options = client.read_changes_call
    assert body.type == "workspace"
    assert options == {"page_size": 50}


def test_check_uses_pinned_model_primary_consistency_and_concrete_object() -> None:
    client = FakeClient()
    provider = OpenFgaAuthorizationProvider(_settings(), client=client)

    decision = provider.check(_request())

    assert decision.kind == DecisionKind.ALLOWED
    assert client.check_call is not None
    body, options = client.check_call
    assert body.user == f"principal:{PRINCIPAL_ID}"
    assert body.object == f"account:{ACCOUNT_ID}"
    assert body.relation == "can_account_read"
    assert options == {"authorization_model_id": MODEL_ID, "consistency": "HIGHER_CONSISTENCY"}


@pytest.mark.parametrize(
    ("direct_parent", "event_parent", "allowed"),
    [(False, "valid", True), (True, "valid", True), (True, "wrong", False), (False, "missing", False)],
)
def test_range_accepts_event_ancestry_but_rejects_conflicting_or_missing_parents(
    direct_parent, event_parent, allowed
) -> None:
    organization, workspace, event, range_uuid = (uuid4() for _ in range(4))
    parents = {
        (f"account:{ACCOUNT_ID}", "installation"): ("installation:root",),
        (f"organization:{organization}", "account"): (f"account:{ACCOUNT_ID}",),
        (f"workspace:{workspace}", "organization"): (f"organization:{organization}",),
        (f"range:{range_uuid}", "workspace"): (f"workspace:{workspace}",) if direct_parent else (),
        (f"range:{range_uuid}", "event"): () if event_parent == "missing" else (f"event:{event}",),
        (f"event:{event}", "workspace"): (f"workspace:{workspace if event_parent == 'valid' else uuid4()}",),
    }

    class AncestryClient(FakeClient):
        def read(self, body, options):
            return SimpleNamespace(
                tuples=[
                    SimpleNamespace(key=SimpleNamespace(user=parent))
                    for parent in parents.get((body.object, body.relation), ())
                ],
                continuation_token="",
            )

    provider = OpenFgaAuthorizationProvider(_settings(), client=AncestryClient())
    request = AuthorizationRequest(
        PrincipalRef(PRINCIPAL_ID, "human"),
        "range.read",
        TargetRef("range", range_uuid),
        ResourceScope("account", ACCOUNT_ID, organization, workspace),
        CredentialCeiling(frozenset({"range.read"})),
    )
    assert provider.check(request).allowed is allowed


@pytest.mark.parametrize("parent_type", ["account", "organization", "workspace"])
def test_event_check_accepts_exact_customer_parent(parent_type: str) -> None:
    organization, workspace, event = (uuid4() for _ in range(3))
    scope = {
        "account": ResourceScope("account", ACCOUNT_ID),
        "organization": ResourceScope("account", ACCOUNT_ID, organization),
        "workspace": ResourceScope("account", ACCOUNT_ID, organization, workspace),
    }[parent_type]
    parent_uuid = {"account": ACCOUNT_ID, "organization": organization, "workspace": workspace}[parent_type]
    parents = {
        (f"account:{ACCOUNT_ID}", "installation"): ("installation:root",),
        (f"organization:{organization}", "account"): (f"account:{ACCOUNT_ID}",),
        (f"workspace:{workspace}", "organization"): (f"organization:{organization}",),
        (f"event:{event}", parent_type): (f"{parent_type}:{parent_uuid}",),
    }

    class AncestryClient(FakeClient):
        def read(self, body, options):
            return SimpleNamespace(
                tuples=[
                    SimpleNamespace(key=SimpleNamespace(user=parent))
                    for parent in parents.get((body.object, body.relation), ())
                ],
                continuation_token="",
            )

    provider = OpenFgaAuthorizationProvider(_settings(), client=AncestryClient())
    request = AuthorizationRequest(
        PrincipalRef(PRINCIPAL_ID, "service"),
        "event.manage",
        TargetRef("event", event),
        scope,
        CredentialCeiling(frozenset({"event.manage"})),
    )

    assert provider.check(request).allowed

    conflicting_parent = "workspace" if parent_type != "workspace" else "account"
    conflicting_uuid = workspace if conflicting_parent == "workspace" else ACCOUNT_ID
    parents[f"event:{event}", conflicting_parent] = (f"{conflicting_parent}:{conflicting_uuid}",)
    assert not provider.check(request).allowed


def test_account_event_range_inherits_only_its_exact_event_parent() -> None:
    event, range_uuid = uuid4(), uuid4()
    parents = {
        (f"account:{ACCOUNT_ID}", "installation"): ("installation:root",),
        (f"range:{range_uuid}", "event"): (f"event:{event}",),
        (f"event:{event}", "account"): (f"account:{ACCOUNT_ID}",),
    }

    class AncestryClient(FakeClient):
        def read(self, body, options):
            return SimpleNamespace(
                tuples=[
                    SimpleNamespace(key=SimpleNamespace(user=parent))
                    for parent in parents.get((body.object, body.relation), ())
                ],
                continuation_token="",
            )

    provider = OpenFgaAuthorizationProvider(_settings(), client=AncestryClient())
    request = AuthorizationRequest(
        PrincipalRef(PRINCIPAL_ID, "service"),
        "range.read",
        TargetRef("range", range_uuid),
        ResourceScope("account", ACCOUNT_ID),
        CredentialCeiling(frozenset({"range.read"})),
    )

    assert provider.check(request).allowed


def test_false_and_provider_errors_fail_closed_without_provider_text() -> None:
    denied = OpenFgaAuthorizationProvider(_settings(), client=FakeClient(allowed=False)).check(_request())
    failed = OpenFgaAuthorizationProvider(
        _settings(), client=FakeClient(error=RuntimeError("token=do-not-leak"))
    ).check(_request())

    assert denied.kind == DecisionKind.DENIED
    assert denied.reason == "policy_denied"
    assert failed.kind == DecisionKind.EVALUATOR_ERROR
    assert failed.reason == "evaluator_unavailable"


def test_batch_is_correlated_and_incomplete_or_per_item_error_denies_whole_batch() -> None:
    request = _request()
    complete = {
        "0": SimpleNamespace(allowed=True, error=None),
        "1": SimpleNamespace(allowed=True, error=None),
    }
    allowed_provider = OpenFgaAuthorizationProvider(_settings(), client=FakeClient(batch_result=complete))
    incomplete_provider = OpenFgaAuthorizationProvider(
        _settings(),
        client=FakeClient(batch_result={"0": complete["0"]}),
    )
    errored_provider = OpenFgaAuthorizationProvider(
        _settings(),
        client=FakeClient(
            batch_result={
                "0": complete["0"],
                "1": SimpleNamespace(allowed=False, error="failed"),
            }
        ),
    )

    assert all(result.allowed for result in allowed_provider.batch_check((request, request)))
    assert all(
        result.kind == DecisionKind.EVALUATOR_ERROR for result in incomplete_provider.batch_check((request, request))
    )
    assert all(
        result.kind == DecisionKind.EVALUATOR_ERROR for result in errored_provider.batch_check((request, request))
    )


def test_batch_accepts_sdk_normalized_list_without_trusting_response_order() -> None:
    request = _request()
    normalized = [
        SimpleNamespace(correlation_id="1", allowed=False, error=None),
        SimpleNamespace(correlation_id="0", allowed=True, error=None),
    ]

    results = OpenFgaAuthorizationProvider(_settings(), client=FakeClient(batch_result=normalized)).batch_check(
        (request, request)
    )

    assert results[0].allowed
    assert not results[1].allowed


def test_transactional_write_and_exact_primary_read_use_only_typed_relationships() -> None:
    client = FakeClient()
    provider = OpenFgaAuthorizationProvider(_settings(), client=client)
    change = PolicyRelationshipChange(
        subject=RelationshipSubject("principal", PRINCIPAL_ID),
        action="account.read",
        target=TargetRef("account", ACCOUNT_ID),
        effect=PolicyEffect.REVOKE,
    )

    provider.write_relationships(change)
    assert client.write_call is not None
    body, options = client.write_call
    assert [item.relation for item in body.writes] == ["deny_account_read"]
    assert [item.relation for item in body.deletes] == ["grant_account_read"]
    assert options["authorization_model_id"] == MODEL_ID
    assert "transaction" not in options

    client.present_relations = {"deny_account_read"}
    state = provider.read_relationships(change)
    assert state.grant_present is False
    assert state.deny_present is True
    assert all(options["consistency"] == "HIGHER_CONSISTENCY" for _, options in client.read_calls)


def test_generation_bound_write_is_append_only_and_verifies_every_provider_tuple() -> None:
    client = FakeClient()
    provider = OpenFgaAuthorizationProvider(_settings(), client=client)
    base = PolicyRelationshipChange(
        subject=RelationshipSubject("principal", PRINCIPAL_ID),
        action="account.read",
        target=TargetRef("account", ACCOUNT_ID),
        effect=PolicyEffect.REVOKE,
    )
    change = VersionedRelationshipChange(base, "a" * 64, 2)

    provider.write_relationships(change)

    assert client.write_call is not None
    body, _options = client.write_call
    assert [item.relation for item in body.writes] == ["candidate", "deny_account_read", "superseded"]
    assert body.deletes == []

    client.present_relations = {"candidate", "deny_account_read", "superseded"}
    state = provider.read_relationships(change)
    assert state.grant_present is False
    assert state.deny_present is True
    assert [call[0].relation for call in client.read_calls] == ["candidate", "deny_account_read", "superseded"]


def test_write_and_read_errors_are_sanitized_provider_errors() -> None:
    provider = OpenFgaAuthorizationProvider(_settings(), client=FakeClient(error=RuntimeError("token=do-not-leak")))
    change = PolicyRelationshipChange(
        subject=RelationshipSubject("principal", PRINCIPAL_ID),
        action="account.read",
        target=TargetRef("account", ACCOUNT_ID),
        effect=PolicyEffect.GRANT,
    )

    with pytest.raises(AuthorizationProviderError, match="OpenFGA relationship write failed"):
        provider.write_relationships(change)
    with pytest.raises(AuthorizationProviderError, match="OpenFGA relationship read failed"):
        provider.read_relationships(change)


@pytest.mark.parametrize("parents", [(), ("installation:other",), ("installation:root", "installation:other")])
def test_missing_stale_or_ambiguous_parent_denies_before_permission_evaluation(parents) -> None:
    client = FakeClient(allowed=True, batch_result={"0": SimpleNamespace(allowed=True, error=None)})
    client.ancestry_parents = parents
    provider = OpenFgaAuthorizationProvider(_settings(), client=client)

    assert not provider.check(_request()).allowed
    assert not provider.batch_check((_request(),))[0].allowed
    assert client.check_call is None
    assert client.batch_call is None
