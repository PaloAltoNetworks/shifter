"""Pure-bytes header inspection primitives for S3 upload validation.

Three checks compose into the per-domain validators (agent installers, CTF
attachments, experiment scripts):

- ``validate_magic_bytes(header, fmt)``: every ``MagicSignature`` on the
  format must match its declared offset. Supports both offset-zero prefixes
  and composite signatures (e.g. RIFF/WAVE, POSIX tar ``ustar`` at offset
  257).
- ``validate_text_header(header)``: header is non-empty, UTF-8 decodable,
  and does not match any known binary signature in
  ``BINARY_MAGIC_SIGNATURES``.
- ``validate_pem_or_der_header(header)``: header is either a PEM-encoded
  text block (``-----BEGIN ...``) or a DER ASN.1 SEQUENCE prefix. Used by
  ``.crt``/``.key`` extensions that legitimately ship in either encoding.

The binary-signature registry is shared so the CTF text-extension negative
check and the script text-only check use the same definition of "is this a
binary file wearing a text extension?".
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass

_EMPTY_CONTENT_MSG = "Uploaded content is empty"
_INVALID_UTF8_MSG = "Uploaded content is not valid UTF-8 text."


class InspectionError(Exception):
    """Raised when an uploaded file's header fails server-side inspection."""


@dataclass(frozen=True)
class MagicSignature:
    """Byte pattern that must appear at a fixed offset in the header.

    ``offset`` zero is a plain prefix. Non-zero offsets cover formats whose
    discriminator lives inside the header but not at byte zero — e.g. POSIX
    tar's ``ustar`` field at offset 257, or RIFF/WAVE's ``WAVE`` identifier
    at offset 8.
    """

    offset: int
    pattern: bytes

    def matches(self, header: bytes) -> bool:
        end = self.offset + len(self.pattern)
        if len(header) < end:
            return False
        return header[self.offset : end] == self.pattern


@dataclass(frozen=True)
class FileFormat:
    """An allowed upload format. A format is satisfied iff ALL signatures match.

    Use multiple alternative ``FileFormat`` objects (e.g. in a CTF rule's
    alternatives list) for "any-of" semantics — e.g. JPEG SOI variants,
    libpcap endian/timestamp variants.

    ``os_slug`` is optional because it only applies to agent installer
    formats; other domains omit it.
    """

    extensions: list[str]
    signatures: tuple[MagicSignature, ...]
    description: str
    os_slug: str | None = None

    @property
    def magic_bytes(self) -> bytes:
        """Convenience: the offset-zero signature's pattern, or empty bytes.

        Provided so single-prefix formats can still be referenced inline
        (e.g. in tests that build a happy-path header from the format).
        """
        for sig in self.signatures:
            if sig.offset == 0:
                return sig.pattern
        return b""

    @property
    def min_header_bytes(self) -> int:
        """Minimum bytes required to evaluate every signature on this format."""
        if not self.signatures:
            return 0
        return max(sig.offset + len(sig.pattern) for sig in self.signatures)


# Full registry of binary signatures referenced anywhere in this module.
# Order does not matter for the negative check; entries cover the formats
# this codebase positively identifies elsewhere. JPEG covers all three SOI
# marker variants explicitly.
BINARY_MAGIC_SIGNATURES: tuple[bytes, ...] = (
    b"\x50\x4b\x03\x04",  # ZIP (local file header)
    b"\x50\x4b\x05\x06",  # ZIP (empty archive)
    b"\x50\x4b\x07\x08",  # ZIP (spanned)
    b"\x1f\x8b",  # GZIP
    b"BZh",  # bzip2
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"GIF8",  # GIF87a/89a
    b"BM",  # BMP
    b"\xff\xd8\xff\xe0",  # JPEG/JFIF
    b"\xff\xd8\xff\xe1",  # JPEG/Exif
    b"\xff\xd8\xff",  # JPEG SOI (generic fallback)
    b"%PDF",  # PDF
    b"MZ",  # PE / Windows executable
    b"\x7fELF",  # ELF (Linux/BSD executable)
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE compound (DOC/XLS/MSI)
    b"!<arch>",  # ar / DEB
    b"\xed\xab\xee\xdb",  # RPM
    b"\xd4\xc3\xb2\xa1",  # libpcap (little-endian, microseconds)
    b"\xa1\xb2\xc3\xd4",  # libpcap (big-endian, microseconds)
    b"\x4d\x3c\xb2\xa1",  # libpcap (little-endian, nanoseconds)
    b"\xa1\xb2\x3c\x4d",  # libpcap (big-endian, nanoseconds)
    b"\x0a\x0d\x0d\x0a",  # pcapng (Section Header Block)
    b"SQLite format 3\x00",  # SQLite v3 database
    b"RIFF",  # RIFF container (WAV/AVI/WEBP)
    b"ID3",  # MP3 with ID3v2 tag
    b"\xff\xfb",  # MP3 MPEG audio frame
    b"\xff\xf3",  # MP3 MPEG audio frame
    b"\xff\xf2",  # MP3 MPEG audio frame
    b"\x30\x82",  # DER ASN.1 SEQUENCE, 2-byte length
    b"\x30\x83",  # DER ASN.1 SEQUENCE, 3-byte length
    b"\x30\x84",  # DER ASN.1 SEQUENCE, 4-byte length
)

# Subset used by `looks_like_known_binary` for the text-negative check.
# Short (≤3 byte) ASCII-printable prefixes (`BM`, `MZ`, `BZh`, `ID3`,
# `RIFF`) are intentionally excluded: they appear at the start of valid
# text uploads (e.g. a Python script `MZ = "marker"`, a doc line
# starting with `BM`) and would otherwise produce cross-domain false
# positives in the experiment-script and CTF TEXT paths. The excluded
# short prefixes can still appear in `BINARY_MAGIC_SIGNATURES` for
# completeness; bytes that aren't valid UTF-8 start bytes (`\xff\xfb`,
# `\xff\xf3`, `\xff\xf2`, `\x30\x82`, `\x30\x83`, `\x30\x84`) are caught
# by the UTF-8 decoder instead.
_TEXT_INCOMPATIBLE_SIGNATURES: tuple[bytes, ...] = (
    b"\x50\x4b\x03\x04",  # ZIP (local file header)
    b"\x50\x4b\x05\x06",  # ZIP (empty archive)
    b"\x50\x4b\x07\x08",  # ZIP (spanned)
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"GIF8",  # GIF
    b"\xff\xd8\xff",  # JPEG SOI (any variant — \xff not valid UTF-8 start)
    b"%PDF-",  # PDF (anchored with dash to reduce ambiguity)
    b"\x7fELF",  # ELF (non-UTF-8 start byte)
    b"\xca\xfe\xba\xbe",  # Java/Mach-O fat (non-UTF-8 start)
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit (non-UTF-8 start)
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit (non-UTF-8 start)
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE compound (non-UTF-8 start)
    b"!<arch>\n",  # ar / DEB (8 bytes, anchored)
    b"\xed\xab\xee\xdb",  # RPM (non-UTF-8 start)
    b"\xd4\xc3\xb2\xa1",  # libpcap LE-microseconds (non-UTF-8 start)
    b"\xa1\xb2\xc3\xd4",  # libpcap BE-microseconds (non-UTF-8 start)
    b"\x4d\x3c\xb2\xa1",  # libpcap LE-nanoseconds (non-UTF-8 start)
    b"\xa1\xb2\x3c\x4d",  # libpcap BE-nanoseconds (non-UTF-8 start)
    b"\x0a\x0d\x0d\x0a",  # pcapng SHB
    b"SQLite format 3\x00",  # SQLite (16 bytes, distinctive)
    b"\x1f\x8b\x08",  # GZIP (3 bytes incl. compression method)
)

# Single-byte DER prefixes that indicate an ASN.1 SEQUENCE with an
# extended length encoding. ``looks_like_der_sequence`` accepts any of
# these followed by the appropriate length octets. Kept separate from
# the binary registry so the text negative check doesn't trip on plain
# ``0x30`` start bytes in unrelated content.
_DER_SEQUENCE_PREFIXES: tuple[bytes, ...] = (
    b"\x30\x81",  # short, 1-byte length
    b"\x30\x82",  # 2-byte length
    b"\x30\x83",  # 3-byte length
    b"\x30\x84",  # 4-byte length
)

_UTF8_BOM = b"\xef\xbb\xbf"


def get_file_extension(filename: str) -> str:
    """Return the file extension including the leading dot, lowercased.

    Recognizes the compound extension ``.tar.gz`` as a single unit.
    """
    lower = filename.lower()
    if lower.endswith(".tar.gz"):
        return ".tar.gz"
    if "." in filename:
        return "." + lower.rsplit(".", 1)[-1]
    return ""


def validate_magic_bytes(header: bytes, fmt: FileFormat) -> None:
    """Confirm every signature on ``fmt`` matches ``header`` at its declared offset.

    Composite formats (RIFF/WAVE = ``RIFF`` at 0 + ``WAVE`` at 8) and offset
    signatures (POSIX tar ``ustar`` at 257) are first-class: list every
    required anchor in ``fmt.signatures`` and the function checks them all.
    """
    if not fmt.signatures:
        raise InspectionError(f"FileFormat {fmt.description} has no signatures configured")
    needed = fmt.min_header_bytes
    if len(header) < needed:
        raise InspectionError(f"Uploaded content is too small to be a valid {fmt.description}")
    for sig in fmt.signatures:
        if not sig.matches(header):
            raise InspectionError(
                f"Uploaded content does not match expected format ({fmt.description}); "
                "the file may be corrupted or mislabeled."
            )


def looks_like_known_binary(header: bytes) -> bool:
    """Return True iff ``header`` starts with a strict text-incompatible signature.

    Consults the curated `_TEXT_INCOMPATIBLE_SIGNATURES` subset rather than
    the full `BINARY_MAGIC_SIGNATURES` registry, so short ASCII-printable
    prefixes (`MZ`, `BM`, `BZh`, `ID3`, `RIFF`) do not false-reject a script
    or text attachment whose first bytes happen to match those patterns.
    """
    if not header:
        return False
    return any(header.startswith(sig) for sig in _TEXT_INCOMPATIBLE_SIGNATURES)


def looks_like_der_sequence(header: bytes) -> bool:
    """Return True iff ``header`` starts with a DER ASN.1 SEQUENCE marker.

    Accepts the common length encodings used by real-world DER-encoded
    crypto material (X.509 certificates, PKCS#1/PKCS#8 keys, PKCS#12).
    """
    return any(header.startswith(prefix) for prefix in _DER_SEQUENCE_PREFIXES)


# PEM armor anchored at the start of the (BOM-stripped, lstripped) header.
# Accepts the standard PEM label characters; case-sensitivity matches the
# RFC 7468 grammar.
_PEM_ARMOR_RE = re.compile(rb"^-----BEGIN [A-Z0-9 ]+-----")


def validate_text_header(header: bytes, *, complete: bool = False) -> None:
    """Confirm ``header`` is non-empty UTF-8 text and not a known binary format.

    A leading UTF-8 BOM is tolerated and stripped before the binary-signature
    check, so a legitimate BOM-prefixed text file does not collide with the
    ``\\xef\\xbb\\xbf`` prefix.

    Set ``complete=True`` when ``header`` is the entire upload body (e.g.
    experiment script uploads, which are capped at 1 MB and validated in full):
    the decoder runs with ``final=True`` so an incomplete trailing multibyte
    sequence is treated as corruption. The default ``complete=False`` is the
    bounded-prefix case used by CTF and agent paths — an incomplete trailing
    codepoint at the end of the inspected prefix is tolerated because the
    full file may complete it.
    """
    if not header:
        raise InspectionError(_EMPTY_CONTENT_MSG)

    body = header[len(_UTF8_BOM) :] if header.startswith(_UTF8_BOM) else header

    if looks_like_known_binary(body):
        raise InspectionError("Uploaded content begins with a known binary signature; expected a text file.")

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        decoder.decode(body, final=complete)
    except UnicodeDecodeError as exc:
        raise InspectionError(_INVALID_UTF8_MSG) from exc


def make_text_stream_validator() -> TextStreamValidator:
    """Return a stateful validator for streaming text uploads chunk-by-chunk.

    Use this when the full upload body is available as an iterable of chunks
    (e.g. the SHA256 loop in CTF's Django-mediated attachment upload). The
    first chunk is checked for a known binary signature; every chunk is fed
    through a UTF-8 incremental decoder; the closing ``finalize()`` call runs
    the decoder with ``final=True`` so an incomplete trailing multibyte
    sequence in the body is rejected as corruption.

    Defends against the prefix-padding bypass: an attacker can no longer
    place valid text in the first N bytes and binary content past N because
    every chunk passes through the same decoder.
    """
    return TextStreamValidator()


@dataclass
class TextStreamValidator:
    """Stateful streaming text validator.

    Created via `make_text_stream_validator`. Feed chunks with ``feed(chunk)``;
    call ``finalize()`` when the stream is exhausted. Both methods raise
    ``InspectionError`` on the first invalid input — there is no recoverable
    state after that.
    """

    _decoder: codecs.IncrementalDecoder | None = None
    _seen_first_chunk: bool = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        if not self._seen_first_chunk:
            # First chunk: run the BOM strip + known-binary check on the
            # prefix (which is what the bounded `validate_text_header` does)
            # before the streaming UTF-8 decode starts.
            body = chunk[len(_UTF8_BOM) :] if chunk.startswith(_UTF8_BOM) else chunk
            if looks_like_known_binary(body):
                raise InspectionError("Uploaded content begins with a known binary signature; expected a text file.")
            self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            self._seen_first_chunk = True
            try:
                self._decoder.decode(body, final=False)
            except UnicodeDecodeError as exc:
                raise InspectionError(_INVALID_UTF8_MSG) from exc
            return
        assert self._decoder is not None
        try:
            self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise InspectionError(_INVALID_UTF8_MSG) from exc

    def finalize(self) -> None:
        if not self._seen_first_chunk or self._decoder is None:
            raise InspectionError(_EMPTY_CONTENT_MSG)
        try:
            self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise InspectionError(_INVALID_UTF8_MSG) from exc


def validate_pem_or_der_header(header: bytes) -> None:
    """Accept either PEM (``-----BEGIN ...``) text or a DER ASN.1 SEQUENCE.

    Used by extensions whose crypto material is delivered in either
    encoding (notably ``.crt`` and ``.key``). The PEM branch requires the
    ``-----BEGIN <LABEL>-----`` armor to appear at the very start of the
    (BOM- and whitespace-stripped) header — text containing the marker
    later in the body does NOT pass. The DER branch checks for the
    ASN.1 SEQUENCE prefix.
    """
    if not header:
        raise InspectionError(_EMPTY_CONTENT_MSG)

    # PEM branch: anchored armor at the start of normalized text.
    body = header[len(_UTF8_BOM) :] if header.startswith(_UTF8_BOM) else header
    stripped = body.lstrip()
    if not looks_like_known_binary(stripped) and _PEM_ARMOR_RE.match(stripped):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        try:
            decoder.decode(stripped, final=False)
        except UnicodeDecodeError:
            pass
        else:
            return

    # DER branch: ASN.1 SEQUENCE prefix.
    if looks_like_der_sequence(header):
        return

    raise InspectionError("Uploaded content is not recognizable as PEM text or DER ASN.1 SEQUENCE.")
