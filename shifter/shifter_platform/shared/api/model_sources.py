"""Closed source-choice fields shared by tenant launch and event APIs."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from shared.model_access.sources import ModelSourceSelection


class ModelSourceRevisionField(serializers.IntegerField):
    """CAS revisions are JSON integers; boolean/string coercion is not intent."""

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            raise serializers.ValidationError("Use the current integer revision.")
        return super().to_internal_value(data)


class SourceChoiceSerializer(serializers.Serializer):
    """Immutable source revision and its allocation weight."""

    source_id = serializers.UUIDField()
    revision = serializers.IntegerField(min_value=1)
    weight = serializers.IntegerField(min_value=1, max_value=64, default=1)


class AliasSourceSelectionSerializer(serializers.Serializer):
    """Chosen source revisions for a logical model alias."""

    logical_alias = serializers.CharField()
    sources = SourceChoiceSerializer(many=True)


class ModelSourceSelectionSerializer(serializers.Serializer):
    """Explicit source choices grouped by logical alias."""

    aliases = AliasSourceSelectionSerializer(many=True)


@extend_schema_field(ModelSourceSelectionSerializer)
class ModelSourceSelectionField(serializers.JSONField):
    """Accept only revision-pinned logical-alias choices, never credentials."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        value = super().to_internal_value(data)
        try:
            return ModelSourceSelection.model_validate(value).model_dump(mode="json")
        except ValueError:
            raise serializers.ValidationError("Select valid model sources and current revisions.") from None

    def to_representation(self, value: object) -> dict[str, object]:
        return ModelSourceSelection.model_validate(value or {}).model_dump(mode="json")
