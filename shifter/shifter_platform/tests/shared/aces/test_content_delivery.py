"""Unit tests for the ACES source-backed content delivery contract (#1564, S1).

Drives the pure delivery primitives that the CMS launch side (materialize +
promote) and the transport / provisioner sides consume:

- ``DeliveryBinding``: the server-owned, byte-free identity that rides beside the
  ProvisioningPlan (ADR-032-R3). Transport round-trips fail closed on tamper.
- ``DeliveryProjection``: the author-declared, inventory-validated mapping from a
  content ``source`` identity to a pack-relative input (ADR-034-R6). Resolution is
  exact and fail-closed; no filename / extension / directory-order sniffing.
- The deterministic materializer seam: source-backed ``file`` and ``directory``
  produce reproducible payload bytes; every other shape is non-realizable.
- Content-addressed key derivation.

Pure module: no cloud, no Django, no pack filesystem coupling beyond a local
source path handed to a materializer.
"""

from __future__ import annotations

import hashlib
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from shared.aces.content_delivery import (
    BINDING_VERSION,
    ContentDeliveryError,
    DeliveryBinding,
    DeliveryProjection,
    DeliveryProjectionEntry,
    materialize_payload,
    normalized_storage_key,
    parse_delivery_projection,
    sha256_hex,
)

_DIGEST = "a" * 64


# --- DeliveryBinding -----------------------------------------------------------


def test_binding_transport_roundtrip():
    binding = DeliveryBinding(
        content_address="content-placement.web.flag",
        sha256=_DIGEST,
        storage_key="aces-content/aa/" + _DIGEST,
        byte_count=12,
    )
    assert binding.binding_version == BINDING_VERSION
    restored = DeliveryBinding.from_transport(binding.to_transport())
    assert restored == binding


def test_binding_transport_is_byte_free():
    # The transport shape must never carry payload bytes, URLs, buckets, or paths.
    payload = DeliveryBinding(
        content_address="a", sha256=_DIGEST, storage_key="k/" + _DIGEST, byte_count=1
    ).to_transport()
    assert set(payload) == {"content_address", "sha256", "storage_key", "byte_count", "binding_version"}


def test_feature_binding_v2_uses_resource_identity_not_legacy_content_address():
    binding = DeliveryBinding(
        content_address=None,
        sha256=_DIGEST,
        storage_key="aces-content/aa/" + _DIGEST,
        byte_count=12,
        binding_version=2,
        resource_type="feature-binding",
        resource_address="provision.feature.agent",
        payload_kind="file",
        install_policy="executable",
    )
    payload = binding.to_transport()
    assert "content_address" not in payload
    assert payload["resource_address"] == "provision.feature.agent"
    assert DeliveryBinding.from_transport(payload) == binding


@pytest.mark.parametrize(
    "mutation",
    [
        {"sha256": "notahexdigest"},
        {"sha256": "b" * 63},
        {"byte_count": -1},
        {"binding_version": BINDING_VERSION + 1},
        {"content_address": ""},
        {"storage_key": ""},
    ],
)
def test_binding_from_transport_fails_closed(mutation):
    good = DeliveryBinding(content_address="a", sha256=_DIGEST, storage_key="k/" + _DIGEST, byte_count=1).to_transport()
    good.update(mutation)
    with pytest.raises(ContentDeliveryError):
        DeliveryBinding.from_transport(good)


def test_binding_from_transport_rejects_extra_keys():
    good = DeliveryBinding(content_address="a", sha256=_DIGEST, storage_key="k/" + _DIGEST, byte_count=1).to_transport()
    good["object_url"] = "https://evil.example/leak"
    with pytest.raises(ContentDeliveryError):
        DeliveryBinding.from_transport(good)


# --- key derivation ------------------------------------------------------------


def test_sha256_hex_known_value():
    assert sha256_hex(b"hello world") == hashlib.sha256(b"hello world").hexdigest()


def test_normalized_storage_key_is_content_addressed():
    key = normalized_storage_key("aces-content", _DIGEST)
    assert key == f"aces-content/{_DIGEST[:2]}/{_DIGEST}"


def test_normalized_storage_key_normalizes_prefix():
    assert normalized_storage_key("aces-content/", _DIGEST) == normalized_storage_key("aces-content", _DIGEST)


def test_normalized_storage_key_rejects_bad_digest():
    with pytest.raises(ContentDeliveryError):
        normalized_storage_key("aces-content", "nothex")


def test_normalized_storage_key_rejects_empty_prefix():
    with pytest.raises(ContentDeliveryError):
        normalized_storage_key("", _DIGEST)


# --- projection parsing --------------------------------------------------------


def _projection_dict() -> dict:
    return {
        "version": 1,
        "entries": [
            {
                "source": {"name": "flag-pkg", "version": "1.0.0"},
                "content_type": "file",
                "format": "",
                "input_path": "assets/flag.txt",
            },
            {
                "source": {"name": "seed-tree", "version": "2.1.0"},
                "content_type": "directory",
                "format": "",
                "input_path": "assets/seed",
            },
        ],
    }


def test_parse_projection_valid():
    projection = parse_delivery_projection(_projection_dict())
    assert isinstance(projection, DeliveryProjection)
    entry = projection.resolve(source_name="flag-pkg", source_version="1.0.0", content_type="file", content_format="")
    assert isinstance(entry, DeliveryProjectionEntry)
    assert entry.input_path == "assets/flag.txt"


def test_parse_v2_feature_projection_is_discriminated():
    projection = parse_delivery_projection(
        {
            "version": 2,
            "entries": [
                {
                    "resource_type": "feature-binding",
                    "source": {"name": "agent", "version": "1.0.0"},
                    "feature_type": "artifact",
                    "payload_kind": "file",
                    "install_policy": "executable",
                    "input_path": "assets/agent.bin",
                }
            ],
        }
    )
    entry = projection.resolve_feature(source_name="agent", source_version="1.0.0", feature_type="artifact")
    assert entry.resource_type == "feature-binding"
    assert entry.payload_kind == "file"
    assert entry.install_policy == "executable"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__("version", 99),
        lambda d: d.__setitem__("entries", "not-a-list"),
        lambda d: d.pop("entries"),
        lambda d: d["entries"][0].pop("input_path"),
        lambda d: d["entries"][0].pop("source"),
        lambda d: d["entries"][0].__setitem__("input_path", 123),
        lambda d: d["entries"][0]["source"].pop("name"),
        lambda d: d["entries"][0].__setitem__("content_type", "account"),
    ],
)
def test_parse_projection_fails_closed(mutate):
    d = _projection_dict()
    mutate(d)
    with pytest.raises(ContentDeliveryError):
        parse_delivery_projection(d)


def test_parse_projection_rejects_absolute_or_traversal_input_path():
    for bad in ("/etc/passwd", "../escape", "assets/../../x"):
        d = _projection_dict()
        d["entries"][0]["input_path"] = bad
        with pytest.raises(ContentDeliveryError):
            parse_delivery_projection(d)


def test_parse_projection_rejects_duplicate_keys():
    d = _projection_dict()
    d["entries"].append(dict(d["entries"][0]))
    with pytest.raises(ContentDeliveryError):
        parse_delivery_projection(d)


# --- projection resolution -----------------------------------------------------


def test_resolve_exact_match():
    projection = parse_delivery_projection(_projection_dict())
    entry = projection.resolve(
        source_name="seed-tree", source_version="2.1.0", content_type="directory", content_format=""
    )
    assert entry.input_path == "assets/seed"


def test_resolve_wildcard_version_unique():
    projection = parse_delivery_projection(_projection_dict())
    entry = projection.resolve(source_name="flag-pkg", source_version="*", content_type="file", content_format="")
    assert entry.input_path == "assets/flag.txt"


def test_resolve_wildcard_version_ambiguous_fails_closed():
    d = _projection_dict()
    d["entries"].append(
        {
            "source": {"name": "flag-pkg", "version": "2.0.0"},
            "content_type": "file",
            "format": "",
            "input_path": "assets/flag2.txt",
        }
    )
    projection = parse_delivery_projection(d)
    with pytest.raises(ContentDeliveryError):
        projection.resolve(source_name="flag-pkg", source_version="*", content_type="file", content_format="")


def test_resolve_no_match_fails_closed():
    projection = parse_delivery_projection(_projection_dict())
    with pytest.raises(ContentDeliveryError):
        projection.resolve(source_name="absent", source_version="1.0.0", content_type="file", content_format="")


def test_resolve_type_must_match():
    projection = parse_delivery_projection(_projection_dict())
    with pytest.raises(ContentDeliveryError):
        # flag-pkg is declared as file, not directory
        projection.resolve(source_name="flag-pkg", source_version="1.0.0", content_type="directory", content_format="")


# --- materialization -----------------------------------------------------------


def test_materialize_file_is_identity(tmp_path: Path):
    src = tmp_path / "flag.txt"
    src.write_bytes(b"CTF{deterministic}")
    payload = materialize_payload(content_type="file", content_format="", source_path=src)
    assert payload == b"CTF{deterministic}"


def test_materialize_directory_is_deterministic_tar(tmp_path: Path):
    tree = tmp_path / "seed"
    (tree / "sub").mkdir(parents=True)
    (tree / "b.txt").write_bytes(b"bbb")
    (tree / "a.txt").write_bytes(b"aaa")
    (tree / "sub" / "c.txt").write_bytes(b"ccc")

    first = materialize_payload(content_type="directory", content_format="", source_path=tree)
    second = materialize_payload(content_type="directory", content_format="", source_path=tree)
    assert first == second  # reproducible

    names = []
    with tarfile.open(fileobj=BytesIO(first), mode="r:") as tar:
        for member in tar.getmembers():
            names.append(member.name)
            assert member.uid == 0 and member.gid == 0
            assert member.mtime == 0
    # sorted, relative posix paths, no absolute leakage
    assert names == sorted(names)
    assert all(not n.startswith("/") and ".." not in n for n in names)
    assert "a.txt" in names and "sub/c.txt" in names


def test_materialize_directory_rejects_symlink(tmp_path: Path):
    tree = tmp_path / "seed"
    tree.mkdir()
    (tree / "real.txt").write_bytes(b"x")
    (tree / "link").symlink_to(tree / "real.txt")
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="directory", content_format="", source_path=tree)


def test_materialize_unsupported_type_fails_closed(tmp_path: Path):
    src = tmp_path / "x"
    src.write_bytes(b"x")
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="dataset", content_format="", source_path=src)


def test_materialize_unsupported_format_fails_closed(tmp_path: Path):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4")
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="file", content_format="pdf-generated", source_path=src)


def test_materialize_missing_source_fails_closed(tmp_path: Path):
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="file", content_format="", source_path=tmp_path / "absent")


def test_materialize_file_size_cap_rejects_before_buffering(tmp_path: Path):
    # F2: an oversized file is rejected via its stat size, not after read_bytes.
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 100)
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="file", content_format="", source_path=src, max_bytes=10)


def test_materialize_directory_cumulative_size_cap(tmp_path: Path):
    # F2: cumulative directory member bytes are capped while the tar is built.
    tree = tmp_path / "seed"
    tree.mkdir()
    (tree / "a.bin").write_bytes(b"a" * 60)
    (tree / "b.bin").write_bytes(b"b" * 60)
    with pytest.raises(ContentDeliveryError):
        materialize_payload(content_type="directory", content_format="", source_path=tree, max_bytes=100)


def test_materialize_within_cap_succeeds(tmp_path: Path):
    src = tmp_path / "ok.txt"
    src.write_bytes(b"small")
    assert materialize_payload(content_type="file", content_format="", source_path=src, max_bytes=1000) == b"small"
