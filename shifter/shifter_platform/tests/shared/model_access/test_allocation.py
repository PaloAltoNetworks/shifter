"""Deterministic model-shard allocation vectors for PLAT-202."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from shared.model_access import AllocationStrategy, ShardWeight
from shared.model_access.allocation import AllocationError, rank_weighted_rendezvous, select_shard

DEPLOYMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
DRAW_ID = UUID("22222222-2222-4222-8222-222222222222")
POLICY_DIGEST = "sha256:" + "0123456789abcdef" * 4


def test_weighted_rendezvous_matches_cross_implementation_golden_vectors():
    path = Path(__file__).parents[5] / "docs/architecture/model-access/weighted-rendezvous-v1-vectors.json"
    vectors = json.loads(path.read_text(encoding="utf-8"))["vectors"]
    for vector in vectors:
        ranked = rank_weighted_rendezvous(
            deployment_id=UUID(vector["deployment_id"]),
            allocation_group_id=UUID(vector["allocation_group_id"]),
            policy_digest=vector["policy_digest"],
            logical_alias=vector["logical_alias"],
            shards=tuple(ShardWeight(**item) for item in vector["shards"]),
        )
        assert [(item.shard_id, item.score_hex) for item in ranked] == [
            (item["shard_id"], item["score_hex"]) for item in vector["ranked"]
        ]


@pytest.mark.parametrize("affinity_id", [DRAW_ID, UUID("33333333-3333-4333-8333-333333333333")])
def test_same_affinity_namespace_is_stable_for_retries(affinity_id):
    args = {
        "deployment_id": DEPLOYMENT_ID,
        "allocation_group_id": affinity_id,
        "policy_digest": POLICY_DIGEST,
        "logical_alias": "coding-main",
        "shards": (ShardWeight(shard_id="a", weight=1), ShardWeight(shard_id="b", weight=2)),
    }
    expected = rank_weighted_rendezvous(**args)
    assert rank_weighted_rendezvous(**args) == expected


def test_fixed_v1_requires_exactly_one_shard():
    shards = (ShardWeight(shard_id="a", weight=1), ShardWeight(shard_id="b", weight=1))
    with pytest.raises(AllocationError) as exc:
        select_shard(
            strategy=AllocationStrategy.FIXED_V1,
            deployment_id=DEPLOYMENT_ID,
            allocation_group_id=DRAW_ID,
            policy_digest=POLICY_DIGEST,
            logical_alias="coding-main",
            shards=shards,
        )
    assert exc.value.code == "allocation.fixed_cardinality"


@pytest.mark.parametrize(
    "shards,code",
    [
        ((), "allocation.empty_shards"),
        (tuple(ShardWeight(shard_id=f"s-{index}", weight=1) for index in range(33)), "allocation.too_many_shards"),
    ],
)
def test_weighted_v1_enforces_shard_count_bounds(shards, code):
    with pytest.raises(AllocationError) as exc:
        rank_weighted_rendezvous(
            deployment_id=DEPLOYMENT_ID,
            allocation_group_id=DRAW_ID,
            policy_digest=POLICY_DIGEST,
            logical_alias="coding-main",
            shards=shards,
        )
    assert exc.value.code == code


def test_ascii_shard_id_is_required():
    with pytest.raises(ValueError):
        ShardWeight(shard_id="vértex", weight=1)


@pytest.mark.parametrize("field", ["deployment_id", "allocation_group_id"])
def test_allocation_rejects_non_uuid_identities(field):
    args = {
        "deployment_id": DEPLOYMENT_ID,
        "allocation_group_id": DRAW_ID,
        "policy_digest": POLICY_DIGEST,
        "logical_alias": "coding-main",
        "shards": (ShardWeight(shard_id="a", weight=1),),
    }
    args[field] = str(args[field])
    with pytest.raises(AllocationError) as exc:
        rank_weighted_rendezvous(**args)
    assert exc.value.code == "allocation.invalid_uuid"


def test_equal_scores_break_ties_by_ascending_ascii_shard_id(monkeypatch):
    monkeypatch.setattr("shared.model_access.allocation._slot_score", lambda *args, **kwargs: 7)
    ranked = rank_weighted_rendezvous(
        deployment_id=DEPLOYMENT_ID,
        allocation_group_id=DRAW_ID,
        policy_digest=POLICY_DIGEST,
        logical_alias="coding-main",
        shards=(ShardWeight(shard_id="z", weight=1), ShardWeight(shard_id="a", weight=1)),
    )
    assert [item.shard_id for item in ranked] == ["a", "z"]
