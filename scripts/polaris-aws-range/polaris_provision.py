"""Trigger a real polaris range provisioning via cms.services.create_range.

Runs inside the portal Docker container via:
    docker exec -i portal python - < polaris_provision.py

This is the cyberscript-pivoted path: instead of manually inserting
DB rows like register_range.py did, we call the production
`cms.services.create_range(user, "polaris", {}, False)` which:

1. Validates the polaris scenario template via the cms scenario registry
2. Hydrates it into a RangeSpec via cms.scenarios.hydrator
3. Calls engine.services.create_range(request_spec)
4. engine.services.create_range creates Range + Subnets DB rows
5. engine.ecs.start_range_provisioning fires an ECS Fargate task on
   the dev-portal-pulumi-provisioner family using the latest
   registered task definition revision (which we just bumped to
   point at the rebuilt provisioner image carrying our
   PolarisRangeBootstrapPlan + per-instance instance_type override)
6. The provisioner reads the request, runs terraform against the
   existing range module (per-subnet SG + ngfw-skipped), waits for
   the polaris VM and the A2 DC to come up, runs DCSetupPlan against
   the DC, runs LinuxBootstrapPlan + PolarisRangeBootstrapPlan
   against the polaris VM
7. Status flips to READY in the DB

The test user (default polaris-cyber-test@example.com) gets a fresh
Django user (created if missing) and any existing active range is
soft-destroyed first so this script is re-runnable end-to-end.
"""

import json
import os
import sys

import boto3

_sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-2"))
_db_secret = json.loads(_sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
_app_secret = json.loads(_sm.get_secret_value(SecretId=os.environ["APP_SECRET_ARN"])["SecretString"])
_cognito_arn = os.environ.get("COGNITO_SECRET_ARN")
if _cognito_arn:
    _cognito_secret = json.loads(_sm.get_secret_value(SecretId=_cognito_arn)["SecretString"])
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

from datetime import datetime, timezone  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402

import cms.services as cms_services  # noqa: E402
from cms.models import RangeInstance  # noqa: E402
from cms.scenarios.loader import list_scenario_ids  # noqa: E402
from cms.scenarios.registry import load_scenario_template  # noqa: E402
from engine.models import Range  # noqa: E402

USER_EMAIL = os.environ.get("POLARIS_USER_EMAIL", "polaris-cyber-test@example.com")
SCENARIO_ID = os.environ.get("POLARIS_SCENARIO_ID", "polaris")

User = get_user_model()

print("=" * 60)
print("polaris_provision: scenario discovery")
print("=" * 60)
print("available scenarios:", sorted(list_scenario_ids()))

template = load_scenario_template(SCENARIO_ID)
print(f"loaded {SCENARIO_ID}: id={template.id} name={template.name} ngfw={template.ngfw}")
for inst in template.instances:
    print(
        f"  instance: name={inst.name} role={inst.role} os_type={inst.os_type} "
        f"ami_key={inst.ami_key} instance_type={inst.instance_type} "
        f"domain_controller={inst.domain_controller}"
    )

print("=" * 60)
print(f"polaris_provision: ensure test user {USER_EMAIL!r}")
print("=" * 60)
user, created = User.objects.get_or_create(
    username=USER_EMAIL,
    defaults={"email": USER_EMAIL, "is_active": True},
)
print(f"  user id={user.id} created={created}")

# Soft-destroy any existing active ranges for this user so we have a
# clean slate (cms.services.create_range refuses to create a second
# active range for the same user).
stale_engine = Range.objects.filter(user=user).exclude(
    status__in=[Range.Status.DESTROYED, Range.Status.FAILED]
)
for r in stale_engine:
    print(f"  soft-destroying stale engine.Range id={r.id} status={r.status}")
    r.status = Range.Status.DESTROYED
    r.destroyed_at = datetime.now(tz=timezone.utc)
    r.save(update_fields=["status", "destroyed_at", "updated_at"])

stale_cms = RangeInstance.objects.filter(user_id=user.id)
for ri in stale_cms:
    print(f"  soft-destroying stale cms.RangeInstance id={ri.id} status={ri.status}")
    ri.status = "destroyed"
    ri.save()

print("=" * 60)
print(f"polaris_provision: cms.services.create_range(user, {SCENARIO_ID!r}, {{}}, False)")
print("=" * 60)
try:
    result = cms_services.create_range(
        user=user,
        scenario=SCENARIO_ID,
        agents_by_os={},
        ngfw_enabled=False,
    )
except Exception as exc:
    print(f"  FAILED: {type(exc).__name__}: {exc}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"  request_id={result.request_id}")
print(f"  scenario_id={result.scenario_id}")
print(f"  status={result.status}")
print(f"  instances={[(i.name, i.role, i.os_type) for i in result.instances]}")

print()
print(json.dumps(
    {
        "request_id": str(result.request_id),
        "user_id": user.id,
        "user_email": user.email,
        "scenario_id": SCENARIO_ID,
        "instances": [
            {"name": i.name, "role": i.role, "os_type": i.os_type}
            for i in result.instances
        ],
    }
))
