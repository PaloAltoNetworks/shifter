"""Shared building-block serializers for the canonical CTF DRF API."""

from __future__ import annotations

from rest_framework import serializers


class _NamedRefSerializer(serializers.Serializer):
    """A minimal ``{id, name}`` reference to a related entity."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
