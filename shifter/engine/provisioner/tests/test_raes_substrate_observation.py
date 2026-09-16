"""VM claims require actual provider readback for every expected instance."""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from raes_substrate_observation import observe_gce_substrates


def _plan():
    return {
        "project_id": "tenant",
        "zone": "zone-a",
        "instances": [
            {"resource_name": "worker-a", "uuid": "node.a#0"},
            {"resource_name": "worker-b", "uuid": "node.a#1"},
        ],
    }


def test_every_replica_is_read_from_the_selected_tenant():
    get = Mock(
        side_effect=[
            SimpleNamespace(name=name, id=index, machine_type="types/vm")
            for index, name in enumerate(("worker-a", "worker-b"), start=1)
        ]
    )
    result = observe_gce_substrates(_plan(), SimpleNamespace(instances=SimpleNamespace(get=get)))
    assert result == [{"instance_key": f"node.a#{index}", "value": "virtual-machine"} for index in range(2)]
    assert get.call_args_list == [
        call(project="tenant", zone="zone-a", instance=name) for name in ("worker-a", "worker-b")
    ]


@pytest.mark.parametrize(
    "actual",
    [
        None,
        SimpleNamespace(name="foreign", id=1, machine_type="types/vm"),
        SimpleNamespace(name="worker-a", id=0, machine_type="types/vm"),
    ],
)
def test_missing_or_foreign_instance_cannot_prove_a_vm(actual):
    get = Mock(return_value=actual)
    with pytest.raises(ValueError):
        observe_gce_substrates(_plan(), SimpleNamespace(instances=SimpleNamespace(get=get)))


@pytest.mark.parametrize("source_id", ["555", "999"])
def test_prepared_image_identity_is_read_from_the_actual_boot_disk(source_id):
    plan = _plan()
    plan["instances"] = [dict(plan["instances"][0], profile=SimpleNamespace(source_image_id="555"))]
    guest = SimpleNamespace(
        name="worker-a",
        id=1,
        machine_type="types/vm",
        disks=[
            SimpleNamespace(boot=True, source="projects/tenant/zones/zone-a/disks/worker-a"),
        ],
    )
    clients = SimpleNamespace(
        instances=SimpleNamespace(get=Mock(return_value=guest)),
        disks=SimpleNamespace(get=Mock(return_value=SimpleNamespace(source_image_id=source_id))),
    )
    if source_id == "555":
        assert observe_gce_substrates(plan, clients)
        clients.disks.get.assert_called_once_with(project="tenant", zone="zone-a", disk="worker-a")
    else:
        with pytest.raises(ValueError):
            observe_gce_substrates(plan, clients)


@pytest.mark.parametrize("source_id", ["555", "999"])
def test_prepared_source_is_checked_before_creating_a_guest(source_id):
    from raes_substrate_observation import verify_prepared_source

    plan = _plan()
    profile = SimpleNamespace(source_image="projects/tenant/global/images/prepared", source_image_id="555")
    get = Mock(return_value=SimpleNamespace(id=int(source_id), status="READY"))
    clients = SimpleNamespace(images=SimpleNamespace(get=get))
    if source_id == "555":
        verify_prepared_source(plan, {"profile": profile}, clients)
        get.assert_called_once_with(project="tenant", image="prepared")
    else:
        with pytest.raises(ValueError):
            verify_prepared_source(plan, {"profile": profile}, clients)
