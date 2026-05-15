"""Set up a CTFEvent + CTFParticipant for a POLARIS smoke test.

Creates an ACTIVE CTFEvent owned by a named superuser for scenario
`polaris_manual_test`, then invites a single participant via the real
ctf.services.participant.invite_participant service so the Django user
and the magic link token are generated exactly as they would be for a
real CTF cohort. Emits JSON on stdout with the IDs + token the caller
needs to wire the range and build the magic link URL.

Run inside the portal Docker container:

    docker exec -i portal python - < polaris_ctf_setup.py

Environment variables (all optional, sensible defaults):

    POLARIS_CTF_EVENT_NAME      Display name for the event
    POLARIS_CTF_SCENARIO_ID     Scenario id stored on the event
    POLARIS_CTF_ADMIN_EMAIL     Username of the superuser who owns it
    POLARIS_CTF_PARTICIPANT_EMAIL
    POLARIS_CTF_PARTICIPANT_NAME
"""

import json
import os
from datetime import datetime, timedelta, timezone

import boto3

_sm = boto3.client(
    "secretsmanager",
    region_name=os.environ.get("AWS_REGION", "us-east-2"),
)
_db_secret = json.loads(
    _sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"]
)
_app_secret = json.loads(
    _sm.get_secret_value(SecretId=os.environ["APP_SECRET_ARN"])["SecretString"]
)
_cognito_arn = os.environ.get("COGNITO_SECRET_ARN")
if _cognito_arn:
    _cognito_secret = json.loads(
        _sm.get_secret_value(SecretId=_cognito_arn)["SecretString"]
    )
    os.environ["OIDC_RP_CLIENT_ID"] = _cognito_secret["client_id"]
    os.environ["OIDC_RP_CLIENT_SECRET"] = _cognito_secret["client_secret"]
    os.environ["OIDC_ISSUER_URL"] = _cognito_secret["issuer_url"]
    os.environ["OIDC_AUTH_DOMAIN"] = _cognito_secret["domain"]
else:
    os.environ.setdefault("OIDC_RP_CLIENT_ID", "dummy")
os.environ.setdefault("DB_HOST", _db_secret["host"])
os.environ.setdefault("DB_PORT", str(_db_secret["port"]))
os.environ["DB_NAME"] = _db_secret["dbname"]
os.environ["DB_USER"] = _db_secret["username"]
os.environ["DB_PASSWORD"] = _db_secret["password"]
os.environ["DJANGO_SECRET_KEY"] = _app_secret["django_secret_key"]
_fek = _app_secret["field_encryption_key"]
os.environ["FIELD_ENCRYPTION_KEY"] = _fek + "=" * ((4 - len(_fek) % 4) % 4)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from ctf.enums import EventStatus  # noqa: E402
from ctf.models import CTFEvent  # noqa: E402
from ctf.services.participant import invite_participant  # noqa: E402

EVENT_NAME = os.environ.get("POLARIS_CTF_EVENT_NAME", "POLARIS Cold-Rebuild Smoke")
SCENARIO_ID = os.environ.get("POLARIS_CTF_SCENARIO_ID", "polaris_manual_test")
ADMIN_EMAIL = os.environ.get(
    "POLARIS_CTF_ADMIN_EMAIL", "admin@example.com"
)
PARTICIPANT_EMAIL = os.environ.get(
    "POLARIS_CTF_PARTICIPANT_EMAIL", "polaris-smoke-01@example.com"
)
PARTICIPANT_NAME = os.environ.get(
    "POLARIS_CTF_PARTICIPANT_NAME", "Polaris Smoke Test"
)

User = get_user_model()

admin = User.objects.filter(username=ADMIN_EMAIL, is_superuser=True).first()
if admin is None:
    raise SystemExit(
        f"Superuser with username={ADMIN_EMAIL} not found in the portal DB"
    )

now = datetime.now(tz=timezone.utc)
event = CTFEvent.objects.create(
    name=EVENT_NAME,
    created_by=admin,
    event_start=now,
    event_end=now + timedelta(days=7),
    scenario_id=SCENARIO_ID,
    status=EventStatus.ACTIVE.value,
)
print(f"event: id={event.id} name={event.name} scenario={event.scenario_id}")

participant = invite_participant(
    event_id=event.id,
    email=PARTICIPANT_EMAIL,
    name=PARTICIPANT_NAME,
)
print(
    f"participant: id={participant.id} email={participant.email} "
    f"status={participant.status} user_id={participant.user_id}"
)
print(
    f"invite_token: {participant.invite_token} "
    f"(expires {participant.invite_token_expires.isoformat()})"
)

print(
    json.dumps(
        {
            "event_id": str(event.id),
            "participant_id": str(participant.id),
            "participant_user_id": participant.user_id,
            "participant_email": participant.email,
            "invite_token": participant.invite_token,
            "invite_token_expires": participant.invite_token_expires.isoformat(),
        }
    )
)
