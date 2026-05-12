"""File validation for agent uploads.

Thin domain-specific layer over `shared.uploads.inspection`. `ALLOWED_FORMATS`
is the agent-installer registry; size and extension checks remain here because
they depend on Django settings and Django UploadedFile semantics.
"""

from django.conf import settings

from shared.uploads.inspection import (
    FileFormat,
    InspectionError,
    MagicSignature,
    get_file_extension,
)
from shared.uploads.inspection import (
    validate_magic_bytes as _validate_magic_bytes_pure,
)


class ValidationError(Exception):
    """Raised when file validation fails."""


# Allowed installer formats. ``.msi`` matches the OLE compound document
# signature; distinguishing MSI from other OLE compound files (e.g. legacy
# Office DOC/XLS) requires parsing the FAT directory to extract the root
# CLSID and is outside a bounded header-byte inspection. The agent-extension
# allowlist constrains the realistic attack surface to OLE-compound material.
ALLOWED_FORMATS: dict[str, FileFormat] = {
    "msi": FileFormat(
        extensions=[".msi"],
        signatures=(MagicSignature(0, bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])),),
        os_slug="windows",
        description="Windows Installer / OLE Compound Document (.msi)",
    ),
    "zip": FileFormat(
        extensions=[".zip"],
        signatures=(MagicSignature(0, bytes([0x50, 0x4B, 0x03, 0x04])),),
        os_slug="windows",
        description="ZIP Archive (.zip)",
    ),
    "tar_gz": FileFormat(
        extensions=[".tar.gz", ".tgz"],
        signatures=(MagicSignature(0, bytes([0x1F, 0x8B])),),
        os_slug="linux-generic",
        description="Gzip Tarball (.tar.gz, .tgz)",
    ),
    "deb": FileFormat(
        extensions=[".deb"],
        signatures=(MagicSignature(0, b"!<arch>"),),
        os_slug="linux-debian",
        description="Debian Package (.deb)",
    ),
    "rpm": FileFormat(
        extensions=[".rpm"],
        signatures=(MagicSignature(0, bytes([0xED, 0xAB, 0xEE, 0xDB])),),
        os_slug="linux-rhel",
        description="RPM Package (.rpm)",
    ),
}


def get_format_for_extension(extension: str) -> FileFormat | None:
    """Find the file format definition for an extension."""
    ext_lower = extension.lower()
    for fmt in ALLOWED_FORMATS.values():
        if ext_lower in fmt.extensions:
            return fmt
    return None


def get_allowed_extensions() -> list[str]:
    """Get list of all allowed file extensions."""
    extensions = []
    for fmt in ALLOWED_FORMATS.values():
        extensions.extend(fmt.extensions)
    return extensions


def validate_file_size(file_obj) -> None:
    """Validate file size is within limits.

    Raises:
        ValidationError: If file exceeds `settings.AGENT_MAX_FILE_SIZE_MB`.
    """
    max_bytes = settings.AGENT_MAX_FILE_SIZE_MB * 1024 * 1024

    if hasattr(file_obj, "size"):
        size = file_obj.size
    else:
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)

    if size > max_bytes:
        raise ValidationError(
            f"File size ({size / 1024 / 1024:.1f} MB) exceeds maximum allowed ({settings.AGENT_MAX_FILE_SIZE_MB} MB)"
        )


def validate_file_extension(filename: str) -> FileFormat:
    """Validate file has an allowed extension and return the matching format."""
    extension = get_file_extension(filename)
    if not extension:
        raise ValidationError("File has no extension")

    fmt = get_format_for_extension(extension)
    if not fmt:
        allowed = ", ".join(get_allowed_extensions())
        raise ValidationError(f"Extension '{extension}' not allowed. Allowed: {allowed}")

    return fmt


def validate_magic_bytes(file_obj, expected_format: FileFormat) -> None:
    """Validate file content matches every magic-byte signature on the format.

    Wraps the pure-bytes inspector in `shared.uploads.inspection` with the
    file-object seek/read pattern Django UploadedFiles expect. Reads enough
    bytes to evaluate the highest-offset signature on the format.
    """
    read_len = max(expected_format.min_header_bytes, 1)
    file_obj.seek(0)
    header = file_obj.read(read_len)
    file_obj.seek(0)

    try:
        _validate_magic_bytes_pure(header, expected_format)
    except InspectionError as exc:
        message = str(exc)
        if "too small to be a valid" in message:
            raise ValidationError("File is too small to be a valid installer") from exc
        if "does not match expected format" in message:
            raise ValidationError(
                f"File content does not match expected format ({expected_format.description}). "
                "The file may be corrupted or mislabeled."
            ) from exc
        raise ValidationError(message) from exc


def validate_agent_file(file_obj, filename: str) -> FileFormat:
    """Perform full validation of an agent upload file.

    Order: size first (cheapest), then extension, then magic bytes.

    Raises:
        ValidationError: If any check fails.
    """
    validate_file_size(file_obj)
    fmt = validate_file_extension(filename)
    validate_magic_bytes(file_obj, fmt)
    return fmt
