"""Attach a freshly-registered RangeInstance to a CTFParticipant.

Reads `POLARIS_CTF_PARTICIPANT_ID` and `POLARIS_CMS_RANGE_INSTANCE_ID`
from the environment, sets the participant's `range_instance_id`,
`range_status`, and `status` so the mission-control dashboard shows
the range and the context processor filters instances to the Kali box.

Run inside the portal Docker container:

    docker exec -i -e POLARIS_CTF_PARTICIPANT_ID=... \
                  -e POLARIS_CMS_RANGE_INSTANCE_ID=... \
                  portal python - < polaris_ctf_attach.py
"""

import json
import os

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

from ctf.enums import ParticipantStatus  # noqa: E402
from ctf.models import CTFParticipant  # noqa: E402

PARTICIPANT_ID = os.environ["POLARIS_CTF_PARTICIPANT_ID"]
RANGE_INSTANCE_ID = int(os.environ["POLARIS_CMS_RANGE_INSTANCE_ID"])

participant = CTFParticipant.objects.get(pk=PARTICIPANT_ID)
participant.range_instance_id = RANGE_INSTANCE_ID
participant.range_status = "ready"
participant.status = ParticipantStatus.ACTIVE.value
participant.save(
    update_fields=[
        "range_instance_id",
        "range_status",
        "status",
        "updated_at",
    ]
)
print(
    f"attached: participant={participant.id} "
    f"range_instance_id={participant.range_instance_id} "
    f"status={participant.status}"
)
