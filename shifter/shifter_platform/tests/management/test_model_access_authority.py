"""Identity-owned model-access selector and spending authority."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from management import services

pytestmark = pytest.mark.django_db

User = get_user_model()


def _operator():
    return User.objects.create_superuser("operator@test", "operator@test", "unused")


def test_group_resolution_uses_primary_key_direct_membership_and_explicit_eligibility():
    operator = _operator()
    member = User.objects.create_user("member@test")
    inactive = User.objects.create_user("inactive@test", is_active=False)
    group = Group.objects.create(name="display-name-is-not-authority")
    group.user_set.add(member, inactive)

    unresolved = services.resolve_model_access_group(operator, group.pk)
    assert unresolved.group_id == group.pk
    assert unresolved.user_ids == (member.pk,)
    assert unresolved.eligibility_basis is None

    policy = services.set_model_access_group_eligibility(
        operator,
        group.pk,
        managed_membership=True,
        spending_approved=False,
        expected_revision=0,
    )
    assert policy.revision == 1
    resolved = services.resolve_model_access_group(operator, group.pk)
    assert resolved.eligibility_basis == "managed_membership"


def test_group_resolution_and_policy_are_operator_only_and_revision_fenced():
    operator = _operator()
    ordinary = User.objects.create_user("ordinary@test")
    group = Group.objects.create(name="researchers")

    with pytest.raises(services.ModelAccessIdentityAuthorityError):
        services.resolve_model_access_group(ordinary, group.pk)

    services.set_model_access_group_eligibility(
        operator,
        group.pk,
        managed_membership=False,
        spending_approved=True,
        expected_revision=0,
    )
    with pytest.raises(services.ModelAccessIdentityAuthorityError) as conflict:
        services.set_model_access_group_eligibility(
            operator,
            group.pk,
            managed_membership=True,
            spending_approved=True,
            expected_revision=0,
        )
    assert conflict.value.code == "identity.group_eligibility_revision_conflict"
