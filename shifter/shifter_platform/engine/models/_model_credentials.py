"""Hashed range credentials; raw tokens exist only during trusted delivery."""

from django.db import models


class ModelAccessCredential(models.Model):
    """One rotating credential family bound to the existing allocation grant."""

    grant = models.OneToOneField("engine.ModelPendingGrant", on_delete=models.PROTECT)
    grant_epoch = models.PositiveBigIntegerField()
    replacement_grant = models.ForeignKey(
        "engine.ModelPendingGrant", on_delete=models.PROTECT, null=True, related_name="predecessor_credentials"
    )
    admitted_subnets = models.JSONField()
    enrollment_hash = models.CharField(max_length=64, blank=True, default="")
    enrollment_expires_at = models.DateTimeField()
    access_hash = models.CharField(max_length=64, blank=True, default="")
    access_expires_at = models.DateTimeField(null=True)
    refresh_hash = models.CharField(max_length=64, blank=True, default="")
    hard_expires_at = models.DateTimeField()
    rotation_window_started_at = models.DateTimeField(null=True)
    rotation_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return str(self.grant_id)
