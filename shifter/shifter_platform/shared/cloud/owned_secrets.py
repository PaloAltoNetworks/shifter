"""Server-owned immutable credential names shared by cloud secret stores."""

from uuid import UUID


def model_source_secret_name(source_id: UUID, version_id: UUID) -> str:
    """Neither a browser nor a broker may provide an arbitrary cloud path."""
    if not isinstance(source_id, UUID) or not isinstance(version_id, UUID):
        raise ValueError("credential ownership requires UUIDs")
    return f"shifter-model-source-{source_id.hex}-{version_id.hex}"


def validate_owned_payload(value: str) -> bytes:
    """Encode a nonempty credential within the owned-secret storage bound."""
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 32768:
        raise ValueError("invalid credential size")
    return value.encode("utf-8")
