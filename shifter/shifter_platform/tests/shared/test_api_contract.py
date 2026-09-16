"""Tests for the committed ``/api/v1/`` OpenAPI contract and its gates (#1329).

Integration-style: the published document is generated once per module and many
assertions read it, rather than one mocked micro-test per property. The
breaking-change gate mocks only the true subprocess boundary (oasdiff/git), per
the boundary-mock policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

import config.management.commands.api_contract as api_contract_command
from shared.api import contract
from shared.api.schema import PlatformAutoSchema, exclude_unpublished_endpoints


@pytest.fixture(scope="module")
def openapi_document() -> dict[str, Any]:
    """The canonical published document, generated from the live DRF surface.

    Generation runs with validation and fail-on-warn, so an unresolved
    serializer, operation-id collision, or schema warning fails this fixture and
    therefore the whole module.
    """
    return json.loads(contract.generate_openapi_document())


class _Callback:
    """Stand-in for a resolved DRF view callback carrying its view class."""

    def __init__(self, module: str) -> None:
        self.cls = type("_View", (), {"__module__": module})


class TestExclusionHook:
    def test_drops_unpublished_app_keeps_published(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The hook filters by whatever prefixes are configured. CTF is now
        # published (its SPA consumer #1372 landed, so the live tuple is empty);
        # pin a synthetic prefix here to exercise the drop-vs-keep mechanism
        # independently of the current config.
        monkeypatch.setattr("shared.api.schema.UNPUBLISHED_VIEW_MODULE_PREFIXES", ("some_unpublished_app.",))
        unpublished = (
            "/api/v1/some-unpublished-app/",
            "^u$",
            "GET",
            _Callback("some_unpublished_app.api.views"),
        )
        mission_control = (
            "/api/v1/mission-control/range/",
            "^mc$",
            "GET",
            _Callback("mission_control.api.ranges"),
        )
        result = exclude_unpublished_endpoints([unpublished, mission_control])
        assert unpublished not in result
        assert mission_control in result

    def test_empty_prefix_tuple_keeps_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The live configuration: no app is excluded, so the hook is a no-op.
        monkeypatch.setattr("shared.api.schema.UNPUBLISHED_VIEW_MODULE_PREFIXES", ())
        ctf = ("/api/v1/ctf/events/", "^ctf$", "GET", _Callback("ctf.api.organizer_views"))
        assert exclude_unpublished_endpoints([ctf]) == [ctf]


class TestPublishedContract:
    def test_ctf_surface_published(self, openapi_document: dict[str, Any]) -> None:
        # CTF joined the published contract when its SPA consumer (#1372) landed.
        paths = openapi_document["paths"]
        assert any(path.startswith("/api/v1/ctf/") for path in paths)
        assert "/api/v1/ctf/events/" in paths
        assert "/api/v1/ctf/me/challenges/" in paths

    def test_mission_control_post_has_request_body(self, openapi_document: dict[str, Any]) -> None:
        launch = openapi_document["paths"]["/api/v1/mission-control/range/launch/"]["post"]
        assert "requestBody" in launch

    def test_error_envelope_is_a_reusable_component(self, openapi_document: dict[str, Any]) -> None:
        schemas = openapi_document["components"]["schemas"]
        assert "ApiError" in schemas
        assert "ApiErrorBody" in schemas
        body = schemas["ApiErrorBody"]["properties"]
        assert {"code", "message"} <= set(body)

    def test_error_responses_reference_the_envelope(self, openapi_document: dict[str, Any]) -> None:
        # Only the statuses the shared exception handler guarantees are injected.
        audit = openapi_document["paths"]["/api/v1/audit/"]["get"]
        for code in ("401", "403"):
            schema = audit["responses"][code]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/ApiError")

    def test_body_dependent_errors_are_not_injected_globally(self, openapi_document: dict[str, Any]) -> None:
        # 400/404 shapes vary per endpoint (some legacy views return non-envelope
        # errors), so they must not be blanket-injected onto every operation.
        audit = openapi_document["paths"]["/api/v1/audit/"]["get"]
        assert "400" not in audit["responses"]
        assert "404" not in audit["responses"]

    def test_audit_publishes_real_filters_and_drops_inert_search_ordering(
        self, openapi_document: dict[str, Any]
    ) -> None:
        # The audit read must advertise the exact structured filters it applies
        # and must not advertise the global SearchFilter/OrderingFilter params it
        # ignores (they were inert). `page` stays for the canonical pagination.
        params = {parameter["name"] for parameter in openapi_document["paths"]["/api/v1/audit/"]["get"]["parameters"]}
        assert {
            "entity_type",
            "entity_id",
            "action",
            "actor_type",
            "actor_id",
            "request_id",
            "from_date",
            "to_date",
            "page",
        } <= params
        assert "search" not in params
        assert "ordering" not in params

    def test_audit_advertises_only_the_credential_it_accepts(self, openapi_document: dict[str, Any]) -> None:
        # The runtime authenticates bearer-first to fail closed, but the audit
        # permission rejects every API-token principal, so the published contract
        # must advertise session-cookie auth only — never ApiTokenAuth as an
        # accepted alternative for either audit operation.
        for path in ("/api/v1/audit/", "/api/v1/audit/{id}/"):
            security = openapi_document["paths"][path]["get"]["security"]
            assert security == [{"cookieAuth": []}]

    def test_workspace_invitations_advertise_only_session_auth(self, openapi_document: dict[str, Any]) -> None:
        collection = openapi_document["paths"]["/api/v1/workspaces/{workspace_uuid}/invitations/"]
        resend = openapi_document["paths"]["/api/v1/workspaces/{workspace_uuid}/invitations/{invitation_uuid}/resend/"]
        revoke = openapi_document["paths"]["/api/v1/workspaces/{workspace_uuid}/invitations/{invitation_uuid}/revoke/"]

        for operation in (collection["get"], collection["post"], resend["post"], revoke["post"]):
            assert operation["security"] == [{"cookieAuth": []}]

    def test_workspace_session_operations_advertise_only_session_auth(self, openapi_document: dict[str, Any]) -> None:
        paths = openapi_document["paths"]
        operations = (
            paths["/api/v1/workspaces/context/"]["get"],
            paths["/api/v1/workspaces/organizations/"]["get"],
            paths["/api/v1/workspaces/organizations/{organization_uuid}/"]["get"],
            paths["/api/v1/workspaces/organizations/{organization_uuid}/"]["patch"],
        )

        for operation in operations:
            assert operation["security"] == [{"cookieAuth": []}]

    def test_range_launch_declares_validation_denial_and_quota_conflict(self, openapi_document: dict[str, Any]) -> None:
        responses = openapi_document["paths"]["/api/v1/mission-control/range/launch/"]["post"]["responses"]

        for status in ("400", "403", "409"):
            schema = responses[status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/ApiError")
        assert "workspace_range_quota_exceeded" in responses["409"]["description"]

    def test_public_scoreboard_contract_matches_the_stable_runtime_shape(
        self, openapi_document: dict[str, Any]
    ) -> None:
        schema = openapi_document["paths"]["/api/v1/ctf/events/{event_id}/scoreboard/"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        name = schema["$ref"].rsplit("/", 1)[-1]
        scoreboard = openapi_document["components"]["schemas"][name]

        expected = {
            "scoreboard_hidden",
            "event_id",
            "team_mode",
            "frozen",
            "rankings",
            "bracket_rankings",
            "brackets",
        }
        assert set(scoreboard["required"]) == expected
        assert set(scoreboard["properties"]) == expected

    def test_created_endpoints_declare_201(self, openapi_document: dict[str, Any]) -> None:
        # NGFW/credential creates return 201; the contract must not claim 200.
        ngfw = openapi_document["paths"]["/api/v1/mission-control/ngfw/"]["post"]
        assert "201" in ngfw["responses"]
        assert "200" not in ngfw["responses"]

    def test_token_scopes_published_for_scoped_operations(self, openapi_document: dict[str, Any]) -> None:
        assert openapi_document["paths"]["/api/v1/mission-control/range/"]["get"]["x-required-scopes"] == [
            "mission_control:range:read"
        ]

    def test_unscoped_operations_omit_scope_extension(self, openapi_document: dict[str, Any]) -> None:
        # Admin-only audit reads are not token-scoped; they must not advertise a scope.
        assert "x-required-scopes" not in openapi_document["paths"]["/api/v1/audit/"]["get"]

    def test_scenario_detail_is_read_scoped_and_read_only(self, openapi_document: dict[str, Any]) -> None:
        detail = openapi_document["paths"]["/api/v1/cms/scenarios/{scenario_id}/"]
        assert detail["get"]["x-required-scopes"] == ["cms:authoring:read"]
        assert "patch" not in detail

    def test_legacy_scenario_editor_api_is_retired_exactly(self) -> None:
        metadata = json.loads(contract.retirement_path().read_text(encoding="utf-8"))
        retirement = next(item for item in metadata["retirements"] if item["issue"] == 1311)

        assert retirement["adr"] == "ADR-024"
        assert set(retirement["paths"]) == {
            "/api/v1/cms/scenario-editor/scenarios/",
            "/api/v1/cms/scenario-editor/scenarios/from-yaml/",
            "/api/v1/cms/scenario-editor/scenarios/{scenario_id}/",
            "/api/v1/cms/scenario-editor/scenarios/{scenario_id}/clone/",
            "/api/v1/cms/scenario-editor/scenarios/{scenario_id}/export/",
            "/api/v1/cms/scenario-editor/scenarios/{scenario_id}/metadata/",
            "/api/v1/cms/scenario-editor/scenarios/{scenario_id}/realizability/",
            "/api/v1/cms/scenario-editor/validate-yaml/",
        }
        assert {tuple(item.values()) for item in retirement["response_schema_properties"]} == {
            ("Bootstrap", "feature_flags"),
            ("ScenarioDetail", "deletable"),
            ("ScenarioDetail", "description"),
            ("ScenarioDetail", "editable"),
            ("ScenarioDetail", "exportable"),
            ("ScenarioDetail", "instances"),
            ("ScenarioDetail", "is_default"),
            ("ScenarioDetail", "ngfw"),
            ("ScenarioDetail", "participant_access"),
            ("ScenarioDetail", "subnets"),
        }

    def test_both_auth_schemes_present(self, openapi_document: dict[str, Any]) -> None:
        assert {"ApiTokenAuth", "cookieAuth"} <= set(openapi_document["components"]["securitySchemes"])


@pytest.mark.django_db
class TestLiveResponseParity:
    """Request-level parity: a live response must agree with the published schema."""

    def test_unauthenticated_request_matches_published_401(self, openapi_document: dict[str, Any]) -> None:
        from rest_framework.test import APIClient

        path = "/api/v1/mission-control/range/"
        response = APIClient().get(path)
        assert response.status_code == 401
        # Live body is the canonical envelope the exception handler renders...
        body = response.json()
        assert {"code", "message"} <= set(body["error"])
        # ...and the contract publishes exactly that shape for 401 on this operation.
        published = openapi_document["paths"][path]["get"]["responses"]["401"]
        assert published["content"]["application/json"]["schema"]["$ref"].endswith("/ApiError")


# The committed-artifact-vs-DRF-surface drift gate is enforced authoritatively by
# the standalone CI job (`manage.py api_contract --check`, a fresh hermetic SQLite
# process). It is deliberately NOT asserted here: regenerating the whole schema
# mid-suite is sensitive to global state (URL conf, SPECTACULAR_SETTINGS,
# drf-spectacular's extension registry) that other tests can mutate, and it also
# varies by DB backend (integer_field_ranges). check_drift's own logic is covered
# in isolation by TestContractDriftBranches and TestApiContractCommand below.


class TestBreakingChangeGate:
    def test_accepted_feature_retirement_projects_only_exact_elements(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        metadata = tmp_path / "v1.retirements.json"
        metadata.write_text(
            json.dumps(
                {
                    "api_major": "v1",
                    "retirements": [
                        {
                            "adr": "ADR-045",
                            "issue": 1374,
                            "paths": ["/api/v1/retired/"],
                            "response_schema_properties": [{"schema": "Bootstrap", "property": "retired"}],
                        },
                        {
                            "adr": "ADR-024",
                            "issue": 1862,
                            "paths": ["/api/v1/also-retired/"],
                            "response_schema_properties": [{"schema": "Bootstrap", "property": "also_retired"}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(contract, "retirement_path", lambda major=contract.API_MAJOR: metadata)
        base = {
            "paths": {
                "/api/v1/retired/": {},
                "/api/v1/also-retired/": {},
                "/api/v1/kept/": {},
            },
            "components": {
                "schemas": {
                    "Bootstrap": {
                        "properties": {
                            "retired": {"type": "boolean"},
                            "also_retired": {"type": "boolean"},
                            "kept": {"type": "boolean"},
                        },
                        "required": ["kept", "retired", "also_retired"],
                    }
                }
            },
        }
        current = {
            "paths": {"/api/v1/kept/": {}},
            "components": {
                "schemas": {
                    "Bootstrap": {
                        "properties": {"kept": {"type": "boolean"}},
                        "required": ["kept"],
                    }
                }
            },
        }

        projected = json.loads(contract.apply_accepted_retirements(json.dumps(base), json.dumps(current)))

        assert projected == current

    def test_accepted_feature_retirement_rejects_reintroduction(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        metadata = tmp_path / "v1.retirements.json"
        metadata.write_text(
            json.dumps(
                {
                    "api_major": "v1",
                    "retirements": [
                        {
                            "adr": "ADR-045",
                            "issue": 1374,
                            "paths": ["/api/v1/retired/"],
                            "response_schema_properties": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(contract, "retirement_path", lambda major=contract.API_MAJOR: metadata)
        document = json.dumps({"paths": {"/api/v1/retired/": {}}})

        with pytest.raises(RuntimeError, match="reintroduced"):
            contract.apply_accepted_retirements(document, document)

    def test_accepted_feature_retirement_rejects_legacy_metadata_shape(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        metadata = tmp_path / "v1.retirements.json"
        metadata.write_text(
            json.dumps(
                {
                    "api_major": "v1",
                    "adr": "ADR-045",
                    "issue": 1374,
                    "paths": ["/api/v1/retired/"],
                    "response_schema_properties": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(contract, "retirement_path", lambda major=contract.API_MAJOR: metadata)

        with pytest.raises(RuntimeError, match="Invalid API retirement metadata"):
            contract.apply_accepted_retirements("{}", "{}")

    def test_breaking_change_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            contract.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="1 error: api path removed", stderr=""),
        )
        is_compatible, detail = contract.check_breaking_changes("{}", "{}")
        assert not is_compatible
        assert "error" in detail

    def test_compatible_change_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            contract.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="No breaking changes", stderr=""),
        )
        is_compatible, _detail = contract.check_breaking_changes("{}", "{}")
        assert is_compatible

    def test_new_major_skips_when_base_artifact_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "resolve_base_document", lambda base_ref, major=contract.API_MAJOR: None)
        ok, detail = contract.check_breaking_against("origin/dev")
        assert ok
        assert "skipped" in detail.lower()

    @staticmethod
    def _fake_git(*, verify_rc: int, ls_tree_rc: int, ls_tree_out: str, show_out: str = "{}"):
        def fake_git(*args: str, cwd: Any = None) -> SimpleNamespace:
            if args[:2] == ("rev-parse", "--show-toplevel"):
                return SimpleNamespace(returncode=0, stdout="/\n", stderr="")
            if args[0] == "rev-parse":
                return SimpleNamespace(returncode=verify_rc, stdout="", stderr="bad ref")
            if args[0] == "ls-tree":
                return SimpleNamespace(returncode=ls_tree_rc, stdout=ls_tree_out, stderr="ls-tree failed")
            if args[0] == "show":
                return SimpleNamespace(returncode=0, stdout=show_out, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return fake_git

    def test_resolve_base_returns_none_when_path_genuinely_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ref resolves, ls-tree succeeds with empty output -> genuine first publication.
        monkeypatch.setattr(contract, "_git", self._fake_git(verify_rc=0, ls_tree_rc=0, ls_tree_out=""))
        assert contract.resolve_base_document("origin/dev") is None

    def test_resolve_base_fails_closed_on_unresolvable_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "_git", self._fake_git(verify_rc=1, ls_tree_rc=0, ls_tree_out=""))
        with pytest.raises(RuntimeError, match="could not be resolved"):
            contract.resolve_base_document("bogus-ref")

    def test_resolve_base_fails_closed_on_lookup_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ref resolves but the path query itself errors -> must raise, never skip.
        monkeypatch.setattr(contract, "_git", self._fake_git(verify_rc=0, ls_tree_rc=128, ls_tree_out=""))
        with pytest.raises(RuntimeError, match="failed to query"):
            contract.resolve_base_document("origin/dev")

    def test_resolve_base_reads_present_artifact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            contract,
            "_git",
            self._fake_git(verify_rc=0, ls_tree_rc=0, ls_tree_out="100644 blob abc\topenapi/v1.json\n", show_out="{}"),
        )
        assert contract.resolve_base_document("origin/dev") == "{}"

    def test_resolve_base_runs_path_commands_from_repo_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Guards the base-path fix: ls-tree/show must run from the repo root so a
        # repo-relative pathspec and <ref>:<path> resolve (an artifact in a
        # subdirectory must be found, not treated as absent and skipped).
        monkeypatch.setattr(contract, "ARTIFACT_DIR", Path("/repo/api"))
        seen: dict[str, Any] = {}

        def fake_git(*args: str, cwd: Any = None) -> SimpleNamespace:
            if args[:2] == ("rev-parse", "--show-toplevel"):
                return SimpleNamespace(returncode=0, stdout="/repo\n", stderr="")
            if args[0] == "ls-tree":
                seen["ls_tree"] = cwd
                return SimpleNamespace(returncode=0, stdout="100644 blob abc\tapi/v1.json\n", stderr="")
            if args[0] == "show":
                seen["show"] = cwd
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(contract, "_git", fake_git)
        assert contract.resolve_base_document("origin/dev") == "{}"
        assert seen["ls_tree"] == Path("/repo")
        assert seen["show"] == Path("/repo")

    def test_git_helper_invokes_git_with_argv_and_cwd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            captured["argv"] = argv
            captured["cwd"] = kwargs.get("cwd")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(contract.subprocess, "run", fake_run)
        result = contract._git("status", cwd=Path("/repo/cwd"))
        assert result.stdout == "ok"
        assert captured["argv"][1:] == ["status"]
        assert captured["cwd"] == Path("/repo/cwd")

    def test_breaking_against_reports_missing_committed_artifact(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(contract, "resolve_base_document", lambda base_ref, major=contract.API_MAJOR: "{}")
        monkeypatch.setattr(contract, "ARTIFACT_DIR", tmp_path)
        ok, detail = contract.check_breaking_against("origin/dev")
        assert not ok
        assert "missing" in detail.lower()


class TestContractDriftBranches:
    def test_check_drift_reports_missing_artifact(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "ARTIFACT_DIR", tmp_path)  # no committed artifact present
        ok, detail = contract.check_drift()
        assert not ok
        assert "missing" in detail.lower()

    def test_check_drift_reports_bounded_diff(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "ARTIFACT_DIR", tmp_path)
        (tmp_path / "v1.json").write_text('{"openapi": "3.0.3"}\n', encoding="utf-8")
        ok, detail = contract.check_drift()
        assert not ok
        assert detail  # a unified diff, not empty


class TestApiContractCommand:
    def test_write_then_check_roundtrip(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "ARTIFACT_DIR", tmp_path)
        call_command("api_contract")
        assert (tmp_path / "v1.json").exists()
        call_command("api_contract", check=True)  # regenerated == committed -> no CommandError

    def test_check_raises_on_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(api_contract_command, "check_drift", lambda major: (False, "boom"))
        with pytest.raises(CommandError, match="drift"):
            call_command("api_contract", check=True)

    def test_breaking_against_skips_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contract, "resolve_base_document", lambda base_ref, major=contract.API_MAJOR: None)
        call_command("api_contract", breaking_against="origin/dev")  # skip -> no CommandError

    def test_breaking_against_raises_on_break(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(api_contract_command, "check_breaking_against", lambda base_ref, major: (False, "break"))
        with pytest.raises(CommandError, match="Breaking API change"):
            call_command("api_contract", breaking_against="origin/dev")


class TestPlatformAutoSchemaFallback:
    def test_resolved_permissions_falls_back_when_get_permissions_raises(self) -> None:
        class _Perm:
            required_read_scope = "mission_control:range:read"
            required_write_scope = "mission_control:range:write"

        class _View:
            permission_classes = [_Perm]

            def get_permissions(self) -> list[Any]:
                raise RuntimeError("boom")

        schema = PlatformAutoSchema()
        schema.view = _View()
        resolved = schema._resolved_permissions()
        assert any(isinstance(permission, _Perm) for permission in resolved)
