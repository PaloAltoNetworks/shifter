"""Serializers for the Mission Control agent-upload DRF endpoints.

Split out of ``serializers.py`` to keep that module under the per-file size
limit. ``AGENT_TYPE_CHOICES`` stays canonical in ``serializers`` (the agent-list
serializer also uses it) and is imported here.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from mission_control.api.serializers import AGENT_TYPE_CHOICES


class UploadInitiateSerializer(serializers.Serializer):
    """Validate agent-upload initiation requests."""

    name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    filename = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    file_size = serializers.JSONField(required=False)
    agent_type = serializers.CharField(required=False, allow_blank=True, default="xdr", trim_whitespace=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        name = attrs.get("name", "")
        filename = attrs.get("filename", "")
        file_size = attrs.get("file_size", 0)
        agent_type = attrs.get("agent_type", "xdr") or "xdr"

        if not name:
            raise serializers.ValidationError("Agent name is required")
        if not filename:
            raise serializers.ValidationError("Filename is required")
        # ``file_size`` is a raw ``JSONField``; reject any non-positive-int JSON
        # value. ``bool`` is a subclass of ``int`` in Python, so guard it first
        # or ``true`` would be admitted as one byte.
        if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size <= 0:
            raise serializers.ValidationError("Valid file size is required")
        if agent_type not in AGENT_TYPE_CHOICES:
            raise serializers.ValidationError("Invalid agent type.")

        attrs["agent_type"] = agent_type
        return attrs


class UploadCompleteSerializer(serializers.Serializer):
    """Validate agent-upload completion requests."""

    upload_token = serializers.CharField(allow_blank=True, required=False, default="")


class UploadCancelSerializer(serializers.Serializer):
    """Validate agent-upload cancel requests."""

    upload_token = serializers.CharField(allow_blank=False, required=True, trim_whitespace=True)


class UploadInitiateResponseSerializer(serializers.Serializer):
    """Response body for ``UploadInitiateView.post`` (``cms.services.initiate_upload``).

    ``presigned_url`` is a short-lived, single-use S3 PUT URL — an existing
    response field, typed here for the schema but never given a real example.
    """

    presigned_url = serializers.CharField()
    s3_key = serializers.CharField()
    upload_token = serializers.CharField()
    expected_os = serializers.CharField(allow_null=True)


class UploadCompleteResponseSerializer(serializers.Serializer):
    """Response body for ``UploadCompleteView.post``."""

    success = serializers.BooleanField()
    agent_id = serializers.IntegerField()
    message = serializers.CharField()
