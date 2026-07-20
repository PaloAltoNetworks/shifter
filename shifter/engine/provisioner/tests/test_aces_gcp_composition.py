"""Tests for ACES composition -> GCE guest bootstrap realization (ADR-032).

Verifies genuine baked-image + inline delivery: inline files are written (base64,
correct mode), directories/parents are created, accounts become real users,
service features run a real install+enable step, non-inline content is treated as
baked (structural target only), the correct OS dialect is chosen, only the target
node's placements are included, and plan-controlled identifiers are validated
fail-closed (no shell injection).
"""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_gcp_composition import AcesGceCompositionError, node_bootstrap_script
from aces_plan import AcesPlan, AcesPlanAccount, AcesPlanContent, AcesPlanFeature, AcesPlanNode


def _node(os_family: str = "linux", address: str = "node.web") -> AcesPlanNode:
    return AcesPlanNode(
        address=address, name=address.rsplit(".", 1)[-1], os_family=os_family, count=1, network_addresses=("net.a",)
    )


def _plan(node: AcesPlanNode, *, content=(), accounts=(), features=()) -> AcesPlan:
    return AcesPlan(
        aces_sdl_version="0.19.1", nodes=(node,), networks=(), content=content, accounts=accounts, features=features
    )


def _content(**kw) -> AcesPlanContent:
    base = {"name": "c", "content_type": "file", "target_address": "node.web"}
    base.update(kw)
    return AcesPlanContent(**base)


class TestLinux:
    def test_account_creates_user_with_groups_shell_home(self):
        account = AcesPlanAccount(
            username="alice",
            target_address="node.web",
            groups=("ops", "sudo"),
            login_shell="/bin/bash",
            home="/home/alice",
        )
        script = node_bootstrap_script(_node(), _plan(_node(), accounts=(account,)))
        assert "id -u alice" in script and "useradd -m alice" in script
        assert "usermod -s /bin/bash alice" in script
        assert "usermod -d /home/alice alice" in script
        assert "usermod -aG ops alice" in script and "usermod -aG sudo alice" in script

    def test_disabled_account_is_locked(self):
        account = AcesPlanAccount(username="bob", target_address="node.web", disabled=True)
        assert "usermod -L bob" in node_bootstrap_script(_node(), _plan(_node(), accounts=(account,)))

    def test_account_mail_is_not_approximated_by_alias_files(self):
        account = AcesPlanAccount(username="carol", target_address="node.web", mail="carol@example.com")
        script = node_bootstrap_script(_node(), _plan(_node(), accounts=(account,)))
        assert "/etc/aliases.d" not in script
        assert "carol@example.com" not in script
        assert "newaliases" not in script

    def test_account_spn_is_never_approximated_by_a_linux_marker_file(self):
        account = AcesPlanAccount(username="svc", target_address="node.web", spn="HTTP/host.example.com")
        script = node_bootstrap_script(_node(), _plan(_node(), accounts=(account,)))
        assert "/etc/aces/spn" not in script
        assert "HTTP/host.example.com" not in script

    def test_inline_file_written_with_base64_and_mode(self):
        content = _content(content_type="file", path="/srv/x.txt", text="hello world")
        script = node_bootstrap_script(_node(), _plan(_node(), content=(content,)))
        assert base64.b64encode(b"hello world").decode() in script
        assert "mkdir -p /srv" in script
        assert "chmod 644 /srv/x.txt" in script

    def test_sensitive_file_is_mode_600(self):
        content = _content(content_type="file", path="/etc/secret", text="s", sensitive=True)
        assert "chmod 600 /etc/secret" in node_bootstrap_script(_node(), _plan(_node(), content=(content,)))

    def test_directory_content_creates_dir(self):
        content = _content(content_type="directory", destination="/srv/data")
        assert "mkdir -p /srv/data" in node_bootstrap_script(_node(), _plan(_node(), content=(content,)))

    def test_source_backed_content_is_excluded_from_bootstrap(self):
        # Source-backed content (file or directory) is delivered post-boot over an
        # authenticated guest channel with digest verification (#1564), never baked
        # into the startup script -- not even a structural mkdir stub, since the
        # delivery realizer creates the target itself as part of atomic install.
        file_content = _content(content_type="file", path="/opt/app/data.bin", source_name="pkg")
        script = node_bootstrap_script(_node(), _plan(_node(), content=(file_content,)))
        assert script == ""
        assert "mkdir -p /opt/app" not in script
        assert "base64 -d" not in script  # no bytes fetched/written

        dir_content = _content(content_type="directory", destination="/srv/data", source_name="pkg")
        script = node_bootstrap_script(_node(), _plan(_node(), content=(dir_content,)))
        assert script == ""
        assert "mkdir -p /srv/data" not in script

    def test_service_feature_is_excluded_for_verified_post_boot_realization(self):
        feature = AcesPlanFeature(name="app", feature_type="service", target_address="node.web", source_name="nginx")
        script = node_bootstrap_script(_node(), _plan(_node(), features=(feature,)))
        assert script == ""

    def test_artifact_feature_is_excluded_for_verified_post_boot_delivery(self):
        feature = AcesPlanFeature(
            name="edr", feature_type="artifact", target_address="node.web", source_name="edr", destination="/opt/edr"
        )
        script = node_bootstrap_script(_node(), _plan(_node(), features=(feature,)))
        assert script == ""


class TestWindows:
    def test_account_creates_local_user(self):
        account = AcesPlanAccount(username="Administrator", target_address="node.dc", groups=("Administrators",))
        node = _node(os_family="windows", address="node.dc")
        script = node_bootstrap_script(node, _plan(node, accounts=(account,)))
        assert "New-LocalUser -Name 'Administrator'" in script
        assert "Add-LocalGroupMember -Group 'Administrators' -Member 'Administrator'" in script

    def test_inline_file_written(self):
        node = _node(os_family="windows", address="node.dc")
        content = AcesPlanContent(
            name="c", content_type="file", target_address="node.dc", path="C:\\app\\x.txt", text="hi"
        )
        script = node_bootstrap_script(node, _plan(node, content=(content,)))
        assert base64.b64encode(b"hi").decode() in script
        assert "WriteAllBytes" in script

    def test_account_mail_is_not_approximated_by_marker_file(self):
        node = _node(os_family="windows", address="node.dc")
        account = AcesPlanAccount(username="dave", target_address="node.dc", mail="dave@corp.local")
        script = node_bootstrap_script(node, _plan(node, accounts=(account,)))
        assert "aces\\mail" not in script
        assert "dave@corp.local" not in script

    def test_account_spn_is_never_approximated_by_a_windows_marker_file(self):
        node = _node(os_family="windows", address="node.dc")
        account = AcesPlanAccount(username="svc", target_address="node.dc", spn="HTTP/host.example.com")
        script = node_bootstrap_script(node, _plan(node, accounts=(account,)))
        assert "aces\\spn" not in script
        assert "HTTP/host.example.com" not in script

    def test_service_feature_is_not_run_in_windows_startup_metadata(self):
        node = _node(os_family="windows", address="node.dc")
        feature = AcesPlanFeature(name="svc", feature_type="service", target_address="node.dc", source_name="mysvc")
        script = node_bootstrap_script(node, _plan(node, features=(feature,)))
        assert script == ""


class TestSelectionAndSafety:
    def test_empty_when_node_has_no_composition(self):
        assert node_bootstrap_script(_node(), _plan(_node())) == ""

    def test_only_target_nodes_placements_included(self):
        # content targets a different node -> not in this node's script.
        content = _content(content_type="file", path="/srv/other", text="x", target_address="node.other")
        assert node_bootstrap_script(_node(), _plan(_node(), content=(content,))) == ""

    @pytest.mark.parametrize("username", ["a; rm -rf /", "-root", "a" * 33])
    def test_unsafe_username_fails_closed(self, username: str):
        account = AcesPlanAccount(username=username, target_address="node.web")
        node_2 = _node()
        plan = _plan(_node(), accounts=(account,))
        with pytest.raises(AcesGceCompositionError, match="unsafe username"):
            node_bootstrap_script(node_2, plan)

    def test_unsafe_package_is_not_rendered_into_startup_metadata(self):
        feature = AcesPlanFeature(
            name="f", feature_type="service", target_address="node.web", source_name="pkg && evil"
        )
        node_2 = _node()
        plan = _plan(_node(), features=(feature,))
        assert node_bootstrap_script(node_2, plan) == ""

    def test_path_with_shell_metacharacters_is_quoted(self):
        content = _content(content_type="file", path="/srv/a b;c.txt", text="x")
        script = node_bootstrap_script(_node(), _plan(_node(), content=(content,)))
        # shlex.quote wraps the dangerous path so it can't break out.
        assert "'/srv/a b;c.txt'" in script
