"""Publish the same closed variants enforced by the communication validators."""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any, Literal

from drf_spectacular.plumbing import force_instance

from ctf.api.serializers.communication import CommunicationAudienceSerializer, CommunicationTriggerSerializer
from ctf.communication_contracts import AUDIENCE_ID_FIELDS, TRIGGER_FIELDS
from shared.api.closed_serializer import ClosedSerializer
from shared.api.schema import ApiErrorSerializer, PlatformAutoSchema


class CommunicationSchema(PlatformAutoSchema):
    """Keep bounds/fields serializer-derived and alternatives domain-derived."""

    def _map_serializer(
        self, serializer: Any, direction: Literal["request", "response"], bypass_extensions: bool = False
    ) -> dict[str, Any]:
        instance = force_instance(serializer)
        schema = super()._map_serializer(instance, direction, bypass_extensions)
        if isinstance(instance, ClosedSerializer):
            schema["additionalProperties"] = False
        variants: Mapping[str, Set[str]] | None = None
        if isinstance(instance, CommunicationAudienceSerializer):
            variants = {kind: {field} for kind, field in AUDIENCE_ID_FIELDS.items()}
        elif isinstance(instance, CommunicationTriggerSerializer):
            variants = TRIGGER_FIELDS
        if variants is not None:
            properties = schema["properties"]
            schema["oneOf"] = [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        # Keep the singleton inside allOf: enum extraction names
                        # all kind fields in this component alike, merging arms.
                        "kind": {"type": "string", "allOf": [{"enum": [kind]}]},
                        **{key: dict(properties[key]) for key in sorted(fields)},
                    },
                    "required": ["kind", *sorted(fields)],
                }
                for kind, fields in variants.items()
            ]
            if isinstance(instance, CommunicationAudienceSerializer):
                for kind, arm in zip(variants, schema["oneOf"], strict=True):
                    ids = arm["properties"][AUDIENCE_ID_FIELDS[kind]]
                    if kind in {"participant", "event"}:
                        ids.update(minItems=1, maxItems=1)
                    elif kind == "multi_event":
                        ids["minItems"] = 2
        return schema

    def _add_error_responses(self, operation: dict[str, Any]) -> None:
        """All communication errors use the same authored platform envelope."""
        super()._add_error_responses(operation)
        error_ref = self.resolve_serializer(ApiErrorSerializer, "response").ref
        for code, description in {
            "400": "Invalid request",
            "404": "Resource not found",
            "409": "Request conflicts with current state",
            "429": "Request was throttled",
            "503": "Service unavailable",
        }.items():
            operation["responses"].setdefault(
                code, {"description": description, "content": {"application/json": {"schema": error_ref}}}
            )


class SessionCommunicationSchema(CommunicationSchema):
    """Retain only the registered cookie scheme for participant receipt APIs."""

    def get_auth(self) -> list[dict[str, Any]]:
        return [scheme for scheme in super().get_auth() if "cookieAuth" in scheme]
