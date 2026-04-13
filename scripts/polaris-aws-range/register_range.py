"""Manually register a POLARIS test range in the shifter CMS + engine DBs.

Runs inside the portal Docker container via:
  docker exec -i portal python - < register_range.py

Creates:
- Django user (standard) with the provided email
- cms.Request + cms.RangeInstance (status=ready)
- engine.Request + engine.Range (status=ready, provisioned_instances set)

Both records reference ONE attacker/kali instance pointing at the POLARIS
EC2 VM's private IP. The Kali SSH key lives in Secrets Manager; the ARN is
stored on the instance dict so engine.services.connect_terminal() and
engine.services.get_rdp_connection_info() can use it.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Fetch Django secrets from AWS Secrets Manager (mirror entrypoint.sh) before
# importing Django so settings.py doesn't raise on startup.
import boto3  # noqa: E402

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

from cms.models import RangeInstance  # noqa: E402
from cms.models import Request as CMSRequest  # noqa: E402
from engine.models import Range  # noqa: E402
from engine.models import Request as EngineRequest  # noqa: E402

# ---- Parameters (env-var overridable so cold-rebuild cycles don't need ------
# ---- a source edit to pick up new EC2 instance ids) -------------------------
USER_EMAIL = os.environ.get("POLARIS_USER_EMAIL", "dev@example.com")
SCENARIO_ID = os.environ.get("POLARIS_SCENARIO_ID", "polaris_manual_test")
RANGE_NAME = os.environ.get("POLARIS_RANGE_NAME", "polaris-test-range")
SUBNET_ID = os.environ.get("POLARIS_SUBNET_ID", "subnet-028b195e8d6f4f8a6")
SUBNET_CIDR = os.environ.get("POLARIS_SUBNET_CIDR", "10.1.100.0/28")
SUBNET_INDEX = int(os.environ.get("POLARIS_SUBNET_INDEX", "4000"))
KALI_INSTANCE_ID = os.environ.get("POLARIS_KALI_INSTANCE_ID", "i-0ca464adb68caf8c5")
KALI_PRIVATE_IP = os.environ.get("POLARIS_KALI_PRIVATE_IP", "10.1.100.10")
KALI_SSH_KEY_SECRET_ARN = os.environ.get(
    "POLARIS_KALI_SSH_KEY_SECRET_ARN",
    "arn:aws:secretsmanager:us-east-2:158151907940:"
    "secret:shifter/development/range/polaris-test-kali-58eP7L",
)
# -----------------------------------------------------------------------------

User = get_user_model()

# 1. Ensure user exists (matches what dev_login does for POSTed email)
user, created = User.objects.get_or_create(
    username=USER_EMAIL,
    defaults={"email": USER_EMAIL, "is_active": True},
)
print(f"user: {user.username} id={user.id} created={created}")

# Clean up any stale active ranges for this user so dev-login flow is deterministic
stale = Range.objects.filter(user=user).exclude(
    status__in=[Range.Status.DESTROYED, Range.Status.FAILED]
)
for r in stale:
    print(f"  soft-destroying stale Range id={r.id} status={r.status}")
    r.status = Range.Status.DESTROYED
    r.destroyed_at = datetime.now(tz=timezone.utc)
    r.save(update_fields=["status", "destroyed_at", "updated_at"])

stale_cms = RangeInstance.active.filter(user_id=user.id)
for ri in stale_cms:
    print(
        f"  soft-destroying stale RangeInstance id={ri.id} status={ri.status}"
    )
    ri.status = "destroyed"
    ri.save()

# 2. Build one attacker instance dict matching what the provisioner would
#    normally produce.
attacker_uuid = str(uuid.uuid4())
attacker_instance = {
    "uuid": attacker_uuid,
    "name": "kali",
    "role": "attacker",
    "os_type": "kali",
    "private_ip": KALI_PRIVATE_IP,
    "instance_id": KALI_INSTANCE_ID,
    "ssh_key_secret_arn": KALI_SSH_KEY_SECRET_ARN,
    "subnet_name": "polaris",
}

# 3. Create engine Request + Range
engine_request = EngineRequest.objects.create(
    request_id=uuid.uuid4(),
    request_type="range",
    user=user,
)
print(f"engine.Request: request_id={engine_request.request_id}")

range_spec = {
    "scenario_id": SCENARIO_ID,
    "user_id": user.id,
    "name": RANGE_NAME,
    "range_type": "demo",
    "ngfw": False,
    "subnets": [
        {
            "name": "polaris",
            "uuid": str(uuid.uuid4()),
            "cidr": SUBNET_CIDR,
            "connected_to": [],
            "instances": [attacker_instance],
        }
    ],
}

range_obj = Range.objects.create(
    user=user,
    request=engine_request,
    cms_user_id=user.id,
    status=Range.Status.READY,
    subnet_id=SUBNET_ID,
    subnet_cidr=SUBNET_CIDR,
    subnet_index=SUBNET_INDEX,
    kali_ip=KALI_PRIVATE_IP,
    kali_instance_id=KALI_INSTANCE_ID,
    kali_ssh_key_secret_arn=KALI_SSH_KEY_SECRET_ARN,
    range_config=range_spec,
    provisioned_instances=[attacker_instance],
    provisioner_version="manual",
    ready_at=datetime.now(tz=timezone.utc),
)
print(f"engine.Range: id={range_obj.id} status={range_obj.status}")

# 4. Create CMS Request + RangeInstance (uses the same request_id so the
#    two sides correlate)
cms_request = CMSRequest.objects.create(
    request_id=engine_request.request_id,
    user=user,
    request_type="range",
)
print(f"cms.Request: id={cms_request.id} request_id={cms_request.request_id}")

cms_range_instance = RangeInstance.objects.create(
    request=cms_request,
    range_id=range_obj.id,
    scenario_id=SCENARIO_ID,
    user_id=user.id,
    status="ready",
    range_spec=range_spec,
)
print(
    f"cms.RangeInstance: id={cms_range_instance.id} "
    f"range_id={cms_range_instance.range_id}"
)

print("\nSUMMARY")
print(f"  User: {user.email} (id={user.id})")
print(f"  Engine Range id: {range_obj.id}")
print(f"  CMS RangeInstance id: {cms_range_instance.id}")
print(f"  Attacker instance uuid: {attacker_uuid}")
print(f"  Kali private IP: {KALI_PRIVATE_IP}")
print(f"  SSH key secret ARN: {KALI_SSH_KEY_SECRET_ARN}")
print(json.dumps({"attacker_uuid": attacker_uuid, "range_id": range_obj.id}))
