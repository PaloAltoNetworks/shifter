"""Hard-delete the POLARIS smoke-test CTFEvent + participant + user.

Removes the CTFParticipant identified by POLARIS_CTF_PARTICIPANT_ID, the
Django User that auto-registration created for it, and the parent
CTFEvent identified by POLARIS_CTF_EVENT_ID. Also soft-destroys the
engine.Range + cms.RangeInstance rows that were tied to the participant
so the dashboard won't keep showing a stale entry if the Django user is
ever recreated with the same email.

Hard-delete (not soft) because the whole point of running this is to
leave no trace of the smoke test behind.

Run inside the portal Docker container:

    docker exec -i \
        -e POLARIS_CTF_EVENT_ID=<uuid> \
        -e POLARIS_CTF_PARTICIPANT_ID=<uuid> \
        portal python - < polaris_ctf_cleanup.py
"""

import json
import os
from datetime import datetime, timezone

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
from django.db import transaction  # noqa: E402

from cms.models import RangeInstance  # noqa: E402
from ctf.models import CTFEvent, CTFParticipant  # noqa: E402
from engine.models import Range  # noqa: E402

EVENT_ID = os.environ["POLARIS_CTF_EVENT_ID"]
PARTICIPANT_ID = os.environ["POLARIS_CTF_PARTICIPANT_ID"]

User = get_user_model()

with transaction.atomic():
    participant = CTFParticipant.all_objects.filter(pk=PARTICIPANT_ID).first()
    if participant is None:
        print(f"participant {PARTICIPANT_ID} already gone")
    else:
        user_id = participant.user_id
        email = participant.email

        # Soft-destroy the engine.Range + cms.RangeInstance rows owned by
        # this participant's user so the dashboard stops showing them.
        if user_id is not None:
            stale_engine = Range.objects.filter(user_id=user_id).exclude(
                status__in=[Range.Status.DESTROYED, Range.Status.FAILED]
            )
            for r in stale_engine:
                r.status = Range.Status.DESTROYED
                r.destroyed_at = datetime.now(tz=timezone.utc)
                r.save(update_fields=["status", "destroyed_at", "updated_at"])
                print(f"soft-destroyed engine.Range id={r.id}")

            stale_cms = RangeInstance.objects.filter(user_id=user_id)
            for ri in stale_cms:
                ri.status = "destroyed"
                ri.save()
                print(f"soft-destroyed cms.RangeInstance id={ri.id}")

        participant.delete(soft=False)
        print(f"hard-deleted participant {PARTICIPANT_ID} ({email})")

        if user_id is not None:
            User.objects.filter(pk=user_id).delete()
            print(f"hard-deleted user id={user_id} ({email})")

    event = CTFEvent.all_objects.filter(pk=EVENT_ID).first()
    if event is None:
        print(f"event {EVENT_ID} already gone")
    else:
        event.delete(soft=False)
        print(f"hard-deleted event {EVENT_ID}")

print("cleanup complete")
