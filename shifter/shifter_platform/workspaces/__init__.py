"""Workspaces: the organization/workspace tenancy domain (ADR-046).

Owns ``Organization``, ``Workspace``, and ``WorkspaceMembership`` and the
authorization seam above them. Other layers consume this domain only through
``workspaces.services``; they never import its models and never hold a
cross-layer ForeignKey to them (ADR-001, ADR-046-R1).
"""
