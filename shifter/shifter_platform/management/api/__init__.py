"""Canonical ``/api/v1/`` management API for the Administer workspace (#1373).

Named-operation user-administration endpoints (read + account-status lifecycle)
consumed by the SPA Administer workspace. Session-only, staff-gated, explicit
read/write field allowlists, strict request-attributed audit inside the atomic
service boundary. The cross-domain local-organizer grant lives at the ``config``
composition root (``config.api_administer``) because it needs
``config.organizer_authority`` and feature apps do not import the composition
root (ADR-001).
"""
