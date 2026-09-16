"""Provisioner-side extraction of RAES composition placements (ADR-031, ADR-032).

Split out of ``raes_plan`` (Sonar file-size): the value objects and pure accessors
for ``content-placement`` / ``feature-binding`` / ``account-placement`` resources
in the serialized RAES plan. Pure stdlib (no ``raes_*``, no Pydantic), mirroring
the compiler payload shapes; the realizer (``raes_gcp_composition``) turns these
into GCE guest bootstrap.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_PORTABLE_ACCOUNT_USERNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,31}$")
_RESERVED_ACCOUNT_USERNAMES = frozenset({"raes"})


@dataclass(frozen=True)
class RaesPlanContent:
    """A content placement (file/dataset/directory) targeting one node.

    ``text`` is inline file content (realized as a real file by the bootstrap
    composition script). A ``source``-backed ``file``/``directory`` is delivered
    post-boot over an authenticated guest channel with a digest-verified byte-free
    delivery binding (#1564, ``raes_content_delivery``) -- the bootstrap script
    never fetches its bytes. A source-less directory (or any other non-inline,
    non-source-backed shape) still only gets its structural target created by the
    bootstrap composition script.
    """

    name: str
    content_type: str
    target_address: str
    # The compiled plan's own resource address (the key it is stored under in the
    # serialized plan's ``resources`` mapping) -- set post-construction by the
    # ``raes_plan`` builder, mirroring ``RaesPlanAccount.address``. Source-backed
    # delivery (#1564) joins a content item to its byte-free delivery binding by
    # this stable address, never by ``target_address``/``path`` (a node can carry
    # more than one content item, and paths are author-controlled).
    address: str = ""
    path: str | None = None
    destination: str | None = None
    text: str | None = None
    source_name: str | None = None
    file_format: str | None = None
    items: tuple[str, ...] = ()
    sensitive: bool = False


@dataclass(frozen=True)
class RaesPlanAccount:
    """A user account placement targeting one node."""

    username: str
    target_address: str
    address: str = ""
    groups: tuple[str, ...] = ()
    login_shell: str | None = None
    home: str | None = None
    mail: str | None = None
    spn: str | None = None
    auth_method: str = "password"
    # Policy label, not a credential.
    password_strength: str = "medium"  # noqa: S105
    disabled: bool = False
    domain_ref: str | None = None
    domain_id: str | None = None
    ordering_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class RaesPlanFeature:
    """A feature binding (service/artifact/configuration) targeting one node.

    A ``service`` feature realizes as an install+enable step whose package/artifact
    is provided by the baked image or the guest package repo (ADR-032); the backend
    does not fetch it.
    """

    name: str
    feature_type: str
    target_address: str
    address: str = ""
    source_name: str | None = None
    source_version: str | None = None
    destination: str | None = None
    has_environment: bool = False
    ordering_dependencies: tuple[str, ...] = ()


def _mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def _opt_str(value: object) -> str | None:
    """Return a stripped non-empty string, or None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _credential_policy_string(spec: Mapping[str, Any], field: str, default: str) -> str:
    """Preserve omission/default semantics while rejecting explicit malformed values."""
    raw = spec.get(field, "")
    if raw == "":
        return default
    if not isinstance(raw, str) or raw.strip() != raw:
        raise ValueError(f"account {field} must be a canonical string")
    return raw


def _str_tuple(value: object) -> tuple[str, ...]:
    """Return the non-empty strings in a list/tuple value as a tuple."""
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _source_name(spec: Mapping[str, Any]) -> str | None:
    """Return a ``source`` package name from a spec (string shorthand or {name})."""
    source = spec.get("source")
    if isinstance(source, str):
        return _opt_str(source)
    if isinstance(source, Mapping):
        return _opt_str(source.get("name"))
    return None


def _source_version(spec: Mapping[str, Any]) -> str | None:
    """Return an exact authored source version, when present."""
    source = spec.get("source")
    return _opt_str(source.get("version")) if isinstance(source, Mapping) else None


def _content_item_names(raw: object) -> tuple[str, ...]:
    """Return the ``name`` of each dataset item in a content ``items`` list."""
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(name for entry in raw if isinstance(entry, Mapping) and (name := _opt_str(entry.get("name"))))


def build_content(payload: Mapping[str, Any]) -> RaesPlanContent | None:
    """Build an RaesPlanContent from a content-placement payload (None if malformed)."""
    spec = _mapping(payload.get("spec"))
    content_type = _opt_str(spec.get("type"))
    target = _opt_str(payload.get("target_address")) or _opt_str(payload.get("target_node"))
    if content_type is None or target is None:
        return None
    text = spec.get("text")
    return RaesPlanContent(
        name=_opt_str(payload.get("content_name")) or _opt_str(payload.get("name")) or content_type.lower(),
        content_type=content_type.lower(),
        target_address=target,
        path=_opt_str(spec.get("path")),
        destination=_opt_str(spec.get("destination")),
        text=text if isinstance(text, str) else None,
        source_name=_source_name(spec),
        file_format=_opt_str(spec.get("format")),
        items=_content_item_names(spec.get("items")),
        sensitive=spec.get("sensitive") is True,
    )


def build_account(payload: Mapping[str, Any]) -> RaesPlanAccount | None:
    """Build an RaesPlanAccount from an account-placement payload (None if malformed)."""
    spec = _mapping(payload.get("spec"))
    username = _opt_str(spec.get("username")) or _opt_str(payload.get("account_name"))
    target = _opt_str(payload.get("target_address")) or _opt_str(payload.get("node_name"))
    if username is None or target is None:
        return None
    if not _PORTABLE_ACCOUNT_USERNAME.fullmatch(username):
        raise ValueError("account username is not portable across supported guest operating systems")
    if username.casefold() in _RESERVED_ACCOUNT_USERNAMES:
        raise ValueError("account username is reserved for provisioner management")
    return RaesPlanAccount(
        username=username,
        target_address=target,
        groups=_str_tuple(spec.get("groups")),
        login_shell=_opt_str(spec.get("shell")),
        home=_opt_str(spec.get("home")),
        mail=_opt_str(spec.get("mail")),
        spn=_opt_str(spec.get("spn")),
        auth_method=_credential_policy_string(spec, "auth_method", "password"),
        password_strength=_credential_policy_string(spec, "password_strength", "medium"),
        disabled=spec.get("disabled") is True,
        domain_ref=_opt_str(spec.get("domain_ref")),
        domain_id=_opt_str(_mapping(payload.get("domain_topology")).get("domain_id")),
    )


def build_feature(payload: Mapping[str, Any]) -> RaesPlanFeature | None:
    """Build an RaesPlanFeature from a feature-binding payload (None if malformed)."""
    template = _mapping(_mapping(payload.get("spec")).get("template"))
    feature_type = _opt_str(template.get("type"))
    target = _opt_str(payload.get("node_address")) or _opt_str(payload.get("node_name"))
    name = _opt_str(payload.get("feature_name")) or _opt_str(template.get("name"))
    if feature_type is None or target is None or name is None:
        return None
    return RaesPlanFeature(
        name=name,
        feature_type=feature_type.lower(),
        target_address=target,
        source_name=_source_name(template),
        source_version=_source_version(template),
        destination=_opt_str(template.get("destination")),
        has_environment=template.get("environment") not in (None, {}, []),
    )
