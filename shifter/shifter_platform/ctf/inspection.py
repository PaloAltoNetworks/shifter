"""Server-side header inspection for CTF challenge file attachments.

Each whitelisted extension lives in one of four categories:

- ``MAGIC``: the header must positively match one of the allowed
  ``FileFormat`` alternatives (each alternative is itself a list of
  ``MagicSignature`` anchors that all must match). Covers PNG, ZIP, PDF,
  ELF, PE, libpcap, pcapng, the POSIX ``tar`` ustar marker at offset 257,
  and composite formats like RIFF/WAVE.
- ``TEXT``: header must decode as UTF-8 and must not match any known
  binary signature (``.txt``, ``.md``, ``.json``, ``.py``, ...).
- ``PEM_OR_DER``: header must be either PEM text (``-----BEGIN ...``) or
  a DER ASN.1 SEQUENCE. Used for ``.crt`` and ``.key`` which legitimately
  ship in either encoding.
- ``OPAQUE``: header inspection does not apply. Raw-byte containers like
  ``.bin``, ``.raw``, ``.dd``, ``.mem``, ``.img``, ``.iso``, ``.vmdk`` are
  accepted as-is because magic bytes are either at large offsets (ISO 9660
  lives at 0x8001) or absent. The extension allowlist and size limit
  remain the only guards for these formats — an explicit security
  trade-off CTF accepts to support forensics-style challenges.

The registry intentionally lives next to ``ctf.s3.ALLOWED_EXTENSIONS`` rather
than in ``shared/`` because every CTF extension's category is a domain
decision, not a cross-cutting one. The dataclass, signature, and pure-bytes
comparators *are* shared (`shared.uploads.inspection`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from shared.uploads.inspection import (
    FileFormat,
    InspectionError,
    MagicSignature,
    TextStreamValidator,
    make_text_stream_validator,
    validate_magic_bytes,
    validate_pem_or_der_header,
    validate_text_header,
)


class CTFInspectionError(Exception):
    """Raised when a CTF attachment header fails server-side inspection."""


class _Category(Enum):
    MAGIC = "magic"
    TEXT = "text"
    PEM_OR_DER = "pem_or_der"
    OPAQUE = "opaque"


@dataclass(frozen=True)
class _CTFRule:
    category: _Category
    description: str
    # For MAGIC: one or more acceptable FileFormat alternatives. At least one
    # alternative's signatures must all match.
    alternatives: tuple[FileFormat, ...] = field(default_factory=tuple)


def _fmt(description: str, signatures: tuple[MagicSignature, ...]) -> FileFormat:
    """Build an internal CTF FileFormat (extensions are tracked by the rule key)."""
    return FileFormat(extensions=[], signatures=signatures, description=description)


# Magic signatures used by ``MAGIC`` alternatives.
_PNG = _fmt("PNG image", (MagicSignature(0, b"\x89PNG\r\n\x1a\n"),))
_GIF = _fmt("GIF image", (MagicSignature(0, b"GIF8"),))
_BMP = _fmt("BMP image", (MagicSignature(0, b"BM"),))
_JPEG_ALTERNATIVES = (
    _fmt("JPEG/JFIF", (MagicSignature(0, b"\xff\xd8\xff\xe0"),)),
    _fmt("JPEG/Exif", (MagicSignature(0, b"\xff\xd8\xff\xe1"),)),
    _fmt("JPEG (generic SOI)", (MagicSignature(0, b"\xff\xd8\xff"),)),
)
_PDF = _fmt("PDF document", (MagicSignature(0, b"%PDF"),))
_PE = _fmt("PE executable", (MagicSignature(0, b"MZ"),))
_ELF = _fmt("ELF binary", (MagicSignature(0, b"\x7fELF"),))
_GZIP = _fmt("Gzip", (MagicSignature(0, b"\x1f\x8b"),))
_ZIP_ALTERNATIVES = (
    _fmt("ZIP (local file header)", (MagicSignature(0, b"\x50\x4b\x03\x04"),)),
    _fmt("ZIP (empty archive)", (MagicSignature(0, b"\x50\x4b\x05\x06"),)),
    _fmt("ZIP (spanned)", (MagicSignature(0, b"\x50\x4b\x07\x08"),)),
)
_BZIP2 = _fmt("bzip2", (MagicSignature(0, b"BZh"),))
_7Z = _fmt("7-Zip", (MagicSignature(0, b"\x37\x7a\xbc\xaf\x27\x1c"),))
_SQLITE = _fmt("SQLite database", (MagicSignature(0, b"SQLite format 3\x00"),))
_PCAP_ALTERNATIVES = (
    _fmt("libpcap (LE, microseconds)", (MagicSignature(0, b"\xd4\xc3\xb2\xa1"),)),
    _fmt("libpcap (BE, microseconds)", (MagicSignature(0, b"\xa1\xb2\xc3\xd4"),)),
    _fmt("libpcap (LE, nanoseconds)", (MagicSignature(0, b"\x4d\x3c\xb2\xa1"),)),
    _fmt("libpcap (BE, nanoseconds)", (MagicSignature(0, b"\xa1\xb2\x3c\x4d"),)),
)
_PCAPNG = _fmt("pcapng (Section Header Block)", (MagicSignature(0, b"\x0a\x0d\x0d\x0a"),))
# RIFF/WAVE is a composite: RIFF chunk at offset 0, WAVE format identifier at
# offset 8 (after the 4-byte container size). Requiring both rejects RIFF
# containers carrying AVI/WEBP/etc.
_WAV = _fmt(
    "WAV audio (RIFF/WAVE)",
    (
        MagicSignature(0, b"RIFF"),
        MagicSignature(8, b"WAVE"),
    ),
)
_MP3_ALTERNATIVES = (
    _fmt("MP3 (ID3v2 tag)", (MagicSignature(0, b"ID3"),)),
    _fmt("MP3 frame (FFFB)", (MagicSignature(0, b"\xff\xfb"),)),
    _fmt("MP3 frame (FFF3)", (MagicSignature(0, b"\xff\xf3"),)),
    _fmt("MP3 frame (FFF2)", (MagicSignature(0, b"\xff\xf2"),)),
)
# POSIX tar puts ``ustar`` at offset 257 of the first block. Pre-POSIX
# (v7) tar has no magic at all and so cannot be positively identified
# within a bounded header read; we accept it via OPAQUE-like fallback by
# treating ``.tar`` as MAGIC-with-ustar — pre-POSIX tar uploads will need
# to use ``.bin`` (which the allowlist already permits) or be repacked.
_TAR_POSIX = _fmt(
    "POSIX tar (ustar)",
    (MagicSignature(257, b"ustar"),),
)
# PKCS#12 archives. The DER ASN.1 SEQUENCE marker at offset 0 is the strongest
# signal achievable inside a bounded header read; proving PKCS#12 specifically
# requires decoding the SEQUENCE (version + AuthSafe + MacData), which is an
# ASN.1 parser and out of scope for this layer.
_PKCS12_ALTERNATIVES = (
    _fmt("PKCS#12 (DER, 2-byte length)", (MagicSignature(0, b"\x30\x82"),)),
    _fmt("PKCS#12 (DER, 3-byte length)", (MagicSignature(0, b"\x30\x83"),)),
    _fmt("PKCS#12 (DER, 4-byte length)", (MagicSignature(0, b"\x30\x84"),)),
)


_RULES: dict[str, _CTFRule] = {
    # Archives
    ".zip": _CTFRule(_Category.MAGIC, "ZIP archive", _ZIP_ALTERNATIVES),
    ".gz": _CTFRule(_Category.MAGIC, "Gzip archive", (_GZIP,)),
    ".tgz": _CTFRule(_Category.MAGIC, "Gzip-compressed tar", (_GZIP,)),
    ".tar": _CTFRule(_Category.MAGIC, "POSIX tar archive", (_TAR_POSIX,)),
    ".bz2": _CTFRule(_Category.MAGIC, "bzip2 archive", (_BZIP2,)),
    ".7z": _CTFRule(_Category.MAGIC, "7-Zip archive", (_7Z,)),
    # Images
    ".png": _CTFRule(_Category.MAGIC, "PNG image", (_PNG,)),
    ".jpg": _CTFRule(_Category.MAGIC, "JPEG image", _JPEG_ALTERNATIVES),
    ".jpeg": _CTFRule(_Category.MAGIC, "JPEG image", _JPEG_ALTERNATIVES),
    ".gif": _CTFRule(_Category.MAGIC, "GIF image", (_GIF,)),
    ".bmp": _CTFRule(_Category.MAGIC, "BMP image", (_BMP,)),
    ".svg": _CTFRule(_Category.TEXT, "SVG (XML) image"),  # SVG is XML text
    # Documents
    ".pdf": _CTFRule(_Category.MAGIC, "PDF document", (_PDF,)),
    # Executables
    ".exe": _CTFRule(_Category.MAGIC, "PE executable", (_PE,)),
    ".dll": _CTFRule(_Category.MAGIC, "PE library", (_PE,)),
    ".elf": _CTFRule(_Category.MAGIC, "ELF binary", (_ELF,)),
    ".so": _CTFRule(_Category.MAGIC, "ELF shared object", (_ELF,)),
    ".out": _CTFRule(_Category.OPAQUE, "compiled output binary"),
    # Network captures
    ".pcap": _CTFRule(_Category.MAGIC, "libpcap capture", _PCAP_ALTERNATIVES),
    ".pcapng": _CTFRule(_Category.MAGIC, "pcapng capture", (_PCAPNG,)),
    ".cap": _CTFRule(_Category.MAGIC, "packet capture", (*_PCAP_ALTERNATIVES, _PCAPNG)),
    # Databases
    ".sqlite": _CTFRule(_Category.MAGIC, "SQLite database", (_SQLITE,)),
    ".db": _CTFRule(_Category.MAGIC, "SQLite database", (_SQLITE,)),
    ".sql": _CTFRule(_Category.TEXT, "SQL script"),
    # Crypto / certs — PKCS#12 archives are DER binary; .crt and .key
    # legitimately ship in either PEM or DER encoding.
    ".p12": _CTFRule(_Category.MAGIC, "PKCS#12 (DER)", _PKCS12_ALTERNATIVES),
    ".pfx": _CTFRule(_Category.MAGIC, "PKCS#12 (DER)", _PKCS12_ALTERNATIVES),
    ".pem": _CTFRule(_Category.TEXT, "PEM-encoded crypto material"),
    ".crt": _CTFRule(_Category.PEM_OR_DER, "PEM or DER certificate"),
    ".key": _CTFRule(_Category.PEM_OR_DER, "PEM or DER private key"),
    # Audio
    ".wav": _CTFRule(_Category.MAGIC, "WAV audio (RIFF/WAVE)", (_WAV,)),
    ".mp3": _CTFRule(_Category.MAGIC, "MP3 audio", _MP3_ALTERNATIVES),
    # Text / docs
    ".txt": _CTFRule(_Category.TEXT, "plain text"),
    ".md": _CTFRule(_Category.TEXT, "Markdown text"),
    ".csv": _CTFRule(_Category.TEXT, "CSV text"),
    ".json": _CTFRule(_Category.TEXT, "JSON text"),
    ".xml": _CTFRule(_Category.TEXT, "XML text"),
    ".yaml": _CTFRule(_Category.TEXT, "YAML text"),
    ".yml": _CTFRule(_Category.TEXT, "YAML text"),
    ".log": _CTFRule(_Category.TEXT, "log text"),
    ".hex": _CTFRule(_Category.TEXT, "hex dump (text)"),
    # Code
    ".py": _CTFRule(_Category.TEXT, "Python source"),
    ".js": _CTFRule(_Category.TEXT, "JavaScript source"),
    ".c": _CTFRule(_Category.TEXT, "C source"),
    ".cpp": _CTFRule(_Category.TEXT, "C++ source"),
    ".h": _CTFRule(_Category.TEXT, "C/C++ header"),
    ".java": _CTFRule(_Category.TEXT, "Java source"),
    ".rb": _CTFRule(_Category.TEXT, "Ruby source"),
    ".sh": _CTFRule(_Category.TEXT, "Shell script"),
    ".ps1": _CTFRule(_Category.TEXT, "PowerShell script"),
    # Raw-byte containers
    ".bin": _CTFRule(_Category.OPAQUE, "raw binary"),
    ".raw": _CTFRule(_Category.OPAQUE, "raw memory/disk image"),
    ".dd": _CTFRule(_Category.OPAQUE, "raw disk image"),
    ".mem": _CTFRule(_Category.OPAQUE, "memory image"),
    ".img": _CTFRule(_Category.OPAQUE, "disk image"),
    ".iso": _CTFRule(_Category.OPAQUE, "ISO 9660 disk image"),
    ".vmdk": _CTFRule(_Category.OPAQUE, "VMDK virtual disk"),
}


def is_text_extension(extension: str) -> bool:
    """Whether the extension's rule expects UTF-8 text content end-to-end.

    Callers (notably `ctf.services.attachment.add_challenge_file`) use this
    to decide whether to plug in a streaming text validator alongside the
    SHA256 loop, so a `valid text prefix + binary tail` upload cannot bypass
    the bounded-header check.
    """
    rule = _RULES.get(extension.lower())
    return rule is not None and rule.category is _Category.TEXT


def new_text_stream_validator() -> TextStreamValidator:
    """Construct the streaming validator used during CTF text uploads."""
    return make_text_stream_validator()


def inspect_attachment_header(header: bytes, extension: str) -> None:
    """Inspect the first bytes of a CTF attachment against its extension's policy.

    Raises ``CTFInspectionError`` if the header does not satisfy the rule.
    """
    ext = extension.lower()
    rule = _RULES.get(ext)
    if rule is None:
        raise CTFInspectionError(
            f"Extension '{extension}' has no inspection rule defined; extension is not in the CTF allowlist."
        )

    if rule.category is _Category.OPAQUE:
        return

    if rule.category is _Category.MAGIC:
        for alternative in rule.alternatives:
            try:
                validate_magic_bytes(header, alternative)
            except InspectionError:
                continue
            else:
                return
        raise CTFInspectionError(
            f"Uploaded content does not match expected format for {ext} "
            f"({rule.description}); the file may be corrupted or mislabeled."
        )

    if rule.category is _Category.PEM_OR_DER:
        try:
            validate_pem_or_der_header(header)
        except InspectionError as exc:
            raise CTFInspectionError(
                f"Uploaded content for {ext} ({rule.description}) is not recognizable PEM or DER: {exc}"
            ) from exc
        return

    # TEXT category
    try:
        validate_text_header(header)
    except InspectionError as exc:
        raise CTFInspectionError(f"Uploaded content for {ext} ({rule.description}) is not valid text: {exc}") from exc


def _verify_rules_match_allowlist() -> None:
    """Module-load parity guard: `_RULES` must align with `ctf.s3.ALLOWED_EXTENSIONS`.

    The runtime path accepts any extension in `ALLOWED_EXTENSIONS` and then
    looks up a rule here. If the two tables drift, uploads either pass the
    extension gate and fail at inspection (false reject) or carry stale
    inspection policy for an extension no longer allowed (silent drift).
    Failing fast at import time prevents either failure mode.
    """
    from ctf.s3 import ALLOWED_EXTENSIONS  # local import to avoid cycle at module top

    rule_keys = set(_RULES)
    missing = ALLOWED_EXTENSIONS - rule_keys
    extra = rule_keys - ALLOWED_EXTENSIONS
    if missing or extra:
        raise RuntimeError(
            "CTF inspection rules out of sync with ctf.s3.ALLOWED_EXTENSIONS: "
            f"missing rules for {sorted(missing)}, extra rules for {sorted(extra)}"
        )


_verify_rules_match_allowlist()
