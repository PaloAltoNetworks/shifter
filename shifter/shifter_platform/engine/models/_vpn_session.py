"""Live participant OpenVPN sessions on the shared server pool (#2480).

The pool controller asks the Engine to authorize every connection and renews
each live session with a heartbeat. PostgreSQL arbitrates the claim (ADR-063-R3):
at most one active session exists per range, and a newer connection ends the
older one, whose server disconnects it on its next heartbeat. A session row
holds no credential, certificate or profile material.
"""

from uuid import uuid4

from django.db import models
from django.db.models import Q


class VpnSessionState(models.TextChoices):
    """Lifecycle of one pool session."""

    ACTIVE = "active", "Active"
    ENDED = "ended", "Ended"


class VpnSessionEndReason(models.TextChoices):
    """Closed reason a session stopped being active."""

    DISCONNECTED = "disconnected", "Disconnected"
    SUPERSEDED = "superseded", "Superseded by a newer session"
    REVOKED = "revoked", "Range access no longer valid"
    LEASE_EXPIRED = "lease_expired", "Server stopped renewing the session"


class VpnSession(models.Model):
    """One participant connection to one pool server."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    range = models.ForeignKey("engine.Range", on_delete=models.CASCADE, related_name="vpn_sessions")
    # The binding generation the client certificate was minted for.
    generation = models.UUIDField()
    # Pool server instance name and the OpenVPN client id on that server.
    server = models.CharField(max_length=63)
    client_id = models.PositiveBigIntegerField()
    state = models.CharField(max_length=16, choices=VpnSessionState.choices, default=VpnSessionState.ACTIVE)
    end_reason = models.CharField(max_length=16, choices=VpnSessionEndReason.choices, blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    lease_expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """One active session per range; servers renew their own sessions by name."""

        db_table = "engine_vpn_session"
        constraints = [
            models.UniqueConstraint(
                fields=["range"],
                condition=Q(state="active"),
                name="engine_vpn_session_one_active_per_range",
            ),
        ]
        indexes = [
            models.Index(fields=["server", "state"], name="engine_vpnsession_server_idx"),
        ]

    def __str__(self) -> str:
        return f"VpnSession {self.id} ({self.state})"
