"""RAES creation pins workspace and effective egress policy (#1325, PLAT-238).

These are durable isolation and policy contracts on the authoritative range
creation seam. They deliberately read persisted state and exercise idempotent
replays so an implementation cannot silently discard or re-resolve a binding.
"""

from uuid import uuid4

import pytest

from engine.models import Range
from engine.services import create_raes_range
from engine.services._common import EngineError
from tests.engine.services.test_raes_range import make_compiled_plan

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="raes-ws-persist@e.com", email="raes-ws-persist@e.com")


@pytest.fixture(autouse=True)
def _ecs_noop(settings):
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = ""
    settings.ENGINE_ECS_CLUSTER_ARN = ""


def test_persists_the_exact_workspace_and_effective_egress_mode(user):
    request_id = uuid4()

    create_raes_range(
        request_id=request_id,
        user_id=user.id,
        compiled_plan=make_compiled_plan(),
        workspace_id=7373,
        egress_mode="none",
    )

    persisted = Range.objects.get(request__request_id=request_id)
    assert persisted.workspace_id == 7373
    assert persisted.egress_mode == "none"


def test_distinct_workspace_scopes_remain_distinct(user):
    first_id, second_id = uuid4(), uuid4()

    create_raes_range(
        request_id=first_id,
        user_id=user.id,
        compiled_plan=make_compiled_plan(),
        workspace_id=11,
    )
    create_raes_range(
        request_id=second_id,
        user_id=user.id,
        compiled_plan=make_compiled_plan(),
        workspace_id=22,
    )

    assert Range.objects.get(request__request_id=first_id).workspace_id == 11
    assert Range.objects.get(request__request_id=second_id).workspace_id == 22


def test_refuses_a_missing_workspace_and_persists_nothing(user):
    request_id = uuid4()
    compiled_plan = make_compiled_plan()

    with pytest.raises(EngineError):
        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=compiled_plan,
            workspace_id=None,
        )

    assert not Range.objects.filter(request__request_id=request_id).exists()


def test_replay_cannot_change_workspace_scope(user):
    request_id = uuid4()
    compiled_plan = make_compiled_plan()
    create_raes_range(
        request_id=request_id,
        user_id=user.id,
        compiled_plan=compiled_plan,
        workspace_id=11,
    )

    with pytest.raises(EngineError, match="conflict"):
        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=compiled_plan,
            workspace_id=22,
        )

    assert Range.objects.get(request__request_id=request_id).workspace_id == 11


def test_replay_cannot_change_effective_egress_mode(user):
    request_id = uuid4()
    compiled_plan = make_compiled_plan()
    create_raes_range(
        request_id=request_id,
        user_id=user.id,
        compiled_plan=compiled_plan,
        workspace_id=11,
        egress_mode="none",
    )

    with pytest.raises(EngineError, match="conflict"):
        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=compiled_plan,
            workspace_id=11,
            egress_mode="status-quo",
        )

    assert Range.objects.get(request__request_id=request_id).egress_mode == "none"
