"""DRF serializers for Risk Register API."""

from rest_framework import serializers

from risk_register.models import APIKey, Comment, Risk, StrideCategory


class RiskSerializer(serializers.ModelSerializer):
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

    def validate_likelihood_score(self, value):
        """Validate likelihood score is between 1 and 5."""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Likelihood score must be between 1 and 5")
        return value

    def validate_impact_score(self, value):
        """Validate impact score is between 1 and 5."""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Impact score must be between 1 and 5")
        return value

    def validate_stride_categories(self, value):
        """Validate STRIDE categories."""
        valid_codes = [choice[0] for choice in StrideCategory.choices]
        for category in value:
            if category not in valid_codes:
                raise serializers.ValidationError(f"Invalid STRIDE category: {category}. Must be one of: {valid_codes}")
        return value


class RiskCreateSerializer(serializers.ModelSerializer):
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

    def validate_likelihood_score(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Likelihood score must be between 1 and 5")
        return value

    def validate_impact_score(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Impact score must be between 1 and 5")
        return value


class RiskUpdateSerializer(serializers.ModelSerializer):
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

    def validate_likelihood_score(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Likelihood score must be between 1 and 5")
        return value

    def validate_impact_score(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("Impact score must be between 1 and 5")
        return value


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


class APIKeySerializer(serializers.ModelSerializer):
    """Serializer for APIKey model (read operations)."""

    is_active = serializers.BooleanField(read_only=True)
    display_key = serializers.CharField(read_only=True)

    class Meta:
        model = APIKey
        fields = [
            "id",
            "name",
            "prefix",
            "display_key",
            "created_at",
            "last_used_at",
            "expires_at",
            "is_active",
        ]
        read_only_fields = fields


class APIKeyCreateSerializer(serializers.Serializer):
    """Serializer for creating API keys."""

    name = serializers.CharField(max_length=100)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class APIKeyCreatedSerializer(serializers.Serializer):
    """Serializer for API key creation response (includes raw key)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    key = serializers.CharField()
    prefix = serializers.CharField()
