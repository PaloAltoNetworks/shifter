"""File validation for agent uploads."""

from dataclasses import dataclass

from django.conf import settings


class ValidationError(Exception):
    """Raised when file validation fails."""

    pass


@dataclass
class FileFormat:
    """Definition of an allowed file format."""

    extensions: list[str]
    magic_bytes: bytes
    os_slug: str
    description: str


# Allowed file formats with magic byte signatures
ALLOWED_FORMATS: dict[str, FileFormat] = {
    "msi": FileFormat(
        extensions=[".msi"],
        magic_bytes=bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]),
        os_slug="windows",
        description="Windows Installer (.msi)",
    ),
    "zip": FileFormat(
        extensions=[".zip"],
        magic_bytes=bytes([0x50, 0x4B, 0x03, 0x04]),
        os_slug="windows",
        description="ZIP Archive (.zip)",
    ),
    "tar_gz": FileFormat(
        extensions=[".tar.gz", ".tgz"],
        magic_bytes=bytes([0x1F, 0x8B]),
        os_slug="linux-generic",
        description="Gzip Tarball (.tar.gz, .tgz)",
    ),
    "deb": FileFormat(
        extensions=[".deb"],
        magic_bytes=b"!<arch>",
        os_slug="linux-debian",
        description="Debian Package (.deb)",
    ),
    "rpm": FileFormat(
        extensions=[".rpm"],
        magic_bytes=bytes([0xED, 0xAB, 0xEE, 0xDB]),
        os_slug="linux-rhel",
        description="RPM Package (.rpm)",
    ),
}


def get_file_extension(filename: str) -> str:
    """
    Get file extension, handling compound extensions like .tar.gz.

    Args:
        filename: The filename to extract extension from

    Returns:
        Extension including leading dot, lowercase
    """
    lower = filename.lower()

    # Check compound extensions first
    if lower.endswith(".tar.gz"):
        return ".tar.gz"

    # Simple extension
    if "." in filename:
        return "." + lower.rsplit(".", 1)[-1]

    return ""


def get_format_for_extension(extension: str) -> FileFormat | None:
    """
    Find the file format definition for an extension.

    Args:
        extension: File extension including dot

    Returns:
        FileFormat if found, None otherwise
    """
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
    """
    Validate file size is within limits.

    Args:
        file_obj: Django UploadedFile object

    Raises:
        ValidationError: If file exceeds size limit
    """
    max_bytes = settings.AGENT_MAX_FILE_SIZE_MB * 1024 * 1024

    # Get file size - Django's UploadedFile has a size attribute
    if hasattr(file_obj, "size"):
        size = file_obj.size
    else:
        # Fallback: seek to end to get size
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)

    if size > max_bytes:
        raise ValidationError(
            f"File size ({size / 1024 / 1024:.1f} MB) exceeds maximum allowed ({settings.AGENT_MAX_FILE_SIZE_MB} MB)"
        )


def validate_file_extension(filename: str) -> FileFormat:
    """
    Validate file has an allowed extension.

    Args:
        filename: Name of the uploaded file

    Returns:
        FileFormat for the extension

    Raises:
        ValidationError: If extension is not allowed
    """
    extension = get_file_extension(filename)
    if not extension:
        raise ValidationError("File has no extension")

    fmt = get_format_for_extension(extension)
    if not fmt:
        allowed = ", ".join(get_allowed_extensions())
        raise ValidationError(f"Extension '{extension}' not allowed. Allowed: {allowed}")

    return fmt


def validate_magic_bytes(file_obj, expected_format: FileFormat) -> None:
    """
    Validate file content matches expected magic bytes.

    Args:
        file_obj: File-like object to validate
        expected_format: The format we expect based on extension

    Raises:
        ValidationError: If magic bytes don't match
    """
    # Read enough bytes to check magic
    magic_len = len(expected_format.magic_bytes)
    file_obj.seek(0)
    header = file_obj.read(magic_len)
    file_obj.seek(0)

    if len(header) < magic_len:
        raise ValidationError("File is too small to be a valid installer")

    if not header.startswith(expected_format.magic_bytes):
        raise ValidationError(
            f"File content does not match expected format ({expected_format.description}). "
            "The file may be corrupted or mislabeled."
        )


def validate_agent_file(file_obj, filename: str) -> FileFormat:
    """
    Perform full validation of an agent upload file.

    Args:
        file_obj: Django UploadedFile or file-like object
        filename: Original filename

    Returns:
        FileFormat of the validated file

    Raises:
        ValidationError: If any validation check fails
    """
    # Check size first (cheapest check)
    validate_file_size(file_obj)

    # Check extension
    fmt = validate_file_extension(filename)

    # Check magic bytes
    validate_magic_bytes(file_obj, fmt)

    return fmt
