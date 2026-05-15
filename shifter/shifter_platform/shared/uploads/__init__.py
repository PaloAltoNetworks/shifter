"""Upload-inspection primitives shared across CMS, CTF, and experiment scripts.

The single source of truth for `FileFormat`, the magic-byte comparator, and the
binary-signature registry that powers both positive-match and negative
(text-only) header checks. Per-domain registries (agent installers, CTF
attachments, experiment scripts) compose on top of these primitives.
"""

from shared.uploads.inspection import (
    BINARY_MAGIC_SIGNATURES,
    FileFormat,
    InspectionError,
    MagicSignature,
    TextStreamValidator,
    get_file_extension,
    looks_like_der_sequence,
    looks_like_known_binary,
    make_text_stream_validator,
    validate_magic_bytes,
    validate_pem_or_der_header,
    validate_text_header,
)

__all__ = [
    "BINARY_MAGIC_SIGNATURES",
    "FileFormat",
    "InspectionError",
    "MagicSignature",
    "TextStreamValidator",
    "get_file_extension",
    "looks_like_der_sequence",
    "looks_like_known_binary",
    "make_text_stream_validator",
    "validate_magic_bytes",
    "validate_pem_or_der_header",
    "validate_text_header",
]
