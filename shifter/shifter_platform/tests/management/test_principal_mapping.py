"""One-time user and verified provider mapping on the real schema."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model

from management.models import Principal, ProviderBinding, UserProfile

pytestmark = pytest.mark.django_db
User = get_user_model()
_mapping = importlib.import_module("management.migrations.0015_map_human_principals")


def test_complete_provider_tuple_maps_once_by_user_id():
    user = User.objects.create_user(username="provider-mapping", email="")
    UserProfile.objects.filter(user=user).update(issuer="issuer-a", cognito_sub="subject-a")

    _mapping.map_human_principals(apps, None)
    _mapping.map_human_principals(apps, None)

    principal = Principal.objects.get(user=user)
    assert principal.kind == "human"
    assert ProviderBinding.objects.get(issuer="issuer-a", subject="subject-a").principal_id == principal.pk
    assert Principal.objects.filter(user=user).count() == 1


def test_email_free_temporary_user_maps_without_fabricated_binding():
    user = User.objects.create_user(username="temporary-mapping", email="")
    UserProfile.objects.filter(user=user).update(is_ctf_account=True, user_type="ctf_participant")

    _mapping.map_human_principals(apps, None)

    assert Principal.objects.get(user=user).kind == "human"
    assert not ProviderBinding.objects.filter(principal__user=user).exists()


def test_subject_only_legacy_row_maps_human_but_remains_unbound_for_s8():
    good = User.objects.create_user(username="good-mapping")
    bad = User.objects.create_user(username="subject-only-mapping")
    UserProfile.objects.filter(user=bad).update(cognito_sub="subject-without-issuer")

    _mapping.map_human_principals(apps, None)

    assert Principal.objects.filter(user__in=(good, bad), kind="human").count() == 2
    assert not ProviderBinding.objects.filter(principal__user=bad).exists()
    assert UserProfile.objects.get(user=bad).cognito_sub == "subject-without-issuer"
