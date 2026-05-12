"""Tests for shared.uploads.inspection."""

import pytest

from shared.uploads.inspection import (
    BINARY_MAGIC_SIGNATURES,
    FileFormat,
    InspectionError,
    MagicSignature,
    get_file_extension,
    looks_like_der_sequence,
    looks_like_known_binary,
    make_text_stream_validator,
    validate_magic_bytes,
    validate_pem_or_der_header,
    validate_text_header,
)


class TestFileFormat:
    def test_construct_with_signatures(self):
        fmt = FileFormat(
            extensions=[".zip"],
            signatures=(MagicSignature(0, b"\x50\x4b\x03\x04"),),
            description="ZIP",
        )
        assert fmt.extensions == [".zip"]
        assert fmt.signatures[0].pattern == b"\x50\x4b\x03\x04"
        assert fmt.description == "ZIP"
        assert fmt.os_slug is None
        assert fmt.magic_bytes == b"\x50\x4b\x03\x04"
        assert fmt.min_header_bytes == 4

    def test_os_slug_optional(self):
        fmt = FileFormat(
            extensions=[".msi"],
            signatures=(MagicSignature(0, b"\xd0\xcf\x11\xe0"),),
            description="MSI",
            os_slug="windows",
        )
        assert fmt.os_slug == "windows"

    def test_min_header_bytes_uses_max_offset(self):
        fmt = FileFormat(
            extensions=[".wav"],
            signatures=(
                MagicSignature(0, b"RIFF"),
                MagicSignature(8, b"WAVE"),
            ),
            description="WAV",
        )
        assert fmt.min_header_bytes == 12

    def test_magic_bytes_property_skips_non_zero_offset(self):
        fmt = FileFormat(
            extensions=[".tar"],
            signatures=(MagicSignature(257, b"ustar"),),
            description="POSIX tar",
        )
        # No offset-0 signature → empty magic_bytes convenience accessor.
        assert fmt.magic_bytes == b""


class TestMagicSignatureMatches:
    def test_offset_zero_match(self):
        sig = MagicSignature(0, b"\x89PNG")
        assert sig.matches(b"\x89PNG more bytes") is True

    def test_non_zero_offset_match(self):
        sig = MagicSignature(8, b"WAVE")
        assert sig.matches(b"RIFF\x00\x00\x00\x00WAVE more") is True

    def test_short_header_returns_false(self):
        sig = MagicSignature(257, b"ustar")
        assert sig.matches(b"short") is False

    def test_offset_mismatch_returns_false(self):
        sig = MagicSignature(8, b"WAVE")
        assert sig.matches(b"RIFFsome-wrong-format-here") is False


class TestGetFileExtension:
    def test_simple(self):
        assert get_file_extension("agent.msi") == ".msi"

    def test_compound_tar_gz(self):
        assert get_file_extension("agent.tar.gz") == ".tar.gz"

    def test_case_insensitive(self):
        assert get_file_extension("FILE.MSI") == ".msi"

    def test_no_extension(self):
        assert get_file_extension("plainfile") == ""

    def test_multiple_dots(self):
        assert get_file_extension("file.name.deb") == ".deb"


def _zip_fmt() -> FileFormat:
    return FileFormat(
        extensions=[".zip"],
        signatures=(MagicSignature(0, b"\x50\x4b\x03\x04"),),
        description="ZIP",
    )


def _wav_fmt() -> FileFormat:
    return FileFormat(
        extensions=[".wav"],
        signatures=(MagicSignature(0, b"RIFF"), MagicSignature(8, b"WAVE")),
        description="WAV (RIFF/WAVE)",
    )


def _tar_fmt() -> FileFormat:
    return FileFormat(
        extensions=[".tar"],
        signatures=(MagicSignature(257, b"ustar"),),
        description="POSIX tar",
    )


class TestValidateMagicBytes:
    def test_match_succeeds(self):
        validate_magic_bytes(b"\x50\x4b\x03\x04extra-content", _zip_fmt())  # no raise

    def test_mismatch_raises(self):
        with pytest.raises(InspectionError) as exc:
            validate_magic_bytes(b"not-a-zip-file", _zip_fmt())
        msg = str(exc.value)
        assert "does not match" in msg
        assert "ZIP" in msg

    def test_header_shorter_than_signature_raises(self):
        with pytest.raises(InspectionError) as exc:
            validate_magic_bytes(b"\x50", _zip_fmt())
        assert "too small" in str(exc.value).lower()

    def test_does_not_leak_raw_header_in_message(self):
        leak_bytes = b"S3CR3T-TOKEN-DO-NOT-LEAK"
        with pytest.raises(InspectionError) as exc:
            validate_magic_bytes(leak_bytes, _zip_fmt())
        assert b"S3CR3T-TOKEN" not in str(exc.value).encode()
        assert "DO-NOT-LEAK" not in str(exc.value)

    def test_composite_signature_passes_when_both_match(self):
        # RIFF at offset 0 + WAVE at offset 8.
        header = b"RIFF\x00\x10\x00\x00WAVEfmt ..."
        validate_magic_bytes(header, _wav_fmt())

    def test_composite_signature_fails_when_format_id_wrong(self):
        # RIFF at offset 0 + AVI  at offset 8 (a different RIFF container).
        header = b"RIFF\x00\x10\x00\x00AVI \x00\x00\x00"
        with pytest.raises(InspectionError) as exc:
            validate_magic_bytes(header, _wav_fmt())
        assert "WAV" in str(exc.value)

    def test_offset_signature_match_at_257(self):
        # POSIX tar header has 'ustar' at offset 257.
        header = b"\x00" * 257 + b"ustar\x0000" + b"\x00" * 240
        validate_magic_bytes(header, _tar_fmt())

    def test_offset_signature_fail_when_marker_missing(self):
        header = b"\x00" * 512  # no ustar marker
        with pytest.raises(InspectionError):
            validate_magic_bytes(header, _tar_fmt())


class TestTextNegativeShortPrefixSafe:
    """Cycle 3 finding 2: short ASCII prefixes must not false-reject text uploads."""

    def test_mz_at_start_of_text_accepted(self):
        # `MZ` is the PE/DOS executable magic but `MZ = "marker"` is a valid
        # Python module assignment.
        validate_text_header(b"MZ = 'marker'\n# Python module top\n")

    def test_bm_at_start_of_text_accepted(self):
        validate_text_header(b"BMP info: this is documentation, not bitmap\n")

    def test_bzh_at_start_of_text_accepted(self):
        # `BZh` is bzip2 magic but `BZh = ...` is valid Python.
        validate_text_header(b"BZh = 'not a bzip2 file'\n")

    def test_id3_at_start_of_text_accepted(self):
        validate_text_header(b"ID3 tags are stored at the start of MP3 files.\n")

    def test_riff_at_start_of_text_accepted(self):
        validate_text_header(b"RIFFraff is an old British insult.\n")

    def test_real_png_header_still_rejected(self):
        with pytest.raises(InspectionError):
            validate_text_header(b"\x89PNG\r\n\x1a\nplausible image content")

    def test_real_zip_header_still_rejected(self):
        with pytest.raises(InspectionError):
            validate_text_header(b"\x50\x4b\x03\x04" + b"\x00" * 16)

    def test_real_pdf_header_still_rejected(self):
        with pytest.raises(InspectionError):
            validate_text_header(b"%PDF-1.7\n" + b"\x00" * 16)


class TestTextStreamValidator:
    """Cycle 3 finding 5: full-stream UTF-8 check blocks prefix-pad bypass."""

    def test_accepts_clean_chunks(self):
        v = make_text_stream_validator()
        v.feed(b"#!/usr/bin/env python3\n")
        v.feed(b"print('hi')\n")
        v.finalize()

    def test_rejects_first_chunk_binary_magic(self):
        v = make_text_stream_validator()
        with pytest.raises(InspectionError):
            v.feed(b"\x89PNG\r\n\x1a\nstart")

    def test_rejects_binary_tail_after_text_prefix(self):
        v = make_text_stream_validator()
        v.feed(b"# clean Python prefix\nprint('ok')\n")
        with pytest.raises(InspectionError):
            v.feed(b"\xff\xfe binary garbage")

    def test_handles_multibyte_split_across_chunks(self):
        v = make_text_stream_validator()
        # UTF-8 "café\n" — split between c3 and a9 of `é`.
        v.feed(b"caf\xc3")
        v.feed(b"\xa9\n")
        v.finalize()

    def test_finalize_with_incomplete_trailing_multibyte_rejects(self):
        v = make_text_stream_validator()
        # Trailing 0xc3 with no continuation byte → corruption at end of file.
        v.feed(b"caf\xc3")
        with pytest.raises(InspectionError):
            v.finalize()

    def test_finalize_without_any_chunks_rejects(self):
        v = make_text_stream_validator()
        with pytest.raises(InspectionError):
            v.finalize()


class TestLooksLikeKnownBinary:
    def test_zip_magic_detected(self):
        assert looks_like_known_binary(b"\x50\x4b\x03\x04rest") is True

    def test_png_magic_detected(self):
        assert looks_like_known_binary(b"\x89PNG\r\n\x1a\nrest") is True

    def test_pe_executable_no_longer_blocks_text(self):
        # `MZ` is a short ASCII-printable prefix that legitimately appears in
        # text uploads (e.g. `MZ = "marker"`). Cycle 3 removed it from the
        # text-negative subset; `looks_like_known_binary` should now be False.
        assert looks_like_known_binary(b"MZ\x90\x00rest") is False

    def test_elf_detected(self):
        assert looks_like_known_binary(b"\x7fELFmore") is True

    def test_plain_text_not_detected(self):
        assert looks_like_known_binary(b"print('hello, world')\n") is False

    def test_empty_header_not_detected(self):
        assert looks_like_known_binary(b"") is False

    def test_binary_signatures_registry_nonempty(self):
        # Sanity: registry must have entries for at least PE, ELF, ZIP, PNG, JPEG, PDF, GZIP.
        magics = set(BINARY_MAGIC_SIGNATURES)
        assert b"\x50\x4b\x03\x04" in magics  # ZIP
        assert b"MZ" in magics  # PE
        assert b"\x7fELF" in magics  # ELF
        assert b"\x89PNG\r\n\x1a\n" in magics  # PNG
        assert b"\xff\xd8\xff" in magics  # JPEG SOI prefix
        assert b"%PDF" in magics  # PDF
        assert b"\x1f\x8b" in magics  # GZIP


class TestValidateTextHeader:
    def test_plain_ascii_python_passes(self):
        validate_text_header(b"print('hello')\n")

    def test_utf8_with_bom_passes(self):
        validate_text_header(b"\xef\xbb\xbfprint('hi')\n")

    def test_utf8_non_ascii_passes(self):
        # "héllo" in UTF-8
        validate_text_header(b"# h\xc3\xa9llo\n")

    def test_zip_magic_rejected(self):
        with pytest.raises(InspectionError) as exc:
            validate_text_header(b"\x50\x4b\x03\x04rest")
        assert "binary" in str(exc.value).lower()

    def test_pe_prefix_in_text_now_accepted(self):
        # Cycle 3 finding 2: `MZ` is too short and too text-friendly to act as
        # an unconditional text blocker. `validate_text_header` no longer
        # rejects text that happens to start with `MZ`.
        validate_text_header(b"MZ = 'not an executable'\n")

    def test_non_utf8_rejected(self):
        # Random bytes that are not valid UTF-8.
        with pytest.raises(InspectionError) as exc:
            validate_text_header(b"\xff\xfe\xfd\xfc some garbage")
        msg = str(exc.value).lower()
        # Either "utf-8" / "text" message — accept either phrasing.
        assert "utf-8" in msg or "text" in msg

    def test_empty_header_rejected(self):
        with pytest.raises(InspectionError) as exc:
            validate_text_header(b"")
        assert "empty" in str(exc.value).lower()

    def test_incomplete_trailing_multibyte_accepted(self):
        # Full text would be "café\n" but we truncate mid-é (UTF-8: c3 a9).
        # The truncated prefix ends with `c3` alone — half a multibyte char.
        # A strict decoder treating this prefix as the whole document would
        # reject it; the bounded-prefix decoder must accept it.
        validate_text_header(b"caf\xc3")  # Note trailing `c3` only

    def test_complete_multibyte_within_prefix_accepted(self):
        validate_text_header("café\n".encode())

    def test_invalid_byte_inside_prefix_rejected(self):
        # `\xff` is never valid UTF-8. This must still be rejected even with
        # the incremental decoder.
        with pytest.raises(InspectionError):
            validate_text_header(b"text\xfftext")


class TestLooksLikeDerSequence:
    def test_2byte_length_prefix_detected(self):
        assert looks_like_der_sequence(b"\x30\x82\x03\x00more-asn1") is True

    def test_3byte_length_prefix_detected(self):
        assert looks_like_der_sequence(b"\x30\x83\x00\x10\x00rest") is True

    def test_4byte_length_prefix_detected(self):
        assert looks_like_der_sequence(b"\x30\x84\x00\x00\x10\x00rest") is True

    def test_short_form_length_prefix_detected(self):
        assert looks_like_der_sequence(b"\x30\x81\x80rest") is True

    def test_text_not_detected(self):
        assert looks_like_der_sequence(b"-----BEGIN CERT-----\n") is False
        assert looks_like_der_sequence(b"random text") is False


class TestValidatePemOrDer:
    def test_pem_accepted(self):
        validate_pem_or_der_header(b"-----BEGIN CERTIFICATE-----\nMIIB...\n")

    def test_pem_key_accepted(self):
        # PEM armor is constructed from a non-literal string so the
        # `detect-private-key` pre-commit hook (which substring-matches
        # the literal label) doesn't trip on test fixtures.
        armor = b"-----BEGIN " + b"RSA PRIVATE KEY" + b"-----"
        validate_pem_or_der_header(armor + b"\nMIIE...\n")

    def test_pem_with_bom_accepted(self):
        validate_pem_or_der_header(b"\xef\xbb\xbf-----BEGIN CERTIFICATE-----\n")

    def test_der_2byte_length_accepted(self):
        validate_pem_or_der_header(b"\x30\x82\x03\x10asn1-payload-bytes")

    def test_der_3byte_length_accepted(self):
        validate_pem_or_der_header(b"\x30\x83\x00\x10\x00asn1-payload-bytes")

    def test_random_text_without_begin_rejected(self):
        with pytest.raises(InspectionError):
            validate_pem_or_der_header(b"some random text without PEM armor")

    def test_random_binary_rejected(self):
        with pytest.raises(InspectionError):
            validate_pem_or_der_header(b"\x89PNG\r\n\x1a\nthis is a PNG")

    def test_empty_rejected(self):
        with pytest.raises(InspectionError):
            validate_pem_or_der_header(b"")

    def test_pem_marker_in_middle_of_text_rejected(self):
        # Text containing the PEM marker later in the body, without being
        # anchored at the start, must NOT pass. This prevents accidental
        # / hostile uploads where unrelated prose precedes the marker.
        header = b"# Notes\nSee certs below:\n-----BEGIN CERTIFICATE-----\n"
        with pytest.raises(InspectionError):
            validate_pem_or_der_header(header)

    def test_pem_with_leading_whitespace_accepted(self):
        # Leading whitespace (newlines, spaces) before the armor is accepted.
        validate_pem_or_der_header(b"\n\n  -----BEGIN CERTIFICATE-----\nMIIB...\n")

    def test_text_without_pem_armor_rejected(self):
        # Plain text without armor and without DER prefix must be rejected.
        with pytest.raises(InspectionError):
            validate_pem_or_der_header(b"-----CERT START-----\nMIIB...\n")  # wrong armor format
