"""DRF serializers for Risk Register API."""

from rest_framework import serializers

from risk_register.models import AuditLog, Comment, Risk, StrideCategory

# SonarCloud S1192: extracted duplicated string literals.
LIKELIHOOD_RANGE_MSG = "Likelihood score must be between 1 and 5"
IMPACT_RANGE_MSG = "Impact score must be between 1 and 5"


class RiskValidatorsMixin:
    """Shared field validators for Risk read/create/update serializers.

    Centralizes the score-range and STRIDE-category rules so create, update,
    and read serializers enforce identical validation. Previously only
    ``RiskSerializer`` (never used for input) validated STRIDE codes, so the
    create/update serializers accepted invalid STRIDE categories (#1302).
    """

    @staticmethod
    def validate_likelihood_score(value: int | None) -> int | None:
        """Validate likelihood score is between 1 and 5."""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError(LIKELIHOOD_RANGE_MSG)
        return value

    @staticmethod
    def validate_impact_score(value: int | None) -> int | None:
        """Validate impact score is between 1 and 5."""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError(IMPACT_RANGE_MSG)
        return value

    @staticmethod
    def validate_stride_categories(value: list[str]) -> list[str]:
        """Validate every STRIDE category is a known code."""
        valid_codes = [choice[0] for choice in StrideCategory.choices]
        for category in value:
            if category not in valid_codes:
                raise serializers.ValidationError(f"Invalid STRIDE category: {category}. Must be one of: {valid_codes}")
        return value


class RiskSerializer(RiskValidatorsMixin, serializers.ModelSerializer):
    """Serializer for Risk model."""

    risk_score = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Risk
        fields = [
            "id",
            "title",
            "description",
            "severity",
            "status",
            "stride_categories",
            "likelihood_score",
            "impact_score",
            "risk_score",
            "attack_vector",
            "affected_assets",
            "mitigation_status",
            "resolution_reason",
            "comment_count",
            "created_at",
            "updated_at",
            "is_deleted",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RiskCreateSerializer(RiskValidatorsMixin, serializers.ModelSerializer):
    """Serializer for creating risks."""

    class Meta:
        model = Risk
        fields = [
            "title",
            "description",
            "severity",
            "status",
            "stride_categories",
            "likelihood_score",
            "impact_score",
            "attack_vector",
            "affected_assets",
            "mitigation_status",
        ]


class RiskUpdateSerializer(RiskValidatorsMixin, serializers.ModelSerializer):
    """Serializer for updating risks."""

    class Meta:
        model = Risk
        fields = [
            "title",
            "description",
            "severity",
            "status",
            "stride_categories",
            "likelihood_score",
            "impact_score",
            "attack_vector",
            "affected_assets",
            "mitigation_status",
            "resolution_reason",
        ]


class CommentAuthorSerializer(serializers.Serializer):
    """Serializer for comment author info."""

    type = serializers.CharField()
    id = serializers.IntegerField()
    name = serializers.CharField()


class CommentSerializer(serializers.ModelSerializer):
    """Serializer for Comment model."""

    author = serializers.SerializerMethodField()
    risk_id = serializers.IntegerField(source="risk.id", read_only=True)
    parent_comment_id = serializers.IntegerField(source="parent_comment.id", read_only=True, allow_null=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "risk_id",
            "content",
            "author",
            "parent_comment_id",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_author(self, obj):
        """Get author information."""
        if obj.author_user:
            return {
                "type": "user",
                "id": obj.author_user.id,
                "name": obj.author_user.email,
            }
        elif obj.author_apikey:
            return {
                "type": "apikey",
                "id": obj.author_apikey.id,
                "name": obj.author_apikey.name,
            }
        return None


class CommentCreateSerializer(serializers.Serializer):
    """Serializer for creating comments."""

    content = serializers.CharField(min_length=1)


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for AuditLog model (read-only)."""

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "entity_type",
            "entity_id",
            "action",
            "actor_type",
            "actor_id",
            "timestamp",
            "previous_state",
            "new_state",
            "context",
            "source_ip",
            "user_agent",
            "request_id",
        ]
        read_only_fields = fields
