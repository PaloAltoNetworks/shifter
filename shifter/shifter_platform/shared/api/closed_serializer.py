"""Closed write contracts reject ignored authority or transport fields."""

from rest_framework import serializers


class ClosedSerializer(serializers.Serializer):
    """Reject unrecognized write fields before ordinary field validation."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown field."]})
        return super().to_internal_value(data)
