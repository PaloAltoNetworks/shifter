"""Closed RAES operation-input contract (ADR-043 phase 5, #1837).

Drives ``shared.raes.operation_input``: the bounded, byte-free projection the
Engine materializes into ``OperationInput`` and the provisioner consumes by
canonical ``operation_id`` instead of reading ``engine_raes_content_delivery_binding``,
``engine_raes_image_mapping``, ``mission_control_range``, and ``engine_instance``.

The parser is the boundary. These tests drive it through that boundary rather
than asserting the dataclass has fields.
"""

from __future__ import annotations

import pytest

from shared.raes.artifact_binding import ArtifactBinding
from shared.raes.content_delivery import DeliveryBinding
from shared.raes.operation_input import (
    MAX_DELIVERY_BINDINGS,
    MAX_IMAGE_CANDIDATES,
    RaesInputBindings,
    RaesOperationInputError,
    build_raes_operation_input,
    image_lookup_key,
    parse_raes_operation_input,
    plan_image_lookup_keys,
)


def _artifact_binding(target: str = "provision.node.web") -> ArtifactBinding:
    return ArtifactBinding(
        target=target,
        requirement_id="req-1",
        artifact_id="img-web",
        version="1.0.0",
        digest="sha256:" + "a" * 64,
        media_type="application/vnd.raes.image",
        mechanism="exact-artifact",
        acquisition="local-lookup",
        timing="backend-preparation",
        image_ref="projects/p/global/images/web",
    )


_SHA = "a" * 64


def _plan() -> dict:
    """A serialized RAES ProvisioningPlan with one sourced and one source-less node."""
    return {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v1",
        "raes_version": "2.0.0",
        "resources": {
            "net.lan": {
                "address": "net.lan",
                "resource_type": "network",
                "payload": {"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
            },
            "node.web": {
                "address": "node.web",
                "resource_type": "node",
                "payload": {
                    "name": "web",
                    "os_family": "linux",
                    "spec": {"node": {"source": "kali"}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
            "node.bare": {
                "address": "node.bare",
                "resource_type": "node",
                "payload": {
                    "name": "bare",
                    "os_family": "windows",
                    "spec": {"node": {}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
        },
    }


def _binding() -> DeliveryBinding:
    return DeliveryBinding(
        content_address="content.c",
        sha256=_SHA,
        storage_key=f"raes/content-delivery/aa/{_SHA}",
        byte_count=5,
    )


def _candidates() -> dict[str, list[dict[str, object]]]:
    return {
        "gce:kali": [
            {
                "source_version": "2024.1",
                "image_ref": "projects/p/global/images/kali",
                "machine_type": "e2-medium",
                "disk_size_gb": 40,
                "disk_type": "pd-balanced",
            }
        ]
    }


def _built(**overrides: object) -> dict:
    kwargs: dict[str, object] = {
        "plan": _plan(),
        "delivery_bindings": [_binding()],
        "image_candidates": _candidates(),
        "range_backend": "gce",
        "instantiation_purpose": "training",
        "legacy_range_id": 7,
    }
    kwargs.update(overrides)
    bindings = RaesInputBindings(
        delivery=kwargs.pop("delivery_bindings"),  # type: ignore[arg-type]
        access=kwargs.pop("access_bindings", ()),  # type: ignore[arg-type]
        artifact=kwargs.pop("artifact_bindings", ()),  # type: ignore[arg-type]
    )
    return build_raes_operation_input(bindings=bindings, **kwargs)  # type: ignore[arg-type]


class TestImageLookupKey:
    """The single key rule both sides must agree on."""

    def test_source_name_wins_over_os_family(self):
        assert image_lookup_key(source_name="kali", os_family="linux") == "kali"

    def test_falls_back_to_os_family_when_source_absent(self):
        assert image_lookup_key(source_name=None, os_family="windows") == "windows"
        assert image_lookup_key(source_name="", os_family="windows") == "windows"

    def test_empty_when_neither_is_authored(self):
        assert image_lookup_key(source_name=None, os_family=None) == ""

    def test_plan_keys_cover_sourced_and_sourceless_nodes(self):
        # The Engine scopes the registry projection with exactly these keys; a
        # key the provisioner would later derive but the Engine did not project
        # means a silently missing image at realization.
        assert plan_image_lookup_keys(_plan()) == ("kali", "windows")

    def test_plan_keys_extract_name_from_mapping_source(self):
        # The real compiled/serialized RAES plan stores a node's source as a
        # mapping ({name, build, version, artifact_requirement}), not a bare
        # string. The Engine must scope the registry projection by the source
        # NAME (e.g. "kali"), not fall back to os_family, or a source-bearing
        # GCE range resolves no image (empty image_candidates at realization).
        plan = {
            "resources": {
                "node.attacker": {
                    "address": "node.attacker",
                    "resource_type": "node",
                    "payload": {
                        "name": "attacker",
                        "os_family": "linux",
                        "spec": {
                            "node": {
                                "source": {
                                    "name": "kali",
                                    "build": None,
                                    "version": "*",
                                    "artifact_requirement": None,
                                }
                            }
                        },
                    },
                }
            }
        }
        assert plan_image_lookup_keys(plan) == ("kali",)

    def test_plan_keys_ignore_non_node_resources_and_are_deduped(self):
        plan = _plan()
        plan["resources"]["node.web2"] = {
            "address": "node.web2",
            "resource_type": "node",
            "payload": {"name": "web2", "os_family": "linux", "spec": {"node": {"source": "kali"}}},
        }
        assert plan_image_lookup_keys(plan) == ("kali", "windows")

    def test_malformed_plan_fails_closed(self):
        with pytest.raises(RaesOperationInputError):
            plan_image_lookup_keys({"resources": "not-a-mapping"})

    def test_plan_without_resources_yields_no_keys(self):
        # An empty/absent resources block is a plan concern for the
        # provisioner's parse_plan, not a transport error: scoping the registry
        # projection must not double as a second plan validator.
        assert plan_image_lookup_keys({}) == ()


class TestRoundTrip:
    def test_parse_returns_the_built_projection(self):
        parsed = parse_raes_operation_input(_built())
        assert parsed.plan == _plan()
        assert parsed.range_backend == "gce"
        assert parsed.instantiation_purpose == "training"
        assert parsed.legacy_range_id == 7
        assert [b.content_address for b in parsed.delivery_bindings] == ["content.c"]
        assert parsed.image_candidates_for("gce", "kali")[0]["image_ref"] == "projects/p/global/images/kali"

    def test_unreferenced_key_resolves_to_no_candidates_not_an_error(self):
        # A source with no registry entry is a resolver concern (fail-loud at
        # realization), not a transport error.
        assert parse_raes_operation_input(_built()).image_candidates_for("gce", "windows") == []

    def test_absent_backend_is_preserved_as_none(self):
        parsed = parse_raes_operation_input(_built(range_backend=None))
        assert parsed.range_backend is None

    def test_build_rejects_an_unnormalized_backend(self):
        with pytest.raises(RaesOperationInputError):
            _built(range_backend="GCE-legacy")


class TestArtifactBindings:
    """The optional artifact_bindings key: omitted when empty, round-trips when present (#1580)."""

    def test_omitted_from_payload_when_empty(self):
        # Rolling-deploy compat: a no-requirement plan produces no key at all, so an
        # older consumer never sees an unexpected field.
        payload = _built()
        assert "artifact_bindings" not in payload
        assert parse_raes_operation_input(payload).artifact_bindings == ()

    def test_payload_without_the_key_still_parses(self):
        # An older queued input has no key; the newer parser tolerates its absence.
        payload = _built()
        payload.pop("artifact_bindings", None)
        parsed = parse_raes_operation_input(payload)
        assert parsed.artifact_binding_for("provision.node.web") is None

    def test_round_trips_and_is_addressable_by_node(self):
        payload = _built(artifact_bindings=[_artifact_binding()])
        assert payload["artifact_bindings"]  # present when non-empty
        binding = parse_raes_operation_input(payload).artifact_binding_for("provision.node.web")
        assert binding is not None
        assert binding.image_ref == "projects/p/global/images/web"

    def test_duplicate_target_fails_closed(self):
        duplicate = [_artifact_binding(), _artifact_binding()]
        with pytest.raises(RaesOperationInputError, match="duplicates target"):
            _built(artifact_bindings=duplicate)


class TestFailsClosed:
    def test_unknown_top_level_key_is_rejected(self):
        payload = _built()
        payload["user_id"] = 3
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_missing_key_is_rejected(self):
        payload = _built()
        del payload["plan"]
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_binding_with_a_smuggled_url_is_rejected(self):
        # DeliveryBinding.from_transport is the gate; a bucket/URL/bytes field
        # riding along must not survive the boundary.
        payload = _built()
        payload["delivery_bindings"][0]["signed_url"] = "https://example.invalid/x"
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_binding_with_a_tampered_digest_is_rejected(self):
        payload = _built()
        payload["delivery_bindings"][0]["sha256"] = "not-a-digest"
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_unbounded_bindings_are_rejected(self):
        payload = _built()
        payload["delivery_bindings"] = [dict(payload["delivery_bindings"][0]) for _ in range(MAX_DELIVERY_BINDINGS + 1)]
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_unbounded_image_candidates_are_rejected(self):
        payload = _built()
        entry = payload["image_candidates"]["gce:kali"][0]
        payload["image_candidates"]["gce:kali"] = [dict(entry) for _ in range(MAX_IMAGE_CANDIDATES + 1)]
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_registry_metadata_on_a_candidate_is_rejected(self):
        # No primary keys, enabled flags, notes, or timestamps cross the wire.
        payload = _built()
        payload["image_candidates"]["gce:kali"][0]["id"] = 12
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_malformed_candidate_key_is_rejected(self):
        payload = _built()
        payload["image_candidates"]["no-separator"] = payload["image_candidates"].pop("gce:kali")
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)

    def test_non_mapping_payload_is_rejected(self):
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(["not", "a", "mapping"])

    def test_legacy_range_id_must_be_a_positive_int(self):
        with pytest.raises(RaesOperationInputError):
            _built(legacy_range_id=0)
        with pytest.raises(RaesOperationInputError):
            _built(legacy_range_id=True)


class TestEgressMode:
    """Pinned effective egress posture rides the operation input (PLAT-238, ADR-017-R5)."""

    def test_round_trips_the_pinned_mode(self):
        parsed = parse_raes_operation_input(_built(egress_mode="none"))
        assert parsed.egress_mode == "none"

    def test_default_when_builder_omits_the_mode(self):
        # The builder default is the compatibility posture.
        parsed = parse_raes_operation_input(_built())
        assert parsed.egress_mode == "status-quo"

    def test_absent_key_resolves_to_status_quo_not_an_error(self):
        # An older queued input minted before this deploy carries no key; absence
        # is the pre-feature behaviour (inherit baseline), never a silent weakening.
        payload = _built(egress_mode="none")
        del payload["egress_mode"]
        parsed = parse_raes_operation_input(payload)
        assert parsed.egress_mode == "status-quo"

    def test_unknown_mode_fails_closed_at_the_wire(self):
        payload = _built()
        payload["egress_mode"] = "wide-open"
        with pytest.raises(RaesOperationInputError):
            parse_raes_operation_input(payload)
