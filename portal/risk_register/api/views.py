"""DRF viewsets for Risk Register API."""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from risk_register.api.permissions import IsAdminUser, IsAuthenticatedOrAPIKey
from risk_register.api.serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeySerializer,
    CommentCreateSerializer,
    CommentSerializer,
    RiskCreateSerializer,
    RiskSerializer,
    RiskUpdateSerializer,
)
from risk_register.models import APIKey, AuditLog, Comment, Risk


def get_actor_info(request):
    """Extract actor type and ID from request for audit logging."""
    if isinstance(request.auth, APIKey):
        return AuditLog.ActorType.APIKEY, request.auth.id
    elif request.user and request.user.is_authenticated:
        return AuditLog.ActorType.USER, request.user.id
    return None, None


def risk_to_dict(risk: Risk) -> dict:
    """Convert risk to dictionary for audit logging."""
    return {
        "id": risk.id,
        "title": risk.title,
        "description": risk.description,
        "severity": risk.severity,
        "status": risk.status,
        "stride_categories": risk.stride_categories,
        "likelihood_score": risk.likelihood_score,
        "impact_score": risk.impact_score,
        "attack_vector": risk.attack_vector,
        "affected_assets": risk.affected_assets,
        "mitigation_status": risk.mitigation_status,
        "resolution_reason": risk.resolution_reason,
        "deleted_at": risk.deleted_at.isoformat() if risk.deleted_at else None,
    }


class RiskViewSet(viewsets.ModelViewSet):
    """ViewSet for Risk CRUD operations."""

    permission_classes = [IsAuthenticatedOrAPIKey]

    def get_serializer_class(self):
        if self.action == "create":
            return RiskCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return RiskUpdateSerializer
        return RiskSerializer

    def get_queryset(self):
        """Return risks, optionally including deleted ones."""
        queryset = Risk.objects.all()

        # Filter by deleted status
        include_deleted = self.request.query_params.get("include_deleted", "").lower() == "true"
        if not include_deleted:
            queryset = queryset.filter(deleted_at__isnull=True)

        # Filter by status
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by severity
        severity_filter = self.request.query_params.get("severity")
        if severity_filter:
            queryset = queryset.filter(severity=severity_filter)

        return queryset

    def create(self, request, *args, **kwargs):
        """Create a new risk with audit logging."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        risk = Risk.objects.create(**serializer.validated_data)

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            AuditLog.log(
                entity_type=AuditLog.EntityType.RISK,
                entity_id=risk.id,
                action=AuditLog.Action.CREATE,
                actor_type=actor_type,
                actor_id=actor_id,
                new_state=risk_to_dict(risk),
            )

        output_serializer = RiskSerializer(risk)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Update a risk with audit logging."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        previous_state = risk_to_dict(instance)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            # Determine action type
            action_type = AuditLog.Action.UPDATE
            old_status = previous_state.get("status")
            new_status = instance.status

            if old_status != "closed" and new_status == "closed":
                action_type = AuditLog.Action.CLOSE
            elif old_status == "closed" and new_status != "closed":
                action_type = AuditLog.Action.REOPEN

            AuditLog.log(
                entity_type=AuditLog.EntityType.RISK,
                entity_id=instance.id,
                action=action_type,
                actor_type=actor_type,
                actor_id=actor_id,
                previous_state=previous_state,
                new_state=risk_to_dict(instance),
            )

        output_serializer = RiskSerializer(instance)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Soft-delete a risk."""
        instance = self.get_object()
        previous_state = risk_to_dict(instance)

        instance.soft_delete()

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            AuditLog.log(
                entity_type=AuditLog.EntityType.RISK,
                entity_id=instance.id,
                action=AuditLog.Action.DELETE,
                actor_type=actor_type,
                actor_id=actor_id,
                previous_state=previous_state,
                new_state=risk_to_dict(instance),
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Restore a soft-deleted risk."""
        instance = self.get_object()

        if not instance.is_deleted:
            return Response(
                {"error": "bad_request", "message": "Risk is not deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_state = risk_to_dict(instance)
        instance.restore()

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            AuditLog.log(
                entity_type=AuditLog.EntityType.RISK,
                entity_id=instance.id,
                action=AuditLog.Action.RESTORE,
                actor_type=actor_type,
                actor_id=actor_id,
                previous_state=previous_state,
                new_state=risk_to_dict(instance),
            )

        serializer = RiskSerializer(instance)
        return Response(serializer.data)


class CommentViewSet(viewsets.ViewSet):
    """ViewSet for Comment operations (nested under risks)."""

    permission_classes = [IsAuthenticatedOrAPIKey]

    def list(self, request, risk_pk=None):
        """List comments for a risk."""
        risk = get_object_or_404(Risk, pk=risk_pk)

        include_deleted = request.query_params.get("include_deleted", "").lower() == "true"
        comments = risk.comments.all().order_by("created_at")

        if not include_deleted:
            comments = comments.filter(deleted_at__isnull=True)

        serializer = CommentSerializer(comments, many=True)
        return Response(serializer.data)

    def create(self, request, risk_pk=None):
        """Create a comment on a risk."""
        risk = get_object_or_404(Risk, pk=risk_pk)

        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Determine author
        author_user = None
        author_apikey = None

        if isinstance(request.auth, APIKey):
            author_apikey = request.auth
        elif request.user and request.user.is_authenticated:
            author_user = request.user

        comment = Comment.objects.create(
            risk=risk,
            content=serializer.validated_data["content"],
            author_user=author_user,
            author_apikey=author_apikey,
        )

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            AuditLog.log(
                entity_type=AuditLog.EntityType.COMMENT,
                entity_id=comment.id,
                action=AuditLog.Action.CREATE,
                actor_type=actor_type,
                actor_id=actor_id,
                new_state={
                    "risk_id": risk.id,
                    "content": comment.content,
                },
            )

        output_serializer = CommentSerializer(comment)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, risk_pk=None, pk=None):
        """Soft-delete a comment."""
        comment = get_object_or_404(Comment, pk=pk, risk__pk=risk_pk)

        comment.soft_delete()

        # Audit log
        actor_type, actor_id = get_actor_info(request)
        if actor_type and actor_id:
            AuditLog.log(
                entity_type=AuditLog.EntityType.COMMENT,
                entity_id=comment.id,
                action=AuditLog.Action.DELETE,
                actor_type=actor_type,
                actor_id=actor_id,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class APIKeyViewSet(viewsets.ViewSet):
    """ViewSet for API key management."""

    permission_classes = [IsAdminUser]

    def list(self, request):
        """List all API keys."""
        keys = APIKey.objects.all()
        serializer = APIKeySerializer(keys, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Get a single API key."""
        key = get_object_or_404(APIKey, pk=pk)
        serializer = APIKeySerializer(key)
        return Response(serializer.data)

    def create(self, request):
        """Create a new API key."""
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        api_key, raw_key = APIKey.create_key(
            name=serializer.validated_data["name"],
            created_by=request.user,
            expires_at=serializer.validated_data.get("expires_at"),
        )

        # Audit log
        AuditLog.log(
            entity_type=AuditLog.EntityType.APIKEY,
            entity_id=api_key.id,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
            new_state={
                "name": api_key.name,
                "prefix": api_key.prefix,
            },
        )

        output = APIKeyCreatedSerializer(
            {
                "id": api_key.id,
                "name": api_key.name,
                "key": raw_key,
                "prefix": api_key.prefix,
            }
        )
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        """Revoke an API key."""
        api_key = get_object_or_404(APIKey, pk=pk)

        if not api_key.is_active:
            return Response(
                {"error": "bad_request", "message": "API key is already revoked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_key.revoke()

        # Audit log
        AuditLog.log(
            entity_type=AuditLog.EntityType.APIKEY,
            entity_id=api_key.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=request.user.id,
        )

        serializer = APIKeySerializer(api_key)
        return Response(serializer.data)
