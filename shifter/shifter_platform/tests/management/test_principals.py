"""Durable human and service identity invariants (ADR-066)."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction

from management.models import Principal, ProviderBinding
from management.services import (
    PrincipalConflictError,
    bind_principal_provider_identity,
    create_service_principal,
    ensure_human_principal,
    principal_for_user,
    set_service_contact,
)
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog

pytestmark = pytest.mark.django_db
User = get_user_model()


def _user(name):
    return User.objects.create_user(username=name)


def test_one_django_user_keeps_one_human_principal_across_resolutions():
    user = _user("one-human")
    first = ensure_human_principal(user)
    second = ensure_human_principal(user)
    assert first == second == principal_for_user(user)
    assert Principal.objects.filter(user=user, kind="human").count() == 1


def test_email_free_temporary_user_needs_no_provider_binding():
    user = _user("temporary")
    user.email = ""
    user.save(update_fields=["email"])
    principal = ensure_human_principal(user)
    assert principal.kind == "human"
    assert not ProviderBinding.objects.filter(principal__uuid=principal.uuid).exists()


def test_service_identity_survives_creator_and_contact_changes():
    creator, contact = _user("creator"), _user("contact")
    service = create_service_principal("Automation", created_by=creator, responsible_user=contact)
    assert service.kind == "service"
    stored = Principal.objects.get(uuid=service.uuid)
    assert stored.user_id is None
    assert stored.created_by_id == creator.id
    from management.services import mark_user_deleted

    mark_user_deleted(creator)
    mark_user_deleted(contact)
    stored.refresh_from_db()
    assert stored.uuid == service.uuid
    assert stored.created_by_id == creator.pk
    assert Principal.objects.filter(user=creator).exists()
    assert Principal.objects.filter(user=contact).exists()
    assert stored.responsible_user_id == contact.pk
    assert stored.is_active is True
    set_service_contact(service, None)
    stored.refresh_from_db()
    assert stored.responsible_user_id is None
    assert stored.is_active is True


def test_provider_binding_is_exact_unique_and_immutable():
    first = ensure_human_principal(_user("first"))
    second = ensure_human_principal(_user("second"))
    bind_principal_provider_identity(first, "https://issuer.example", "subject")
    bind_principal_provider_identity(first, "https://issuer.example", "subject")
    assert ProviderBinding.objects.count() == 1
    with pytest.raises(PrincipalConflictError):
        bind_principal_provider_identity(second, "https://issuer.example", "subject")
    bind_principal_provider_identity(second, "https://other.example", "subject")
    assert ProviderBinding.objects.count() == 2
    binding = ProviderBinding.objects.get(principal__uuid=first.uuid)
    binding.subject = "new-subject"
    with pytest.raises(PrincipalConflictError):
        binding.save()


def test_database_blocks_bulk_rebinding_and_deletion():
    principal = ensure_human_principal(_user("database-binding"))
    bind_principal_provider_identity(principal, "issuer", "subject")
    binding = ProviderBinding.objects.get(principal__uuid=principal.uuid)
    with pytest.raises(DatabaseError), transaction.atomic():
        ProviderBinding.objects.filter(pk=binding.pk).update(subject="replacement")
    with pytest.raises(DatabaseError), transaction.atomic():
        ProviderBinding.objects.filter(pk=binding.pk).delete()
    assert ProviderBinding.objects.get(pk=binding.pk).subject == "subject"


def test_subject_only_and_blank_provider_identity_cannot_bind():
    principal = ensure_human_principal(_user("third"))
    for issuer, subject in (("", "subject"), ("issuer", ""), (" ", "subject")):
        with pytest.raises(PrincipalConflictError):
            bind_principal_provider_identity(principal, issuer, subject)


def test_database_enforces_human_service_shape_and_unique_user():
    user = _user("shape")
    ensure_human_principal(user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Principal.objects.create(kind="human", user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Principal.objects.create(kind="service", user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Principal.objects.create(kind="human")


def test_unknown_or_wrong_kind_principal_cannot_be_used_as_human():
    with pytest.raises(PrincipalConflictError):
        bind_principal_provider_identity(PrincipalRef(uuid=uuid4(), kind="human"), "issuer", "subject")
    with pytest.raises(PrincipalConflictError):
        set_service_contact(ensure_human_principal(_user("human")), None)


def test_service_and_provider_binding_mutations_are_audited_without_provider_tuple():
    service = create_service_principal("A private agent")
    bind_principal_provider_identity(service, "sensitive-issuer", "sensitive-subject")
    assert AuditLog.objects.filter(entity_type="principal", action="create").exists()
    binding_event = AuditLog.objects.get(entity_type="provider_binding", action="create")
    assert "sensitive-issuer" not in str(binding_event.new_state)
    assert "sensitive-subject" not in str(binding_event.new_state)
