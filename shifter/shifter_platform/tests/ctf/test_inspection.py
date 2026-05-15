"""Tests for ctf.inspection — CTF attachment header inspection."""

import pytest

from ctf.inspection import (
    CTFInspectionError,
    inspect_attachment_header,
)


class TestMagicCategory:
    """Extensions whose header must positively match a magic-byte signature."""

    def test_png_passes_with_png_magic(self):
        inspect_attachment_header(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, ".png")

    def test_png_fails_with_pdf_magic(self):
        with pytest.raises(CTFInspectionError) as exc:
            inspect_attachment_header(b"%PDF-1.4\n" + b"\x00" * 16, ".png")
        assert ".png" in str(exc.value)

    def test_pdf_passes_with_pdf_magic(self):
        inspect_attachment_header(b"%PDF-1.7\n" + b"\x00" * 16, ".pdf")

    def test_zip_passes_with_zip_magic(self):
        inspect_attachment_header(b"\x50\x4b\x03\x04" + b"\x00" * 16, ".zip")

    def test_zip_fails_with_random_bytes(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"random nonsense bytes", ".zip")

    def test_jpeg_passes_with_jpeg_magic(self):
        inspect_attachment_header(b"\xff\xd8\xff\xe0\x00\x10JFIF", ".jpg")
        inspect_attachment_header(b"\xff\xd8\xff\xe1\x00\x10Exif", ".jpeg")

    def test_elf_passes_with_elf_magic(self):
        inspect_attachment_header(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8, ".elf")

    def test_pe_passes_with_mz_magic(self):
        inspect_attachment_header(b"MZ\x90\x00" + b"\x00" * 16, ".exe")

    def test_gzip_passes_with_gzip_magic(self):
        inspect_attachment_header(b"\x1f\x8b\x08\x00" + b"\x00" * 16, ".gz")
        inspect_attachment_header(b"\x1f\x8b\x08\x00" + b"\x00" * 16, ".tgz")

    def test_sqlite_passes(self):
        inspect_attachment_header(b"SQLite format 3\x00" + b"\x00" * 8, ".sqlite")
        inspect_attachment_header(b"SQLite format 3\x00" + b"\x00" * 8, ".db")


class TestTextCategory:
    """Extensions whose header must be UTF-8 text and not a known binary signature."""

    def test_txt_accepts_plain_text(self):
        inspect_attachment_header(b"Hello, world!\nThis is a flag file.\n", ".txt")

    def test_md_accepts_markdown(self):
        inspect_attachment_header(b"# Challenge\n\nDescription here.\n", ".md")

    def test_json_accepts_json(self):
        inspect_attachment_header(b'{"flag": "shifter{example}"}\n', ".json")

    def test_csv_accepts_csv(self):
        inspect_attachment_header(b"name,value\nfoo,bar\n", ".csv")

    def test_py_accepts_python_source(self):
        inspect_attachment_header(b"#!/usr/bin/env python3\nprint('hi')\n", ".py")

    def test_sh_accepts_shell_script(self):
        inspect_attachment_header(b"#!/bin/sh\necho hello\n", ".sh")

    def test_pem_accepts_pem_text(self):
        inspect_attachment_header(b"-----BEGIN CERTIFICATE-----\nMIIB...\n", ".pem")

    def test_txt_rejects_zip_magic(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"\x50\x4b\x03\x04rest", ".txt")

    def test_txt_rejects_pe_magic(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"MZ\x90\x00more bytes", ".txt")

    def test_py_rejects_elf_magic(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"\x7fELFmore bytes", ".py")

    def test_json_rejects_non_utf8(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"\xff\xfe\xfd\xfc garbage", ".json")

    def test_txt_with_bom_accepted(self):
        inspect_attachment_header(b"\xef\xbb\xbfHello\n", ".txt")


class TestOpaqueCategory:
    """Extensions where the magic-byte concept does not apply (raw containers)."""

    def test_bin_accepts_anything(self):
        inspect_attachment_header(b"\xff\xfe\xfd\xfc\x00\x01\x02\x03", ".bin")
        inspect_attachment_header(b"\x50\x4b\x03\x04zip-magic", ".bin")
        inspect_attachment_header(b"plain text in bin file", ".bin")

    def test_raw_accepts_anything(self):
        inspect_attachment_header(b"\x00" * 16, ".raw")

    def test_dd_accepts_anything(self):
        inspect_attachment_header(b"\xde\xad\xbe\xef", ".dd")

    def test_iso_accepts_anything(self):
        # ISO 9660 magic is at offset 0x8001, way past our 512-byte window —
        # so OPAQUE is the only sane policy for .iso headers.
        inspect_attachment_header(b"\x00" * 16, ".iso")

    def test_vmdk_accepts_anything(self):
        inspect_attachment_header(b"random vmdk header bytes", ".vmdk")


class TestTarOffsetSignature:
    """`.tar` is MAGIC with ``ustar`` at offset 257 — not OPAQUE."""

    def test_posix_tar_accepted(self):
        header = b"\x00" * 257 + b"ustar\x0000" + b"\x00" * 240
        inspect_attachment_header(header, ".tar")

    def test_random_bytes_rejected(self):
        # Random bytes the size of a tar header, no ustar marker.
        header = b"A" * 512
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(header, ".tar")


class TestWavCompositeSignature:
    """`.wav` requires both ``RIFF`` at 0 AND ``WAVE`` at offset 8."""

    def test_wave_riff_accepted(self):
        header = b"RIFF\x00\x10\x00\x00WAVEfmt \x00\x00"
        inspect_attachment_header(header, ".wav")

    def test_riff_avi_rejected(self):
        # AVI is also a RIFF container — must not pass the .wav rule.
        header = b"RIFF\x00\x10\x00\x00AVI LIST\x00\x00"
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(header, ".wav")

    def test_riff_webp_rejected(self):
        header = b"RIFF\x00\x10\x00\x00WEBPVP8 \x00\x00"
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(header, ".wav")


class TestPemOrDerCategory:
    """`.crt` and `.key` accept either PEM text or DER ASN.1 SEQUENCE."""

    def test_crt_accepts_pem_certificate(self):
        inspect_attachment_header(b"-----BEGIN CERTIFICATE-----\nMIIB...\n", ".crt")

    def test_crt_accepts_der_certificate(self):
        inspect_attachment_header(b"\x30\x82\x03\x10" + b"\x00" * 32, ".crt")

    def test_key_accepts_pem_private_key(self):
        # PEM armor is constructed at runtime so the `detect-private-key`
        # pre-commit hook doesn't trip on the literal label.
        armor = b"-----BEGIN " + b"RSA PRIVATE KEY" + b"-----"
        inspect_attachment_header(armor + b"\nMIIE...\n", ".key")

    def test_key_accepts_der_private_key(self):
        inspect_attachment_header(b"\x30\x82\x04\x00" + b"\x00" * 32, ".key")

    def test_crt_rejects_random_binary(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"\x89PNG\r\n\x1a\nrest", ".crt")

    def test_key_rejects_random_text(self):
        with pytest.raises(CTFInspectionError):
            inspect_attachment_header(b"this is not a key file", ".key")


class TestUnknownExtension:
    def test_unknown_extension_rejected(self):
        # Defense-in-depth: even though attachment.py rejects unknown extensions
        # earlier, the inspector must not silently allow them.
        with pytest.raises(CTFInspectionError) as exc:
            inspect_attachment_header(b"anything", ".unknown-ext")
        assert "extension" in str(exc.value).lower() or "unknown" in str(exc.value).lower()


class TestRulesParityWithAllowlist:
    """Cycle 3 finding 3: _RULES must stay in sync with ctf.s3.ALLOWED_EXTENSIONS."""

    def test_rules_keys_equal_allowed_extensions(self):
        from ctf.inspection import _RULES
        from ctf.s3 import ALLOWED_EXTENSIONS

        assert set(_RULES) == ALLOWED_EXTENSIONS


class TestSecretSafety:
    def test_error_message_does_not_echo_upload_bytes(self):
        leak = b"S3CR3T-FLAG-DO-NOT-LEAK"
        with pytest.raises(CTFInspectionError) as exc:
            inspect_attachment_header(leak, ".png")
        assert "S3CR3T-FLAG" not in str(exc.value)
        assert "DO-NOT-LEAK" not in str(exc.value)
