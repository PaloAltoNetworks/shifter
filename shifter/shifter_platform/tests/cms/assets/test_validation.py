"""Unit tests for file validation service."""

import io

import pytest

from cms.assets.validation import (
    ALLOWED_FORMATS,
    ValidationError,
    get_allowed_extensions,
    get_file_extension,
    get_format_for_extension,
    validate_agent_file,
    validate_file_extension,
    validate_file_size,
    validate_magic_bytes,
)


class TestGetFileExtension:
    def test_simple_extension(self):
        assert get_file_extension("file.msi") == ".msi"

    def test_compound_tar_gz(self):
        assert get_file_extension("agent.tar.gz") == ".tar.gz"

    def test_tgz(self):
        assert get_file_extension("agent.tgz") == ".tgz"

    def test_case_insensitive(self):
        assert get_file_extension("FILE.MSI") == ".msi"

    def test_no_extension(self):
        assert get_file_extension("filename") == ""

    def test_multiple_dots(self):
        assert get_file_extension("file.name.deb") == ".deb"


class TestGetFormatForExtension:
    def test_msi(self):
        fmt = get_format_for_extension(".msi")
        assert fmt is not None
        assert fmt.os_slug == "windows"

    def test_zip(self):
        fmt = get_format_for_extension(".zip")
        assert fmt is not None
        assert fmt.os_slug == "windows"

    def test_tar_gz(self):
        fmt = get_format_for_extension(".tar.gz")
        assert fmt is not None
        assert fmt.os_slug == "linux-generic"

    def test_tgz(self):
        fmt = get_format_for_extension(".tgz")
        assert fmt is not None
        assert fmt.os_slug == "linux-generic"

    def test_deb(self):
        fmt = get_format_for_extension(".deb")
        assert fmt is not None
        assert fmt.os_slug == "linux-debian"

    def test_rpm(self):
        fmt = get_format_for_extension(".rpm")
        assert fmt is not None
        assert fmt.os_slug == "linux-rhel"

    def test_unknown(self):
        assert get_format_for_extension(".exe") is None

    def test_case_insensitive(self):
        fmt = get_format_for_extension(".MSI")
        assert fmt is not None


class TestGetAllowedExtensions:
    def test_returns_all_extensions(self):
        extensions = get_allowed_extensions()
        assert ".msi" in extensions
        assert ".zip" in extensions
        assert ".tar.gz" in extensions
        assert ".tgz" in extensions
        assert ".deb" in extensions
        assert ".rpm" in extensions


class TestValidateFileSize:
    def test_valid_size(self, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        file_obj = io.BytesIO(b"x" * 1000)
        file_obj.size = 1000
        validate_file_size(file_obj)  # Should not raise

    def test_exceeds_limit(self, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 1  # 1 MB
        file_obj = io.BytesIO(b"x" * 100)
        file_obj.size = 2 * 1024 * 1024  # 2 MB
        with pytest.raises(ValidationError) as exc:
            validate_file_size(file_obj)
        assert "exceeds maximum" in str(exc.value)

    def test_fallback_to_seek(self, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        file_obj = io.BytesIO(b"x" * 1000)
        # No size attribute
        validate_file_size(file_obj)  # Should not raise


class TestValidateFileExtension:
    def test_valid_extension(self):
        fmt = validate_file_extension("agent.msi")
        assert fmt.os_slug == "windows"

    def test_invalid_extension(self):
        with pytest.raises(ValidationError) as exc:
            validate_file_extension("agent.exe")
        assert "not allowed" in str(exc.value)

    def test_no_extension(self):
        with pytest.raises(ValidationError) as exc:
            validate_file_extension("agent")
        assert "no extension" in str(exc.value)


class TestValidateMagicBytes:
    def test_valid_msi_magic(self):
        # OLE Compound Document magic bytes
        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_obj = io.BytesIO(magic + b"content")
        fmt = ALLOWED_FORMATS["msi"]
        validate_magic_bytes(file_obj, fmt)  # Should not raise

    def test_valid_zip_magic(self):
        magic = bytes([0x50, 0x4B, 0x03, 0x04])
        file_obj = io.BytesIO(magic + b"content")
        fmt = ALLOWED_FORMATS["zip"]
        validate_magic_bytes(file_obj, fmt)  # Should not raise

    def test_valid_gzip_magic(self):
        magic = bytes([0x1F, 0x8B])
        file_obj = io.BytesIO(magic + b"content")
        fmt = ALLOWED_FORMATS["tar_gz"]
        validate_magic_bytes(file_obj, fmt)  # Should not raise

    def test_valid_deb_magic(self):
        magic = b"!<arch>"
        file_obj = io.BytesIO(magic + b"content")
        fmt = ALLOWED_FORMATS["deb"]
        validate_magic_bytes(file_obj, fmt)  # Should not raise

    def test_valid_rpm_magic(self):
        magic = bytes([0xED, 0xAB, 0xEE, 0xDB])
        file_obj = io.BytesIO(magic + b"content")
        fmt = ALLOWED_FORMATS["rpm"]
        validate_magic_bytes(file_obj, fmt)  # Should not raise

    def test_invalid_magic(self):
        file_obj = io.BytesIO(b"not a real msi file")
        fmt = ALLOWED_FORMATS["msi"]
        with pytest.raises(ValidationError) as exc:
            validate_magic_bytes(file_obj, fmt)
        assert "does not match" in str(exc.value)

    def test_file_too_small(self):
        file_obj = io.BytesIO(b"x")
        fmt = ALLOWED_FORMATS["msi"]
        with pytest.raises(ValidationError) as exc:
            validate_magic_bytes(file_obj, fmt)
        assert "too small" in str(exc.value)


class TestValidateAgentFile:
    def test_valid_msi_file(self, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        file_obj = io.BytesIO(magic + b"x" * 1000)
        file_obj.size = len(magic) + 1000

        fmt = validate_agent_file(file_obj, "agent.msi")
        assert fmt.os_slug == "windows"

    def test_valid_tar_gz_file(self, settings):
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        magic = bytes([0x1F, 0x8B])
        file_obj = io.BytesIO(magic + b"x" * 1000)
        file_obj.size = len(magic) + 1000

        fmt = validate_agent_file(file_obj, "agent.tar.gz")
        assert fmt.os_slug == "linux-generic"

    def test_extension_mismatch(self, settings):
        """File with .msi extension but ZIP magic bytes should fail."""
        settings.AGENT_MAX_FILE_SIZE_MB = 200
        zip_magic = bytes([0x50, 0x4B, 0x03, 0x04])
        file_obj = io.BytesIO(zip_magic + b"x" * 1000)
        file_obj.size = len(zip_magic) + 1000

        with pytest.raises(ValidationError) as exc:
            validate_agent_file(file_obj, "agent.msi")
        assert "does not match" in str(exc.value)

    def test_size_check_first(self, settings):
        """Size check should happen before expensive magic byte check."""
        settings.AGENT_MAX_FILE_SIZE_MB = 1
        file_obj = io.BytesIO(b"x" * 100)
        file_obj.size = 2 * 1024 * 1024  # 2 MB

        with pytest.raises(ValidationError) as exc:
            validate_agent_file(file_obj, "agent.msi")
        assert "exceeds maximum" in str(exc.value)
