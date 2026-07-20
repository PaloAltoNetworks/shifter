"""Tests for the provisioner-side serialized-ACES-plan reader (ADR-031, ADR-032).

The reader consumes the serialized ACES ProvisioningPlan persisted in
range_config and extracts realization intent via accessors mirroring the
reference ACES backend. These tests drive it directly with serialized-plan dicts;
a platform-side drift test compares its extraction against aces_backend_libvirt.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_plan import (
    ACES_PROVISIONING_PLAN_CONTRACT_VERSION,
    ACES_PROVISIONING_PLAN_KIND,
    MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE,
    MINIMUM_ACES_SDL_VERSION,
    AcesPlan,
    AcesPlanError,
    parse_plan,
)


def _resource(address: str, resource_type: str, payload: dict) -> dict:
    return {
        "address": address,
        "domain": "provisioning",
        "resource_type": resource_type,
        "payload": payload,
        "ordering_dependencies": [],
        "refresh_dependencies": [],
    }


def _serialized(
    *resources: dict,
    version: str | None = "0.19.1",
    contract_version: str | None = ACES_PROVISIONING_PLAN_CONTRACT_VERSION,
) -> dict:
    envelope: dict = {
        "kind": ACES_PROVISIONING_PLAN_KIND,
        "resources": {r["address"]: r for r in resources},
    }
    if version is not None:
        envelope["aces_sdl_version"] = version
    if contract_version is not None:
        envelope["contract_version"] = contract_version
    return envelope


def _node_payload(**node_spec) -> dict:
    return {
        "name": "attacker",
        "os_family": "linux",
        "count": 2,
        "spec": {
            "node": {
                "source": {"name": "kali", "version": "2024.1"},
                "resources": {"ram": 2147483648, "cpu": 2},
                **node_spec,
            },
            "infrastructure": {"networks": ["net.default"]},
        },
    }


def _domain_resources() -> tuple[dict, dict, dict, dict, dict, dict]:
    topology = {
        "domain_id": "corp",
        "profile": "active_directory",
        "dns_name": "corp.example",
        "netbios_name": "CORP",
        "authority_account_address": "provision.account.domain-admin",
        "controller_addresses": ["provision.node.dc"],
    }
    network = _resource(
        "provision.network.lan",
        "network",
        {"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.70.0.0/24"}}}},
    )
    controller = _resource(
        "provision.node.dc",
        "node",
        {
            "name": "dc",
            "os_family": "windows",
            "count": 1,
            "spec": {"node": {"os": "windows"}, "infrastructure": {"networks": ["provision.network.lan"]}},
            "domain_topology": {**topology, "role": "controller"},
        },
    )
    member = _resource(
        "provision.node.member",
        "node",
        {
            "name": "member",
            "os_family": "windows",
            "count": 1,
            "spec": {"node": {"os": "windows"}, "infrastructure": {"networks": ["provision.network.lan"]}},
            "domain_topology": {**topology, "role": "member"},
        },
    )
    member["ordering_dependencies"] = ["provision.node.dc"]
    authority = _resource(
        "provision.account.domain-admin",
        "account-placement",
        {
            "account_name": "domain-admin",
            "target_address": "provision.node.dc",
            "spec": {"username": "Administrator", "auth_method": "password", "password_strength": "strong"},
            "domain_topology": {**topology, "role": "controller"},
        },
    )
    service = _resource(
        "provision.account.web-service",
        "account-placement",
        {
            "account_name": "web-service",
            "target_address": "provision.node.member",
            "spec": {
                "username": "svc-web",
                "auth_method": "password",
                "password_strength": "strong",
                "domain_ref": "corp",
                "spn": "HTTP/member.corp.example",
            },
            "domain_topology": {**topology, "role": "member"},
        },
    )
    service["ordering_dependencies"] = ["provision.node.member"]
    local_operator = _resource(
        "provision.account.local-operator",
        "account-placement",
        {
            "account_name": "local-operator",
            "target_address": "provision.node.member",
            "spec": {
                "username": "local-operator",
                "auth_method": "password",
                "password_strength": "strong",
            },
            "domain_topology": {**topology, "role": "member"},
        },
    )
    local_operator["ordering_dependencies"] = ["provision.node.member"]
    return network, controller, member, authority, service, local_operator


class TestParseValid:
    def test_extracts_node_and_network(self):
        plan = _serialized(
            _resource("node.attacker", "node", _node_payload()),
            _resource(
                "net.default",
                "network",
                {
                    "name": "default",
                    "spec": {
                        "infrastructure": {
                            "properties": {"cidr": "10.0.0.0/24", "gateway": "10.0.0.1", "internal": True}
                        }
                    },
                },
            ),
        )
        parsed = parse_plan(plan)
        assert isinstance(parsed, AcesPlan)
        assert parsed.aces_sdl_version == "0.19.1"

        node = parsed.nodes[0]
        assert node.address == "node.attacker"
        assert node.os_family == "linux"
        assert node.count == 2
        assert node.ram_mib == 2048  # 2 GiB bytes -> MiB
        assert node.vcpus == 2
        assert node.image is not None and node.image.name == "kali" and node.image.version == "2024.1"
        assert node.network_addresses == ("net.default",)  # resolved via lookup

        net = parsed.networks[0]
        assert net.cidr == "10.0.0.0/24" and net.gateway == "10.0.0.1" and net.internal is True

    def test_os_family_falls_back_to_spec_node_os(self):
        payload = {"spec": {"node": {"os": "windows"}}}
        parsed = parse_plan(_serialized(_resource("node.dc", "node", payload)))
        assert parsed.nodes[0].os_family == "windows"

    def test_small_ram_treated_as_mib(self):
        payload = {"os_family": "linux", "spec": {"node": {"resources": {"ram": 512}}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].ram_mib == 512

    def test_bare_string_source(self):
        payload = {"os_family": "windows", "spec": {"node": {"source": "win2022-template"}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].image is not None
        assert parsed.nodes[0].image.name == "win2022-template" and parsed.nodes[0].image.version is None

    def test_absent_sizing_and_image_are_none(self):
        payload = {"os_family": "linux", "spec": {"node": {}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        node = parsed.nodes[0]
        assert node.ram_mib is None and node.vcpus is None and node.image is None
        assert node.count == 1  # default

    def test_unresolvable_network_ref_fails_closed(self):
        # ADR-032-R7: a node referencing an undeclared network aborts rather than
        # silently dropping the ref (which would provision a wrong topology).
        payload = {"os_family": "linux", "spec": {"infrastructure": {"networks": ["ghost"]}}}
        serialized = _serialized(_resource("node.a", "node", payload))
        with pytest.raises(AcesPlanError, match="unknown network"):
            parse_plan(serialized)


class TestAclExtraction:
    def _node_with_acls(self, *acls: dict) -> dict:
        payload = {"os_family": "linux", "spec": {"infrastructure": {"acls": list(acls)}}}
        # Declare the network ACL endpoints reference so parse resolves them (ADR-032-R7).
        network = _resource("net.dmz", "network", {"name": "dmz", "spec": {"infrastructure": {"properties": {}}}})
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload), network))
        return parsed.nodes[0]

    def test_extracts_and_normalizes_acl(self):
        node = self._node_with_acls(
            {
                "name": "ssh",
                "action": "allow",
                "direction": "in",
                "protocol": "TCP",
                "ports": [22],
                "from_net": "net.dmz",
            }
        )
        assert len(node.acls) == 1
        acl = node.acls[0]
        assert acl.name == "ssh"
        assert acl.action == "accept"  # allow -> accept
        assert acl.direction == "in"
        assert acl.protocol == "tcp"  # lowercased
        assert acl.ports == (22,)
        assert acl.from_net == "net.dmz" and acl.to_net is None

    def test_defaults_direction_inout_and_wildcard_protocol(self):
        node = self._node_with_acls({"action": "deny"})
        acl = node.acls[0]
        assert acl.action == "drop" and acl.direction == "inout" and acl.protocol == "all"
        assert acl.name == "acl-0"

    def test_missing_action_fails_closed(self):
        with pytest.raises(AcesPlanError, match="missing 'action'"):
            self._node_with_acls({"direction": "in"})

    def test_ports_with_wildcard_protocol_fails_closed(self):
        with pytest.raises(AcesPlanError, match="ports require protocol"):
            self._node_with_acls({"action": "allow", "protocol": "all", "ports": [22]})

    def test_invalid_port_fails_closed(self):
        with pytest.raises(AcesPlanError, match="invalid port"):
            self._node_with_acls({"action": "allow", "protocol": "tcp", "ports": [70000]})

    def test_no_acls_is_empty(self):
        payload = {"os_family": "linux", "spec": {"node": {}}}
        parsed = parse_plan(_serialized(_resource("node.a", "node", payload)))
        assert parsed.nodes[0].acls == ()


class TestCompositionExtraction:
    def _content_resource(self, **spec) -> dict:
        return _resource(
            "content.doc",
            "content-placement",
            {
                "name": "doc",
                "content_name": "doc",
                "target_node": "web",
                "target_address": "provision.node.web",
                "spec": spec,
            },
        )

    def _target_node(self) -> dict:
        # The node every composition placement below targets (provision.node.web);
        # ADR-032-R7 requires composition targets resolve to a declared node.
        return _resource("provision.node.web", "node", {"os_family": "linux", "spec": {"node": {}}})

    def test_extracts_inline_file_content(self):
        plan = parse_plan(
            _serialized(self._content_resource(type="file", path="/srv/x.txt", text="hello"), self._target_node())
        )
        content = plan.content[0]
        assert content.content_type == "file"
        assert content.path == "/srv/x.txt"
        assert content.text == "hello"
        assert content.target_address == "provision.node.web"

    def test_extracts_dataset_items_and_source(self):
        plan = parse_plan(
            _serialized(
                self._content_resource(
                    type="dataset",
                    format="json",
                    source={"name": "seed-pkg"},
                    items=[{"name": "a.json"}, {"name": "b.json"}],
                ),
                self._target_node(),
            )
        )
        content = plan.content[0]
        assert content.content_type == "dataset"
        assert content.source_name == "seed-pkg"
        assert content.items == ("a.json", "b.json")
        assert content.file_format == "json"

    def test_extracts_directory_content(self):
        plan = parse_plan(self._serialized_directory())
        content = plan.content[0]
        assert content.content_type == "directory"
        assert content.destination == "/srv/data"

    def test_content_address_is_the_compiled_resource_address(self):
        # #1564: the provisioner joins a source-backed content item to its
        # byte-free delivery binding by this address (the same address the CMS
        # side reads off the serialized plan's `resources` mapping key) -- never
        # by target_address or path, since a node may carry more than one
        # content item and paths are author-controlled.
        plan = parse_plan(
            _serialized(self._content_resource(type="file", path="/srv/x.txt", text="hello"), self._target_node())
        )
        assert plan.content[0].address == "content.doc"

    def _serialized_directory(self) -> dict:
        return _serialized(self._content_resource(type="directory", destination="/srv/data"), self._target_node())

    def test_extracts_account(self):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "name": "alice",
                "account_name": "alice",
                "node_name": "web",
                "target_address": "provision.node.web",
                "spec": {
                    "username": "alice",
                    "node": "web",
                    "groups": ["ops", "sudo"],
                    "shell": "/bin/bash",
                    "home": "/home/alice",
                    "auth_method": "publickey",
                    "password_strength": "strong",
                    "disabled": False,
                },
            },
        )
        account = parse_plan(_serialized(account_resource, self._target_node())).accounts[0]
        assert account.username == "alice"
        assert account.groups == ("ops", "sudo")
        assert account.login_shell == "/bin/bash"
        assert account.auth_method == "publickey"
        assert account.password_strength == "strong"
        assert account.target_address == "provision.node.web"
        assert account.disabled is False

    def test_account_defaults_to_password_and_medium_strength(self):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice"},
            },
        )

        account = parse_plan(_serialized(account_resource, self._target_node())).accounts[0]

        assert account.auth_method == "password"
        assert account.password_strength == "medium"

    @pytest.mark.parametrize("auth_method", ["kerberos", "PASSWORD", "public-key"])
    def test_rejects_unsupported_account_auth_method(self, auth_method: str):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice", "auth_method": auth_method},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="unsupported account auth_method"):
            parse_plan(serialized)

    @pytest.mark.parametrize("auth_method", [None, 1, [], {}])
    def test_rejects_malformed_explicit_account_auth_method(self, auth_method: object):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice", "auth_method": auth_method},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="auth_method must be a canonical string"):
            parse_plan(serialized)

    @pytest.mark.parametrize("password_strength", ["none", "extreme", "MEDIUM"])
    def test_rejects_unsafe_password_strength(self, password_strength: str):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {
                    "username": "alice",
                    "auth_method": "password",
                    "password_strength": password_strength,
                },
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="unsupported password_strength"):
            parse_plan(serialized)

    @pytest.mark.parametrize("password_strength", [None, 1, [], {}])
    def test_rejects_malformed_explicit_password_strength(self, password_strength: object):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice", "password_strength": password_strength},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="password_strength must be a canonical string"):
            parse_plan(serialized)

    @pytest.mark.parametrize("username", ["a;id", "a'lice", "a lice", "-root", "a" * 33])
    def test_rejects_username_unsafe_for_supported_guest_dialects(self, username: str):
        account_resource = _resource(
            "account.bad",
            "account-placement",
            {
                "account_name": username,
                "target_address": "provision.node.web",
                "spec": {"username": username},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="account username is not portable"):
            parse_plan(serialized)

    @pytest.mark.parametrize("username", ["aces", "ACES"])
    def test_rejects_provisioner_management_username(self, username: str):
        account_resource = _resource(
            "account.management-collision",
            "account-placement",
            {
                "account_name": username,
                "target_address": "provision.node.web",
                "spec": {"username": username},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="reserved for provisioner management"):
            parse_plan(serialized)

    def test_disabled_account_accepts_explicit_no_password_without_generating_blank_login(self):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {
                    "username": "alice",
                    "auth_method": "password",
                    "password_strength": "none",
                    "disabled": True,
                },
            },
        )

        account = parse_plan(_serialized(account_resource, self._target_node())).accounts[0]

        assert account.disabled is True
        assert account.password_strength == "none"

    def test_rejects_mail_in_separate_provisioner_consumer(self):
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice", "mail": "alice@example.com"},
            },
        )

        serialized = _serialized(account_resource, self._target_node())
        with pytest.raises(AcesPlanError, match="account mail is not realized"):
            parse_plan(serialized)

    def test_rejects_spn_without_domain_binding_without_leaking_value(self):
        authored_spn = "HTTP/member.corp.example"
        account_resource = _resource(
            "account.alice",
            "account-placement",
            {
                "account_name": "alice",
                "target_address": "provision.node.web",
                "spec": {"username": "alice", "spn": authored_spn},
            },
        )
        serialized = _serialized(account_resource, self._target_node())

        with pytest.raises(AcesPlanError, match="account spn requires a supported domain binding") as error:
            parse_plan(serialized)

        assert authored_spn not in str(error.value)

    def test_extracts_supported_domain_topology_dependencies_and_account_identity(self):
        network, controller, member, authority, service, local_operator = _domain_resources()

        parsed = parse_plan(_serialized(network, controller, member, authority, service, version="0.23.0"))

        assert parsed.domains[0].domain_id == "corp"
        assert parsed.domains[0].controller_addresses == ("provision.node.dc",)
        assert parsed.domains[0].member_addresses == ("provision.node.member",)
        assert next(node for node in parsed.nodes if node.address == "provision.node.member").ordering_dependencies == (
            "provision.node.dc",
        )
        service_account = next(account for account in parsed.accounts if account.username == "svc-web")
        assert service_account.address == "provision.account.web-service"
        assert service_account.domain_ref == "corp"
        assert service_account.ordering_dependencies == ("provision.node.member",)

        for field, value in (
            ("groups", ["ops"]),
            ("shell", "/bin/bash"),
            ("home", "/home/Administrator"),
        ):
            unsupported_authority = _resource(
                authority["address"],
                authority["resource_type"],
                {
                    **authority["payload"],
                    "spec": {**authority["payload"]["spec"], field: value},
                },
            )
            serialized = _serialized(network, controller, member, unsupported_authority, service, version="0.23.0")
            with pytest.raises(AcesPlanError, match="domain authority account is unsupported"):
                parse_plan(serialized)

        serialized = _serialized(network, controller, member, authority, service, local_operator, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain topology account binding is invalid"):
            parse_plan(serialized)

        inconsistent_member = _resource(
            member["address"],
            member["resource_type"],
            {
                **member["payload"],
                "domain_topology": {**member["payload"]["domain_topology"], "dns_name": "other.example"},
            },
        )
        inconsistent_member["ordering_dependencies"] = member["ordering_dependencies"]
        serialized = _serialized(network, controller, inconsistent_member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain topology identity is inconsistent"):
            parse_plan(serialized)

        malformed_controller = _resource(
            controller["address"],
            controller["resource_type"],
            {**controller["payload"], "domain_topology": "active_directory"},
        )
        serialized = _serialized(network, malformed_controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain topology must be an object"):
            parse_plan(serialized)

        colliding_service = _resource(
            service["address"],
            service["resource_type"],
            {
                **service["payload"],
                "spec": {**service["payload"]["spec"], "username": "Administrator"},
            },
        )
        colliding_service["ordering_dependencies"] = service["ordering_dependencies"]
        serialized = _serialized(network, controller, member, authority, colliding_service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="duplicate domain account identity"):
            parse_plan(serialized)

    @pytest.mark.parametrize(
        "spec_overrides",
        [
            {"auth_method": "publickey"},
            {"password_strength": "none", "disabled": True},
            {"disabled": True},
            {"groups": ["ops"]},
            {"shell": "/bin/bash"},
            {"home": "/home/svc-web"},
            {"username": "a" * 21},
        ],
    )
    def test_rejects_unsupported_domain_account_policy(self, spec_overrides: dict) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        service["payload"]["spec"] = {**service["payload"]["spec"], **spec_overrides}

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain account policy is unsupported"):
            parse_plan(serialized)

    @pytest.mark.parametrize(
        "spn",
        [
            "not-a-service-principal",
            "HTTP/member.corp.example\nHOST/other.corp.example",
            "HTTP/member.corp.example\rHOST/other.corp.example",
        ],
    )
    def test_rejects_malformed_domain_account_spn(self, spn: str) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        service["payload"]["spec"] = {**service["payload"]["spec"], "spn": spn}

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="account spn is invalid") as error:
            parse_plan(serialized)

        assert spn not in str(error.value)

    def test_rejects_unsupported_controller_cardinality(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        controller["payload"]["count"] = 2

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain controller cardinality or operating system is unsupported"):
            parse_plan(serialized)

    def test_rejects_non_windows_domain_member(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        member["payload"]["os_family"] = "linux"

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain member operating system is unsupported"):
            parse_plan(serialized)

    def test_rejects_unreachable_domain_member(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        isolated_network = _resource(
            "provision.network.isolated",
            "network",
            {"name": "isolated", "spec": {"infrastructure": {"properties": {"cidr": "10.80.0.0/24"}}}},
        )
        member["payload"]["spec"] = {
            **member["payload"]["spec"],
            "infrastructure": {"networks": ["provision.network.isolated"]},
        }

        serialized = _serialized(
            network,
            isolated_network,
            controller,
            member,
            authority,
            service,
            version="0.23.0",
        )
        with pytest.raises(AcesPlanError, match="domain member is not reachable from its controller"):
            parse_plan(serialized)

    def test_rejects_member_without_controller_ordering_dependency(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        member["ordering_dependencies"] = []

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain member ordering dependency is missing"):
            parse_plan(serialized)

    def test_rejects_duplicate_case_folded_spn(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        duplicate = _resource(
            "provision.account.api-service",
            "account-placement",
            {
                **service["payload"],
                "account_name": "api-service",
                "spec": {
                    **service["payload"]["spec"],
                    "username": "svc-api",
                    "spn": "http/MEMBER.CORP.EXAMPLE",
                },
            },
        )
        duplicate["ordering_dependencies"] = ["provision.node.member"]

        serialized = _serialized(network, controller, member, authority, service, duplicate, version="0.23.0")
        with pytest.raises(AcesPlanError, match="duplicate account spn"):
            parse_plan(serialized)

    def test_rejects_domain_account_topology_identity_mismatch(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        service["payload"]["domain_topology"] = {
            **service["payload"]["domain_topology"],
            "domain_id": "other",
        }

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain account binding is invalid"):
            parse_plan(serialized)

    def test_rejects_domain_account_target_outside_domain(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        outsider = _resource(
            "provision.node.outsider",
            "node",
            {"name": "outsider", "os_family": "windows", "spec": {"node": {"os": "windows"}}},
        )
        service["payload"]["target_address"] = outsider["address"]

        serialized = _serialized(network, controller, member, outsider, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain account target is invalid"):
            parse_plan(serialized)

    def test_rejects_domain_reference_without_realized_domain(self) -> None:
        network, controller, member, authority, service, _local_operator = _domain_resources()
        service["payload"]["spec"] = {**service["payload"]["spec"], "domain_ref": "ghost"}

        serialized = _serialized(network, controller, member, authority, service, version="0.23.0")
        with pytest.raises(AcesPlanError, match="domain account references an unsupported domain"):
            parse_plan(serialized)

    def test_extracts_service_feature(self):
        feature_resource = _resource(
            "feature.web-app",
            "feature-binding",
            {
                "name": "web-app",
                "feature_name": "web-app",
                "node_name": "web",
                "node_address": "provision.node.web",
                "role_name": "admin",
                "spec": {
                    "binding": {"node": "web", "role": "admin"},
                    "template": {"type": "service", "source": {"name": "nginx"}, "destination": ""},
                },
            },
        )
        feature = parse_plan(_serialized(feature_resource, self._target_node())).features[0]
        assert feature.name == "web-app"
        assert feature.feature_type == "service"
        assert feature.source_name == "nginx"
        assert feature.target_address == "provision.node.web"

    def test_malformed_composition_fails_closed(self):
        # ADR-032-R7: a content resource missing its type is a malformed payload
        # and aborts rather than being silently skipped.
        serialized = _serialized(self._content_resource(path="/srv/x"))
        with pytest.raises(AcesPlanError, match="malformed content-placement"):
            parse_plan(serialized)

    def test_no_composition_is_empty(self):
        plan = parse_plan(_serialized(_resource("node.a", "node", {"os_family": "linux", "spec": {"node": {}}})))
        assert plan.content == () and plan.accounts == () and plan.features == ()


class TestSelfDiscrimination:
    def test_rejects_none(self):
        with pytest.raises(AcesPlanError):
            parse_plan(None)

    def test_rejects_wrong_kind(self):
        plan = _serialized(_resource("node.a", "node", {"os_family": "linux"}))
        plan["kind"] = "something-else"
        with pytest.raises(AcesPlanError):
            parse_plan(plan)

    def test_rejects_cyberscript_envelope(self):
        envelope = {"spec_schema": "range_spec", "spec_version": "1", "payload": {"scenario_id": "basic-attack"}}
        with pytest.raises(AcesPlanError):
            parse_plan(envelope)


class TestVersionValidation:
    """ADR-032-R7: declare + validate supported contract and producer versions."""

    def _node(self) -> dict:
        return _resource("node.a", "node", {"os_family": "linux", "spec": {"node": {}}})

    def test_supported_contract_version_accepted(self):
        parsed = parse_plan(_serialized(self._node()))
        assert isinstance(parsed, AcesPlan)

    def test_missing_contract_version_fails_closed(self):
        serialized = _serialized(self._node(), contract_version=None)
        with pytest.raises(AcesPlanError, match="contract_version"):
            parse_plan(serialized)

    def test_unknown_contract_version_fails_closed(self):
        serialized = _serialized(self._node(), contract_version="aces-provisioning-plan-v99")
        with pytest.raises(AcesPlanError, match="contract_version"):
            parse_plan(serialized)

    def test_missing_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version=None)
        with pytest.raises(AcesPlanError, match="aces_sdl_version"):
            parse_plan(serialized)

    def test_empty_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version="   ")
        with pytest.raises(AcesPlanError, match="aces_sdl_version"):
            parse_plan(serialized)

    def test_below_minimum_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version="0.18.9")
        with pytest.raises(AcesPlanError, match="outside the supported range"):
            parse_plan(serialized)

    def test_future_series_aces_sdl_version_fails_closed(self):
        # A future major/minor outside the bounded series is rejected, not assumed
        # compatible -- an independently upgraded producer cannot slip changed
        # semantics past the older consumer.
        serialized = _serialized(self._node(), version="1.4.0")
        with pytest.raises(AcesPlanError, match="outside the supported range"):
            parse_plan(serialized)

    def test_exclusive_maximum_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version=MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE)
        with pytest.raises(AcesPlanError, match="outside the supported range"):
            parse_plan(serialized)

    def test_prerelease_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version="0.19.1rc1")
        with pytest.raises(AcesPlanError, match="not a valid release version"):
            parse_plan(serialized)

    def test_trailing_garbage_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version="0.19.1garbage")
        with pytest.raises(AcesPlanError, match="not a valid release version"):
            parse_plan(serialized)

    def test_unparseable_aces_sdl_version_fails_closed(self):
        serialized = _serialized(self._node(), version="not-a-version")
        with pytest.raises(AcesPlanError, match="not a valid release version"):
            parse_plan(serialized)

    def test_minimum_aces_sdl_version_accepted(self):
        parsed = parse_plan(_serialized(self._node(), version=MINIMUM_ACES_SDL_VERSION))
        assert parsed.aces_sdl_version == MINIMUM_ACES_SDL_VERSION

    @pytest.mark.parametrize("version", ["0.19.9", "0.20.0", "0.21.0", "0.22.0", "0.23.0"])
    def test_release_within_declared_window_accepted(self, version: str):
        parsed = parse_plan(_serialized(self._node(), version=version))
        assert parsed.aces_sdl_version == version


class TestFailClosed:
    """ADR-032-R7: reject unknown types, duplicate identities, dangling refs."""

    def test_unknown_resource_type_fails_closed(self):
        bad = _resource("lb.edge", "loadbalancer", {"spec": {}})
        serialized = _serialized(bad)
        with pytest.raises(AcesPlanError, match="resource_type"):
            parse_plan(serialized)

    def test_duplicate_resource_address_fails_closed(self):
        node = _resource("node.a", "node", {"os_family": "linux", "spec": {"node": {}}})
        plan = _serialized(node)
        # Two entries sharing the same authored address (distinct dict keys so the
        # collision is not hidden by the resources map).
        plan["resources"]["node.a#dup"] = _resource("node.a", "node", {"os_family": "linux", "spec": {"node": {}}})
        with pytest.raises(AcesPlanError, match="duplicate resource address"):
            parse_plan(plan)

    def test_duplicate_network_alias_fails_closed(self):
        net_a = _resource("net.a", "network", {"name": "shared", "spec": {"infrastructure": {"properties": {}}}})
        net_b = _resource("net.b", "network", {"name": "shared", "spec": {"infrastructure": {"properties": {}}}})
        serialized = _serialized(net_a, net_b)
        with pytest.raises(AcesPlanError, match="duplicate network alias"):
            parse_plan(serialized)

    def test_duplicate_node_alias_fails_closed(self):
        node_a = _resource("node.a", "node", {"name": "web", "spec": {"node": {}}})
        node_b = _resource("node.b", "node", {"name": "web", "spec": {"node": {}}})
        serialized = _serialized(node_a, node_b)
        with pytest.raises(AcesPlanError, match="duplicate node alias"):
            parse_plan(serialized)

    def test_dangling_acl_endpoint_fails_closed(self):
        node = _resource(
            "node.a",
            "node",
            {
                "os_family": "linux",
                "spec": {"infrastructure": {"acls": [{"action": "allow", "from_net": "net.ghost"}]}},
            },
        )
        serialized = _serialized(node)
        with pytest.raises(AcesPlanError, match=r"ACL .* references unknown network"):
            parse_plan(serialized)

    def test_dangling_composition_target_fails_closed(self):
        content = _resource(
            "content.doc",
            "content-placement",
            {"content_name": "doc", "target_address": "provision.node.ghost", "spec": {"type": "file"}},
        )
        serialized = _serialized(content)
        with pytest.raises(AcesPlanError, match="targets unknown node"):
            parse_plan(serialized)

    def test_unhashable_contract_version_fails_closed(self):
        # A malformed envelope whose discriminator is unhashable must fail closed as
        # AcesPlanError, not raise TypeError from set membership.
        serialized = _serialized(contract_version=[])
        with pytest.raises(AcesPlanError, match="contract_version"):
            parse_plan(serialized)  # type: ignore[arg-type]

    def test_unhashable_resource_type_fails_closed(self):
        bad = _resource("x.a", {}, {"spec": {}})  # type: ignore[arg-type]
        serialized = _serialized(bad)
        with pytest.raises(AcesPlanError, match="resource_type"):
            parse_plan(serialized)
