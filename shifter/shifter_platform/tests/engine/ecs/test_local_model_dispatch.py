"""Local workers must see committed generation, input, and model allocation rows."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.db import connections, transaction

from engine.ecs import start_raes_range_provisioning
from engine.models import ModelAllocation, OperationInput, ProvisionerLaunchIntent

from ..services.test_model_allocation_launch import prepared_launch

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("rollback", [False, True])
def test_local_model_launch_starts_only_after_outer_commit(
    django_user_model, settings, tmp_path, monkeypatch, rollback
):
    request = prepared_launch(django_user_model)
    (tmp_path / "main.py").write_text("# first-party process boundary fixture\n")
    settings.PROVISIONER_PATH = str(tmp_path)
    settings.LOCAL_PROVISIONER = "subprocess"
    calls = []

    def committed_rows():
        try:
            return (
                ModelAllocation.objects.count(),
                OperationInput.objects.count(),
                ProvisionerLaunchIntent.objects.count(),
            )
        finally:
            connections.close_all()

    def spawn(command, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(committed_rows).result(timeout=10) == (1, 1, 1)
        assert "--operation-id" in command
        calls.append(command)
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr("subprocess.Popen", spawn)
    with transaction.atomic():
        assert start_raes_range_provisioning(request.request_id)
        assert not calls
        if rollback:
            transaction.set_rollback(True)
    assert len(calls) == (0 if rollback else 1)
    assert ModelAllocation.objects.count() == (0 if rollback else 1)
    assert ProvisionerLaunchIntent.objects.count() == (0 if rollback else 1)
