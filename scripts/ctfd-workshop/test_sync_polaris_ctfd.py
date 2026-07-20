"""Tests for the Polaris CTFd sync flag/hint reconciliation (issue #702).

Run from this directory:
    python3 -m unittest test_sync_polaris_ctfd -v

The scripts import sibling modules by bare name, so the directory must be on
sys.path; running with `-m unittest` from here satisfies that.
"""

from __future__ import annotations

import unittest

from ctfd_reconcile import ensure_flags, ensure_hints, normalize_flag, reconcile_rows
from polaris_manifest import (
    SUPPORTED_FLAG_TYPES,
    SyncError,
    validate_live_challenge_names,
    validate_manifest,
    verify_challenge_rows,
)
from sync_polaris_ctfd import sync_challenges


class FakeCtfdClient:
    """In-memory CTFd emulator covering challenges, flags, and hints.

    Stateful so reconciliation idempotency is observable across calls.
    """

    def __init__(self) -> None:
        self.challenges: dict[int, dict] = {}
        self.flags: dict[int, dict] = {}
        self.hints: dict[int, dict] = {}
        self.tags: dict[int, dict] = {}
        self._next_id = 1
        self.calls: list[tuple[str, str]] = []

    def _new_id(self) -> int:
        ident = self._next_id
        self._next_id += 1
        return ident

    def seed_challenge(self, name: str, **fields) -> int:
        cid = self._new_id()
        self.challenges[cid] = {"id": cid, "name": name, **fields}
        return cid

    def seed_flag(self, challenge_id: int, *, type: str, content: str, data: str = "") -> int:
        fid = self._new_id()
        self.flags[fid] = {
            "id": fid,
            "challenge_id": challenge_id,
            "type": type,
            "content": content,
            "data": data,
        }
        return fid

    def seed_hint(self, challenge_id: int, *, title: str, content: str) -> int:
        hid = self._new_id()
        self.hints[hid] = {
            "id": hid,
            "challenge_id": challenge_id,
            "title": title,
            "content": content,
        }
        return hid

    def count(self, method: str, prefix: str) -> int:
        return sum(1 for m, path in self.calls if m == method and path.startswith(prefix))

    def get(self, path: str, query: dict | None = None) -> dict:
        self.calls.append(("GET", path))
        parts = path.strip("/").split("/")
        if path == "/flags":
            cid = (query or {}).get("challenge_id")
            return {"data": [dict(f) for f in self.flags.values() if cid is None or f["challenge_id"] == cid]}
        if path == "/challenges":
            return {"data": [dict(c) for c in self.challenges.values()]}
        if path == "/pages":
            return {"data": []}
        if len(parts) == 3 and parts[0] == "challenges" and parts[2] == "flags":
            cid = int(parts[1])
            return {"data": [dict(f) for f in self.flags.values() if f["challenge_id"] == cid]}
        if len(parts) == 3 and parts[0] == "challenges" and parts[2] == "hints":
            cid = int(parts[1])
            return {"data": [dict(h) for h in self.hints.values() if h["challenge_id"] == cid]}
        if len(parts) == 3 and parts[0] == "challenges" and parts[2] == "tags":
            cid = int(parts[1])
            return {"data": [dict(t) for t in self.tags.values() if t["challenge_id"] == cid]}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, body: dict) -> dict:
        self.calls.append(("POST", path))
        store, defaults = {
            "/flags": (self.flags, {"data": ""}),
            "/hints": (self.hints, {}),
            "/tags": (self.tags, {}),
            "/challenges": (self.challenges, {}),
        }[path]
        ident = self._new_id()
        store[ident] = {"id": ident, **defaults, **body}
        return {"success": True, "data": dict(store[ident])}

    def patch(self, path: str, body: dict) -> dict:
        self.calls.append(("PATCH", path))
        parts = path.strip("/").split("/")
        store = {"flags": self.flags, "hints": self.hints, "challenges": self.challenges}[parts[0]]
        store[int(parts[1])].update(body)
        return {"success": True, "data": dict(store[int(parts[1])])}

    def delete(self, path: str) -> dict:
        self.calls.append(("DELETE", path))
        parts = path.strip("/").split("/")
        store = {
            "flags": self.flags,
            "hints": self.hints,
            "tags": self.tags,
            "challenges": self.challenges,
        }[parts[0]]
        store.pop(int(parts[1]), None)
        return {"success": True}


class NormalizeFlagTest(unittest.TestCase):
    """`normalize_flag` aliases canonical FLAG{hex} static flags to an exact
    case-insensitive regex that accepts the wrapped form OR the bare hex.
    Issue #705 — participants who copy only the inner hex stop getting
    rejected. Non-canonical static content and existing regex flags pass
    through unchanged.
    """

    def test_canonical_static_emits_aliased_regex(self) -> None:
        row = normalize_flag({"type": "static", "content": "FLAG{0a5c7e3f91b8d426}"})
        self.assertEqual(
            row,
            {
                "type": "regex",
                "content": r"^(?:FLAG\{0a5c7e3f91b8d426\}|0a5c7e3f91b8d426)$",
                "data": "case_insensitive",
            },
        )

    def test_canonical_static_with_default_type_emits_aliased_regex(self) -> None:
        row = normalize_flag({"content": "FLAG{aaaa1111bbbb2222}"})
        self.assertEqual(row["type"], "regex")
        self.assertEqual(row["data"], "case_insensitive")
        self.assertEqual(
            row["content"], r"^(?:FLAG\{aaaa1111bbbb2222\}|aaaa1111bbbb2222)$"
        )

    def test_non_canonical_static_passthrough(self) -> None:
        # Defensive: validator should catch malformed wrappers before we get
        # here, but the helper itself stays a no-op on shapes it cannot alias.
        row = normalize_flag({"type": "static", "content": "FLAG{abc"})
        self.assertEqual(
            row, {"type": "static", "content": "FLAG{abc", "data": ""}
        )

    def test_short_hex_body_passthrough(self) -> None:
        # Issue #705: only ``FLAG{<16-hex>}`` is the canonical production
        # contract. Well-closed but non-16-hex bodies must NOT be aliased —
        # they would derive a trivially short accepted answer for CTFd.
        # ``validate_manifest`` rejects these upstream; the helper stays
        # defensive by passing them through unchanged.
        row = normalize_flag({"type": "static", "content": "FLAG{aaa}"})
        self.assertEqual(
            row, {"type": "static", "content": "FLAG{aaa}", "data": ""}
        )

    def test_existing_regex_passthrough(self) -> None:
        row = normalize_flag(
            {"type": "regex", "content": "(?i)Kursk Heavy Industries", "data": ""}
        )
        self.assertEqual(
            row,
            {"type": "regex", "content": "(?i)Kursk Heavy Industries", "data": ""},
        )

    def test_uppercase_hex_source_is_preserved(self) -> None:
        # `case_insensitive` on the live row means we do not have to lowercase
        # source content. Keep it verbatim so the canonical FLAG{...} the
        # walkthroughs show is exactly what CTFd matches first.
        row = normalize_flag({"type": "static", "content": "FLAG{ABCDEF0123456789}"})
        self.assertEqual(
            row["content"], r"^(?:FLAG\{ABCDEF0123456789\}|ABCDEF0123456789)$"
        )

    def test_static_without_flag_prefix_passthrough(self) -> None:
        row = normalize_flag({"type": "static", "content": "answer-without-wrapper"})
        self.assertEqual(
            row,
            {"type": "static", "content": "answer-without-wrapper", "data": ""},
        )


class ReconcileRowsTest(unittest.TestCase):
    def test_add_missing_keep_match_delete_stale(self) -> None:
        created: list = []
        matched: list = []
        deleted: list = []
        reconcile_rows(
            source_rows=[{"k": "a"}, {"k": "b"}],
            live_rows=[{"k": "b"}, {"k": "c"}],
            row_key=lambda row: row["k"],
            on_create=created.append,
            on_match=lambda live, src: matched.append((live, src)),
            on_delete=deleted.append,
        )
        self.assertEqual([row["k"] for row in created], ["a"])
        self.assertEqual([src["k"] for _, src in matched], ["b"])
        self.assertEqual([row["k"] for row in deleted], ["c"])


class EnsureFlagsTest(unittest.TestCase):
    def test_creates_every_source_flag(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            flags=[
                {"type": "static", "content": "FLAG{aaaaaaaaaaaaaaaa}"},
                {"type": "static", "content": "FLAG{bbbbbbbbbbbbbbbb}"},
            ],
            dry_run=False,
        )
        # Source content is aliased to a wrapper-or-bare regex (issue #705),
        # so this asserts the aliased shape rather than the source literals.
        # 16-hex bodies are the production contract enforced upstream by
        # ``polaris_manifest.validate_manifest``.
        contents = sorted(f["content"] for f in client.flags.values())
        self.assertEqual(
            contents,
            [
                r"^(?:FLAG\{aaaaaaaaaaaaaaaa\}|aaaaaaaaaaaaaaaa)$",
                r"^(?:FLAG\{bbbbbbbbbbbbbbbb\}|bbbbbbbbbbbbbbbb)$",
            ],
        )
        self.assertEqual(client.count("POST", "/flags"), 2)

    def test_removes_stale_flag(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        # Pre-existing live row matches the new aliased shape so the test
        # exercises stale-row removal under the production-contract
        # ``FLAG{<16-hex>}`` source shape (issue #705).
        client.seed_flag(
            cid,
            type="static",
            content="FLAG{0000000000000001}",
        )
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{0000000000000002}"}],
            dry_run=False,
        )
        self.assertEqual(
            [f["content"] for f in client.flags.values()],
            [r"^(?:FLAG\{0000000000000002\}|0000000000000002)$"],
        )
        self.assertEqual(client.count("DELETE", "/flags/"), 1)
        self.assertEqual(client.count("POST", "/flags"), 1)

    def test_idempotent_resync_makes_no_writes(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        flags = [{"type": "static", "content": "FLAG{aaaaaaaaaaaaaaaa}"}]
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        writes_before = len(client.calls)
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        for method, path in client.calls[writes_before:]:
            self.assertEqual(method, "GET", f"re-sync issued a write: {method} {path}")
        self.assertEqual(
            [f["content"] for f in client.flags.values()],
            [r"^(?:FLAG\{aaaaaaaaaaaaaaaa\}|aaaaaaaaaaaaaaaa)$"],
        )

    def test_dry_run_and_missing_id_make_no_calls(self) -> None:
        client = FakeCtfdClient()
        ensure_flags(
            client,
            challenge_id=5,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{aaaaaaaaaaaaaaaa}"}],
            dry_run=True,
        )
        ensure_flags(
            client,
            challenge_id=None,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{aaaaaaaaaaaaaaaa}"}],
            dry_run=False,
        )
        self.assertEqual(client.calls, [])


class EnsureFlagsBareHexAliasTest(unittest.TestCase):
    """Issue #705 — `ensure_flags` against canonical `FLAG{hex}` source content
    produces a single live CTFd row of `type: regex` that accepts the wrapped
    form or the bare hex. Pre-existing static rows are migrated in one
    idempotent pass.
    """

    def test_canonical_static_creates_aliased_regex_row(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{0a5c7e3f91b8d426}"}],
            dry_run=False,
        )
        rows = list(client.flags.values())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "regex")
        self.assertEqual(row["data"], "case_insensitive")
        self.assertEqual(
            row["content"], r"^(?:FLAG\{0a5c7e3f91b8d426\}|0a5c7e3f91b8d426)$"
        )

    def test_migrates_pre_existing_static_to_aliased_regex(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content="FLAG{aaaa1111bbbb2222}")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{aaaa1111bbbb2222}"}],
            dry_run=False,
        )
        # Stale static row deleted, new aliased regex row created.
        self.assertEqual(client.count("DELETE", "/flags/"), 1)
        self.assertEqual(client.count("POST", "/flags"), 1)
        rows = list(client.flags.values())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "regex")
        self.assertEqual(
            rows[0]["content"],
            r"^(?:FLAG\{aaaa1111bbbb2222\}|aaaa1111bbbb2222)$",
        )

    def test_idempotent_after_migration(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        flags = [{"type": "static", "content": "FLAG{ccccdddd11112222}"}]
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        writes_before = len(client.calls)
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        # Second pass issues only reads, no mutations.
        for method, path in client.calls[writes_before:]:
            self.assertEqual(method, "GET", f"re-sync issued a write: {method} {path}")

    def test_multi_flag_challenge_aliases_each(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Two Flags")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Two Flags",
            flags=[
                {"type": "static", "content": "FLAG{1111222233334444}"},
                {"type": "static", "content": "FLAG{aaaabbbbccccdddd}"},
            ],
            dry_run=False,
        )
        contents = sorted(f["content"] for f in client.flags.values())
        self.assertEqual(
            contents,
            [
                r"^(?:FLAG\{1111222233334444\}|1111222233334444)$",
                r"^(?:FLAG\{aaaabbbbccccdddd\}|aaaabbbbccccdddd)$",
            ],
        )
        for row in client.flags.values():
            self.assertEqual(row["type"], "regex")
            self.assertEqual(row["data"], "case_insensitive")

    def test_existing_regex_flag_passes_through_unchanged(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Follow the Money")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Follow the Money",
            flags=[
                {"type": "regex", "content": "(?i)Kursk Heavy Industries", "data": ""}
            ],
            dry_run=False,
        )
        rows = list(client.flags.values())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "regex")
        self.assertEqual(rows[0]["content"], "(?i)Kursk Heavy Industries")


class EnsureHintsTest(unittest.TestCase):
    def test_create_carries_polymorphic_type(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        ensure_hints(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            hints=[{"content": "look here", "cost": 10}],
            dry_run=False,
        )
        self.assertEqual(len(client.hints), 1)
        for hint in client.hints.values():
            self.assertEqual(hint["type"], "standard")
            self.assertEqual(hint["content"], "look here")
            self.assertEqual(hint["cost"], 10)

    def test_patch_carries_polymorphic_type(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_hint(cid, title="Hint 1", content="stale")
        ensure_hints(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            hints=[{"content": "fresh", "cost": 10}],
            dry_run=False,
        )
        self.assertEqual(client.count("PATCH", "/hints/"), 1)
        self.assertEqual(client.count("POST", "/hints"), 0)
        for hint in client.hints.values():
            self.assertEqual(hint["type"], "standard")
            self.assertEqual(hint["content"], "fresh")

    def test_deletes_stale_hint(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_hint(cid, title="Hint 1", content="keep")
        client.seed_hint(cid, title="Hint 2", content="stale")
        ensure_hints(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            hints=[{"title": "Hint 1", "content": "keep", "cost": 0}],
            dry_run=False,
        )
        self.assertEqual(client.count("DELETE", "/hints/"), 1)
        self.assertEqual({h["title"] for h in client.hints.values()}, {"Hint 1"})


class ValidateManifestTest(unittest.TestCase):
    def _challenge(self, **overrides) -> dict:
        challenge = {
            "id": 1,
            "name": "Company Info",
            "category": "Mission 1 — Boreas",
            # 16-hex body matches the production contract enforced by
            # ``validate_manifest`` (issue #705).
            "flags": [{"type": "static", "content": "FLAG{aaaaaaaaaaaaaaaa}"}],
        }
        challenge.update(overrides)
        return challenge

    def test_valid_manifest_passes(self) -> None:
        validate_manifest([self._challenge(id=1, name="A"), self._challenge(id=2, name="B")])

    def test_rejects_duplicate_id(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest([self._challenge(id=1, name="A"), self._challenge(id=1, name="B")])

    def test_rejects_duplicate_name(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest([self._challenge(id=1, name="A"), self._challenge(id=2, name="A")])

    def test_rejects_missing_category(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest([self._challenge(category="")])

    def test_rejects_empty_flags(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest([self._challenge(flags=[])])

    def test_rejects_unsupported_flag_type(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest([self._challenge(flags=[{"type": "bogus", "content": "x"}])])
        self.assertIn("static", SUPPORTED_FLAG_TYPES)

    def test_rejects_malformed_flag_wrapper(self) -> None:
        # Issue #705: a static flag that *looks* like FLAG{...} but is malformed
        # must fail validation rather than silently bypass the bare-hex alias
        # derivation and ship as plain static content.
        with self.assertRaises(SyncError):
            validate_manifest(
                [self._challenge(flags=[{"type": "static", "content": "FLAG{abc"}])]
            )

    def test_rejects_flag_wrapper_with_non_hex_body(self) -> None:
        with self.assertRaises(SyncError):
            validate_manifest(
                [
                    self._challenge(
                        flags=[{"type": "static", "content": "FLAG{not-hex-here}"}]
                    )
                ]
            )

    def test_rejects_flag_wrapper_with_short_hex_body(self) -> None:
        # Issue #705: the production contract is ``FLAG{<16-hex>}``. Accepting
        # any hex length would let a source like ``FLAG{aaa}`` derive a
        # 3-character bare-hex alias and ship a trivially short accepted
        # answer to CTFd.
        for short_body in ("a", "aaa", "0123456789abcde", "0123456789abcdef0"):
            with self.assertRaises(SyncError):
                validate_manifest(
                    [
                        self._challenge(
                            flags=[
                                {
                                    "type": "static",
                                    "content": f"FLAG{{{short_body}}}",
                                }
                            ]
                        )
                    ]
                )

    def test_accepts_canonical_flag_wrapper(self) -> None:
        validate_manifest(
            [
                self._challenge(
                    flags=[{"type": "static", "content": "FLAG{0a5c7e3f91b8d426}"}]
                )
            ]
        )

    def test_accepts_static_without_flag_prefix(self) -> None:
        # Non-wrapped static content is left alone (no alias derivation), which
        # validation must continue to accept — bare-hex acceptance is opt-in
        # via the FLAG{<hex>} shape.
        validate_manifest(
            [
                self._challenge(
                    flags=[{"type": "static", "content": "answer-without-wrapper"}]
                )
            ]
        )


class ValidateLiveChallengeNamesTest(unittest.TestCase):
    def test_unique_names_pass(self) -> None:
        validate_live_challenge_names([{"name": "A"}, {"name": "B"}])

    def test_duplicate_live_name_rejected(self) -> None:
        with self.assertRaises(SyncError):
            validate_live_challenge_names([{"name": "A"}, {"name": "A"}])


class VerifyChallengeRowsTest(unittest.TestCase):
    _CANONICAL_FLAG = "FLAG{aaaaaaaaaaaaaaaa}"

    def test_passes_when_rows_present(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content=self._CANONICAL_FLAG)
        verify_challenge_rows(
            client,
            challenges=[
                {
                    "name": "Company Info",
                    "flags": [{"type": "static", "content": self._CANONICAL_FLAG}],
                }
            ],
            name_to_live_id={"Company Info": cid},
        )

    def test_fails_when_flag_rows_empty(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        with self.assertRaises(SyncError):
            verify_challenge_rows(
                client,
                challenges=[
                    {
                        "name": "Company Info",
                        "flags": [{"type": "static", "content": self._CANONICAL_FLAG}],
                    }
                ],
                name_to_live_id={"Company Info": cid},
            )

    def test_fails_when_hint_rows_empty(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content=self._CANONICAL_FLAG)
        with self.assertRaises(SyncError):
            verify_challenge_rows(
                client,
                challenges=[
                    {
                        "name": "Company Info",
                        "flags": [{"type": "static", "content": self._CANONICAL_FLAG}],
                        "hints": [{"content": "h", "cost": 0}],
                    }
                ],
                name_to_live_id={"Company Info": cid},
            )


class SyncChallengesTest(unittest.TestCase):
    def test_mission_one_challenge_gets_its_flag(self) -> None:
        """Regression: Missions 1-5 were skipped by the old category allowlist."""
        client = FakeCtfdClient()
        challenges = [
            {
                "id": 1,
                "name": "Company Info",
                "description": "d",
                "category": "Mission 1 — Boreas",
                "value": 100,
                # Canonical 16-hex body (issue #705) so the row hits the
                # bare-hex alias path and asserts the aliased live shape.
                "flags": [{"type": "static", "content": "FLAG{1111111111111111}"}],
                "hints": [{"content": "hint", "cost": 10}],
                "tags": ["recon"],
            }
        ]
        name_to_live_id = sync_challenges(
            client,
            challenges=challenges,
            existing_challenges=[],
            manifest_id_to_name={1: "Company Info"},
            dry_run=False,
        )
        live_id = name_to_live_id["Company Info"]
        flag_contents = [f["content"] for f in client.flags.values() if f["challenge_id"] == live_id]
        self.assertEqual(
            flag_contents,
            [r"^(?:FLAG\{1111111111111111\}|1111111111111111)$"],
        )
        hint_count = sum(1 for h in client.hints.values() if h["challenge_id"] == live_id)
        self.assertEqual(hint_count, 1)


if __name__ == "__main__":
    unittest.main()
