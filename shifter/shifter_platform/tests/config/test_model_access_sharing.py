"""Cross-domain named model-access selector composition."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from shared.model_access import (
    OwnedReference,
    SelectorKind,
    SelectorResolution,
    SharingSelector,
    compute_digest,
    seal_sharing_binding,
)


def _atom_resolution(selector, *, authority_owner, members):
    digest = compute_digest(selector)
    authority_ref = {"owner": authority_owner, "reference": f"scope:{selector.kind.value}"}
    return SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=len(members),
        member_refs=tuple({"owner": "deployment", "reference": member} for member in members),
        selector_authority_refs=(authority_ref,),
        subject_authorities=tuple(
            {
                "subject_ref": {"owner": "deployment", "reference": member},
                "authority_ref": authority_ref,
            }
            for member in members
        ),
        publisher_requirements=({"selector_digest": digest, "authority_ref": authority_ref, "scope": "selector"},),
    )


def test_named_collection_unions_members_and_retains_every_atomic_publisher_requirement(monkeypatch):
    from config.model_access_sharing import resolve_model_access_selector

    event_selector = SharingSelector(kind=SelectorKind.CTF_EVENT, ids=(str(uuid4()),))
    user_selector = SharingSelector(kind=SelectorKind.USER, ids=("7",))
    named = SharingSelector(
        kind=SelectorKind.NAMED_COLLECTION,
        members=(event_selector, user_selector),
    )

    def resolve_atom(actor, selector):
        if selector.kind is SelectorKind.CTF_EVENT:
            return _atom_resolution(
                selector,
                authority_owner="ctf",
                members=("range:shared", "range:event"),
            )
        return _atom_resolution(
            selector,
            authority_owner="management",
            members=("range:shared", "range:user"),
        )

    monkeypatch.setattr("config.model_access_sharing._resolve_atom", resolve_atom)

    resolution = resolve_model_access_selector(object(), named)

    assert resolution.selector_digest == compute_digest(named)
    assert {item.reference for item in resolution.member_refs} == {
        "range:shared",
        "range:event",
        "range:user",
    }
    assert {item.selector_digest for item in resolution.publisher_requirements} == {
        compute_digest(event_selector),
        compute_digest(user_selector),
    }
    assert {item.owner for item in resolution.selector_authority_refs} == {"ctf", "management"}


@pytest.mark.django_db
def test_publication_uses_server_derived_publisher_and_projected_membership_revision(monkeypatch):
    from config.model_access_sharing import publish_model_access_binding

    deployment_id = uuid4()
    selector = SharingSelector(kind=SelectorKind.ALL_RANGES)
    resolution = _atom_resolution(selector, authority_owner="management", members=("range:one",))
    binding = seal_sharing_binding(
        {
            "contract_version": "model-access-sharing/v1",
            "sharing_binding_id": "binding-one",
            "deployment_id": str(deployment_id),
            "selector": selector.model_dump(mode="json"),
            "membership_mode": "dynamic",
            "membership_revision": 1,
            "authorized_publisher_ref": {"owner": "forged", "reference": "forged:actor"},
            "sharing_pool_id": "pool-one",
            "facets": ["spend"],
            "effective_from": "2026-09-14T00:00:00Z",
            "effective_until": "2026-09-15T00:00:00Z",
        }
    )
    actor = SimpleNamespace(pk=17)
    published = {}
    monkeypatch.setattr(
        "config.model_access_sharing.resolve_model_access_selector",
        lambda actor, selector: resolution,
    )
    monkeypatch.setattr(
        "cms.services.engine_project_selector_resolution",
        lambda **kwargs: SimpleNamespace(membership_revision=7),
    )
    monkeypatch.setattr(
        "cms.services.engine_publish_sharing_binding",
        lambda **kwargs: published.update(kwargs) or "revision",
    )
    monkeypatch.setattr("management.services.is_platform_operator", lambda actor: False)

    result = publish_model_access_binding(
        actor=actor,
        deployment_id=deployment_id,
        catalog=object(),
        binding=binding,
        pool=object(),
        expected_definition_revision=0,
    )

    assert result == "revision"
    assert published["binding"].membership_revision == 7
    assert published["publisher_identity"] == OwnedReference(
        owner="management",
        reference="user:17",
    )


@pytest.mark.django_db(transaction=True)
def test_failed_publication_rolls_back_projection_and_authority_fences(monkeypatch):
    from config.model_access_sharing import publish_model_access_binding
    from engine.models import MembershipProjection, SharingAuthorityFence

    deployment_id = uuid4()
    selector = SharingSelector(kind=SelectorKind.USER, ids=("19",))
    resolution = _atom_resolution(selector, authority_owner="management", members=("range:one",))
    binding = seal_sharing_binding(
        {
            "contract_version": "model-access-sharing/v1",
            "sharing_binding_id": "rollback-binding",
            "deployment_id": str(deployment_id),
            "selector": selector.model_dump(mode="json"),
            "membership_mode": "dynamic",
            "membership_revision": 1,
            "authorized_publisher_ref": {"owner": "forged", "reference": "forged:actor"},
            "sharing_pool_id": "pool-one",
            "facets": ["spend"],
            "effective_from": "2026-09-14T00:00:00Z",
            "effective_until": "2026-09-15T00:00:00Z",
        }
    )
    monkeypatch.setattr(
        "config.model_access_sharing.resolve_model_access_selector",
        lambda actor, selector: resolution,
    )
    monkeypatch.setattr("management.services.is_platform_operator", lambda actor: False)

    def refuse_publish(**kwargs):
        raise RuntimeError("publication refused")

    monkeypatch.setattr("cms.services.engine_publish_sharing_binding", refuse_publish)

    with pytest.raises(RuntimeError, match="publication refused"):
        publish_model_access_binding(
            actor=SimpleNamespace(pk=19),
            deployment_id=deployment_id,
            catalog=object(),
            binding=binding,
            pool=object(),
            expected_definition_revision=0,
        )

    assert not MembershipProjection.objects.filter(deployment_id=deployment_id).exists()
    assert not SharingAuthorityFence.objects.filter(deployment_id=deployment_id).exists()
