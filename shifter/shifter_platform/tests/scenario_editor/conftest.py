"""Shared fixtures for scenario editor tests."""

import time

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from shared.auth import THREAT_RESEARCH_GROUP

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@example.com",
        email="staff@example.com",
        password="testpass",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="regular@example.com",
        email="regular@example.com",
        password="testpass",
        is_staff=False,
    )


@pytest.fixture
def threat_research_user(db):
    user = User.objects.create_user(
        username="threat@example.com",
        email="threat@example.com",
        password="testpass",
        is_staff=False,
    )
    group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def staff_client(staff_user):
    client = Client()
    client.force_login(staff_user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def regular_client(regular_user):
    client = Client()
    client.force_login(regular_user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def threat_research_client(threat_research_user):
    client = Client()
    client.force_login(threat_research_user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


@pytest.fixture
def valid_definition():
    return {
        "instances": [
            {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
            {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
        ],
        "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
        "ngfw": False,
    }
