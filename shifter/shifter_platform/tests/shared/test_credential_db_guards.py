"""Database enforcement for immutable issued limits, including bulk writers."""

import pytest
from django.db import DatabaseError, transaction

from shared.api_tokens.models import ApiToken


@pytest.mark.django_db
def test_bulk_writer_cannot_expand_scope_or_unrevoke(django_user_model):
    from uuid import uuid4

    from shared.authorization import TargetRef

    user = django_user_model.objects.create_user(username="guarded-owner")
    token, _ = ApiToken.create_token(
        name="guarded", created_by=user, scopes=["ctf:event:read"], target=TargetRef("event", uuid4())
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        ApiToken.objects.filter(pk=token.pk).update(scopes=["ctf:event:write"])
    for update in ({"target_uuid": uuid4()}, {"target_type": "workspace"}):
        with pytest.raises(DatabaseError), transaction.atomic():
            ApiToken.objects.filter(pk=token.pk).update(**update)
    token.revoke()
    with pytest.raises(DatabaseError), transaction.atomic():
        ApiToken.objects.filter(pk=token.pk).update(revoked_at=None)


@pytest.mark.django_db
def test_service_admission_cannot_be_expanded_or_reactivated_by_bulk_writer():
    from management.models import ProviderBinding, ServiceCredentialAdmission
    from management.services import bind_principal_provider_identity, create_service_principal

    principal = create_service_principal("Immutable admission")
    bind_principal_provider_identity(principal, "https://accounts.google.com", "123456789012345678901")
    admission = ServiceCredentialAdmission.objects.create(
        binding=ProviderBinding.objects.get(principal__uuid=principal.uuid),
        audience="https://portal.example.test",
        scopes=["ctf:event:read"],
    )
    for update in ({"scopes": ["ctf:event:write"]}, {"audience": "https://other.example.test"}):
        with pytest.raises(DatabaseError), transaction.atomic():
            ServiceCredentialAdmission.objects.filter(pk=admission.pk).update(**update)
    admission.is_active = False
    admission.save(update_fields=["is_active"])
    with pytest.raises(DatabaseError), transaction.atomic():
        ServiceCredentialAdmission.objects.filter(pk=admission.pk).update(is_active=True)
