"""Tests for the Polaris CTFd sync flag/hint reconciliation (issue #702).

Run from this directory:
    python3 -m unittest test_sync_polaris_ctfd -v

The scripts import sibling modules by bare name, so the directory must be on
sys.path; running with `-m unittest` from here satisfies that.
"""

from __future__ import annotations

import unittest

from ctfd_reconcile import ensure_flags, ensure_hints, reconcile_rows
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
                {"type": "static", "content": "FLAG{aaa}"},
                {"type": "static", "content": "FLAG{bbb}"},
            ],
            dry_run=False,
        )
        contents = sorted(f["content"] for f in client.flags.values())
        self.assertEqual(contents, ["FLAG{aaa}", "FLAG{bbb}"])
        self.assertEqual(client.count("POST", "/flags"), 2)

    def test_removes_stale_flag(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content="FLAG{old}")
        ensure_flags(
            client,
            challenge_id=cid,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{new}"}],
            dry_run=False,
        )
        self.assertEqual([f["content"] for f in client.flags.values()], ["FLAG{new}"])
        self.assertEqual(client.count("DELETE", "/flags/"), 1)
        self.assertEqual(client.count("POST", "/flags"), 1)

    def test_idempotent_resync_makes_no_writes(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        flags = [{"type": "static", "content": "FLAG{aaa}"}]
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        writes_before = len(client.calls)
        ensure_flags(client, challenge_id=cid, challenge_name="Company Info", flags=flags, dry_run=False)
        for method, path in client.calls[writes_before:]:
            self.assertEqual(method, "GET", f"re-sync issued a write: {method} {path}")
        self.assertEqual([f["content"] for f in client.flags.values()], ["FLAG{aaa}"])

    def test_dry_run_and_missing_id_make_no_calls(self) -> None:
        client = FakeCtfdClient()
        ensure_flags(
            client,
            challenge_id=5,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{aaa}"}],
            dry_run=True,
        )
        ensure_flags(
            client,
            challenge_id=None,
            challenge_name="Company Info",
            flags=[{"type": "static", "content": "FLAG{aaa}"}],
            dry_run=False,
        )
        self.assertEqual(client.calls, [])


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
            "flags": [{"type": "static", "content": "FLAG{aaa}"}],
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


class ValidateLiveChallengeNamesTest(unittest.TestCase):
    def test_unique_names_pass(self) -> None:
        validate_live_challenge_names([{"name": "A"}, {"name": "B"}])

    def test_duplicate_live_name_rejected(self) -> None:
        with self.assertRaises(SyncError):
            validate_live_challenge_names([{"name": "A"}, {"name": "A"}])


class VerifyChallengeRowsTest(unittest.TestCase):
    def test_passes_when_rows_present(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content="FLAG{aaa}")
        verify_challenge_rows(
            client,
            challenges=[{"name": "Company Info", "flags": [{"type": "static", "content": "FLAG{aaa}"}]}],
            name_to_live_id={"Company Info": cid},
        )

    def test_fails_when_flag_rows_empty(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        with self.assertRaises(SyncError):
            verify_challenge_rows(
                client,
                challenges=[{"name": "Company Info", "flags": [{"type": "static", "content": "FLAG{aaa}"}]}],
                name_to_live_id={"Company Info": cid},
            )

    def test_fails_when_hint_rows_empty(self) -> None:
        client = FakeCtfdClient()
        cid = client.seed_challenge("Company Info")
        client.seed_flag(cid, type="static", content="FLAG{aaa}")
        with self.assertRaises(SyncError):
            verify_challenge_rows(
                client,
                challenges=[
                    {
                        "name": "Company Info",
                        "flags": [{"type": "static", "content": "FLAG{aaa}"}],
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
                "flags": [{"type": "static", "content": "FLAG{m1}"}],
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
        self.assertEqual(flag_contents, ["FLAG{m1}"])
        hint_count = sum(1 for h in client.hints.values() if h["challenge_id"] == live_id)
        self.assertEqual(hint_count, 1)


if __name__ == "__main__":
    unittest.main()
