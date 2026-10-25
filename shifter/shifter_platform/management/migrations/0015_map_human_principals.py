"""Map existing Django users to durable human principals (ADR-066, S1).

The migration never guesses an issuer for a subject-only legacy profile. It
maps every Django user to a human principal, binds only complete provider
tuples, and preserves incomplete or contradictory rows unchanged for explicit
S8 validation and the coordinated authority cutover.
"""

from django.db import migrations


def map_human_principals(apps, schema_editor):
    """Map by user primary key and complete provider tuple, without email matching."""
    user_model = apps.get_model("auth", "User")
    profile_model = apps.get_model("management", "UserProfile")
    principal_model = apps.get_model("management", "Principal")
    binding_model = apps.get_model("management", "ProviderBinding")

    for user_id in user_model.objects.order_by("pk").values_list("pk", flat=True).iterator():
        principal, _ = principal_model.objects.get_or_create(user_id=user_id, defaults={"kind": "human"})
        if principal.kind != "human":
            raise RuntimeError(f"identity mapping blocked user_id={user_id} reason=principal_kind_conflict")

    complete_profiles = (
        profile_model.objects.filter(is_ctf_account=False)
        .exclude(cognito_sub__isnull=True)
        .exclude(cognito_sub="")
        .exclude(issuer__isnull=True)
        .exclude(issuer="")
        .order_by("pk")
    )
    for profile in complete_profiles.iterator():
        if not profile.issuer.strip() or not profile.cognito_sub.strip():
            continue
        principal = principal_model.objects.get(user_id=profile.user_id)
        binding, _ = binding_model.objects.get_or_create(
            issuer=profile.issuer,
            subject=profile.cognito_sub,
            defaults={"principal_id": principal.pk},
        )
        if binding.principal_id != principal.pk:
            raise RuntimeError(f"identity mapping blocked profile_id={profile.pk} reason=provider_collision")


class Migration(migrations.Migration):
    dependencies = [("management", "0014_principal_providerbinding_and_more")]

    operations = [migrations.RunPython(map_human_principals, migrations.RunPython.noop)]
