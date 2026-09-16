"""Version rollout and semantic metadata must fail before realization."""

from copy import deepcopy

import pytest

from raes_plan import RaesPlanError, parse_plan


def _plan():
    return {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v2",
        "raes_version": "3.5.0",
        "resources": {},
        "operations": [],
        "realization_authority": [],
        "realization_constraints": [],
        "realization_envelope": None,
        "backend_realization_envelope": None,
        "operation_id": None,
    }


def _semantic_plan():
    plan = _plan()
    address = "provision.node.web"
    payload = {"name": "web", "spec": {"node": {"type": "compute"}, "infrastructure": {}}}
    plan["resources"] = {
        address: {
            "address": address,
            "resource_type": "node",
            "payload": payload,
            "refresh_dependencies": [],
            "ordering_dependencies": [],
        }
    }
    plan["realization_authority"] = [
        {
            "address": address,
            "field_path": "spec.node.resources.cpu",
            "domain": "field-cpu",
            "requirement_kind": "open",
            "payload_pointer": "/spec/node/resources/cpu",
            "mode": "open",
            "source": "authored-leaf",
        }
    ]
    plan["realization_constraints"] = [
        {
            "address": address,
            "field_path": "spec.node.type",
            "concern": "compute-substrate",
            "posture": "open",
            "value_domain": None,
            "governing_scope": "scenario",
            "provenance": "authored",
        }
    ]
    plan["operations"] = [
        {
            "address": address,
            "resource_type": "node",
            "action": "create",
            "payload": deepcopy(payload),
            "refresh_dependencies": [],
            "ordering_dependencies": [],
        }
    ]
    return plan


def test_new_transport_is_accepted():
    assert parse_plan(_plan()).raes_version == "3.5.0"


def test_populated_semantic_metadata_is_accepted():
    parsed = parse_plan(_semantic_plan())
    assert [node.address for node in parsed.nodes] == ["provision.node.web"]


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda row: row.pop("domain"), "invalid fields"),
        (lambda row: row.update(extra="value"), "invalid fields"),
        (lambda row: row.update(field_path=""), "invalid identity"),
        (lambda row: row.update(address="provision.node.missing"), "invalid resource identity"),
        (lambda row: row.update(mode="preferred"), "unsupported posture"),
        (lambda row: row.update(source="backend-invented"), "unsupported source"),
        (lambda row: row.update(payload_pointer="spec/node"), "invalid payload pointer"),
        (lambda row: row.update(bounds=[{"minimum": 1}]), "bounds require unsupported"),
        (lambda row: row.update(provenance={}), "malformed optional metadata"),
    ],
)
def test_authority_rows_fail_closed_for_each_guarded_condition(change, error):
    plan = _semantic_plan()
    change(plan["realization_authority"][0])
    with pytest.raises(RaesPlanError, match=error):
        parse_plan(plan)


def test_authority_rows_reject_duplicate_resource_field_identity():
    plan = _semantic_plan()
    plan["realization_authority"].append(deepcopy(plan["realization_authority"][0]))
    with pytest.raises(RaesPlanError, match="invalid resource identity"):
        parse_plan(plan)


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda row: row.update(concern="network"), "unsupported constraint"),
        (lambda row: row.update(address=3), "invalid resource identity"),
        (lambda row: row.update(address="provision.node.missing"), "invalid resource identity"),
        (lambda row: row.update(posture="exact", value_domain=None), "supported substrate domain"),
        (
            lambda row: row.update(posture="exact", value_domain={"kind": "exact", "value": "container"}),
            "do not permit",
        ),
        (
            lambda row: row.update(posture="constrained", value_domain={"kind": "enum", "values": ["container"]}),
            "do not permit",
        ),
        (
            lambda row: row.update(posture="preferred", value_domain={"kind": "exact", "value": "virtual-machine"}),
            "do not permit",
        ),
    ],
)
def test_constraint_rows_fail_closed_for_each_guarded_condition(change, error):
    plan = _semantic_plan()
    change(plan["realization_constraints"][0])
    with pytest.raises(RaesPlanError, match=error):
        parse_plan(plan)


def test_constraint_rows_reject_duplicate_resource_identity():
    plan = _semantic_plan()
    plan["realization_constraints"].append(deepcopy(plan["realization_constraints"][0]))
    with pytest.raises(RaesPlanError, match="invalid resource identity"):
        parse_plan(plan)


@pytest.mark.parametrize(
    "posture,value_domain",
    [
        ("exact", {"kind": "exact", "value": "virtual-machine"}),
        ("constrained", {"kind": "enum", "values": ["container", "virtual-machine"]}),
    ],
)
def test_supported_exact_and_constrained_vm_domains_are_accepted(posture, value_domain):
    plan = _semantic_plan()
    plan["realization_constraints"][0].update(posture=posture, value_domain=value_domain)
    assert parse_plan(plan).nodes[0].address == "provision.node.web"


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda plan, row: row.update(address="provision.node.missing"), "unknown resource"),
        (lambda plan, row: row.update(payload={"name": "other"}), "resource payloads"),
        (lambda plan, row: row.update(resource_type="network"), "resource types"),
        (lambda plan, row: row.update(action="update"), "unsupported incremental"),
        (lambda plan, row: row.update(refresh_dependencies={}), "dependencies must be address lists"),
        (lambda plan, row: row.update(ordering_dependencies=[1]), "dependencies must be address lists"),
        (
            lambda plan, row: row.update(refresh_dependencies=["provision.node.web"]),
            "fresh-create ordering",
        ),
        (
            lambda plan, row: (
                plan["resources"][row["address"]].update(refresh_dependencies=["provision.node.web"]),
                row.update(ordering_dependencies=["provision.node.web"]),
            ),
            "refresh_dependencies require fresh-create ordering",
        ),
        (
            lambda plan, row: row.update(ordering_dependencies=["provision.node.missing"]),
            "complete plan",
        ),
    ],
)
def test_operation_rows_fail_closed_for_each_guarded_condition(change, error):
    plan = _semantic_plan()
    change(plan, plan["operations"][0])
    with pytest.raises(RaesPlanError, match=error):
        parse_plan(plan)


def test_operation_rows_reject_duplicate_resource_identity():
    plan = _semantic_plan()
    plan["operations"].append(deepcopy(plan["operations"][0]))
    with pytest.raises(RaesPlanError, match="duplicate resource identities"):
        parse_plan(plan)


def _selected_carrier():
    digest = "sha256:" + "1" * 64
    configuration_digest = "sha256:" + "2" * 64
    return {
        "schema_version": "realization-envelope/v1",
        "contract_id": "realization-envelope-v1",
        "id": "selected",
        "expression": {},
        "configuration": {"configuration_digest": configuration_digest},
        "concerns": [],
        "digest": digest,
    }, {
        "contract_id": "realization-envelope-v1",
        "envelope_id": "selected",
        "schema_version": "realization-envelope/v1",
        "digest": digest,
        "configuration_digest": configuration_digest,
    }


def test_runtime_selected_carrier_must_match_plan_identity():
    plan = _plan()
    carrier, identity = _selected_carrier()
    plan["backend_realization_envelope"] = carrier
    plan["realization_envelope"] = identity

    assert parse_plan(plan).raes_version == "3.5.0"

    plan["backend_realization_envelope"]["digest"] = "sha256:" + "3" * 64
    with pytest.raises(RaesPlanError, match="diverges"):
        parse_plan(plan)


@pytest.mark.parametrize("field", ["operations", "realization_authority", "realization_constraints"])
@pytest.mark.parametrize("value", [None, {}, "invalid", [False]])
def test_malformed_semantic_metadata_is_not_ignored(field, value):
    plan = _plan()
    plan[field] = value
    with pytest.raises(RaesPlanError, match=field):
        parse_plan(plan)


def test_old_producer_is_cleanup_only_and_input_is_not_rewritten():
    old = {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v1",
        "raes_version": "2.0.0",
        "resources": {},
    }
    before = deepcopy(old)
    with pytest.raises(RaesPlanError):
        parse_plan(old)
    assert parse_plan(old, cleanup_only=True).raes_version == "2.0.0"
    assert old == before


def test_cleanup_does_not_accept_an_unreviewed_producer():
    old = {
        "kind": "raes_provisioning_plan",
        "contract_version": "raes-provisioning-plan-v1",
        "raes_version": "2.9.0",
        "resources": {},
    }
    with pytest.raises(RaesPlanError):
        parse_plan(old, cleanup_only=True)


def test_old_cleanup_preserves_resource_names_and_public_key_secret_identity():
    from raes_plan_contract import prepare_envelope

    old = _plan()
    old.update(contract_version="raes-provisioning-plan-v1", raes_version="2.0.0")
    old["resources"] = {
        "provision.node.web": {
            "address": "provision.node.web",
            "domain": "provisioning",
            "resource_type": "node",
            "payload": {"os_family": "linux", "spec": {"node": {"type": "vm"}}},
        },
        "provision.account.login": {
            "address": "provision.account.login",
            "domain": "provisioning",
            "resource_type": "account-placement",
            "payload": {"spec": {"auth_method": "publickey"}},
        },
    }
    before = deepcopy(old)
    view = prepare_envelope(old, cleanup_only=True)
    assert view["resources"]["provision.node.web"]["payload"]["name"] == "web"
    assert view["resources"]["provision.account.login"]["payload"]["spec"]["auth_method"] == "key"
    assert view["raes_version"] == "2.0.0"
    assert old == before
