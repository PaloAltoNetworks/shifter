"""Tests for the in-range-cluster guest SSH transport (RangePodSSHExecutor)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest

from executors.range_pod_ssh_executor import RangePodSSHExecutor


class _ApiException(Exception):
    def __init__(self, status=500):
        self.status = status
        super().__init__(f"ApiException({status})")


def _running_pod_with_segment_ip():
    pod = MagicMock()
    pod.to_dict.return_value = {
        "status": {"phase": "Running"},
        "metadata": {
            "annotations": {
                "k8s.v1.cni.cncf.io/network-status": json.dumps([{"interface": "net1", "ips": ["10.200.2.12"]}])
            }
        },
    }
    return pod


def _make_executor(core_api):
    return RangePodSSHExecutor(
        core_api=core_api,
        client_module=MagicMock(),
        api_exception=_ApiException,
        namespace="range-7",
        network_name="range-7-core",
        runner_image="registry.example/runner:latest",
        private_key="PRIVATE-KEY-MATERIAL",
        username="kali",
    )


def _make_gcp_executor(core_api):
    executor = RangePodSSHExecutor(
        core_api=core_api,
        client_module=MagicMock(),
        api_exception=_ApiException,
        namespace="range-7",
        network_name="range-7-core",
        runner_image="us-central1-docker.pkg.dev/proj/repo/runner:abc123",
        private_key="PRIVATE-KEY-MATERIAL",
        username="kali",
    )
    executor._mint_registry_token = lambda: "ya29.MINTED-TOKEN"  # type: ignore[method-assign]
    return executor


@pytest.mark.parametrize(
    ("image", "needs"),
    [
        ("us-central1-docker.pkg.dev/proj/repo/runner:abc123", True),
        ("gcr.io/proj/runner:latest", True),
        ("us.gcr.io/proj/runner:latest", True),
        ("docker.io/library/ubuntu:24.04", False),
        ("registry.example/runner:latest", False),
    ],
)
def test_registry_needs_credentials(image, needs):
    executor = RangePodSSHExecutor(
        core_api=MagicMock(),
        client_module=MagicMock(),
        api_exception=_ApiException,
        namespace="range-7",
        network_name="range-7-core",
        runner_image=image,
        private_key="K",
        username="kali",
    )
    assert executor._registry_needs_credentials() is needs


def test_ensure_pull_secret_plants_dockerconfigjson_for_artifact_registry():
    core_api = MagicMock()
    executor = _make_gcp_executor(core_api)

    executor._ensure_pull_secret()

    core_api.create_namespaced_secret.assert_called_once()
    _args, kwargs = core_api.create_namespaced_secret.call_args
    body = kwargs["body"]
    assert kwargs["namespace"] == "range-7"
    assert body["type"] == "kubernetes.io/dockerconfigjson"
    cfg = json.loads(base64.b64decode(body["data"][".dockerconfigjson"]).decode())
    entry = cfg["auths"]["us-central1-docker.pkg.dev"]
    assert entry["username"] == "oauth2accesstoken"
    assert entry["password"] == "ya29.MINTED-TOKEN"
    assert base64.b64decode(entry["auth"]).decode() == "oauth2accesstoken:ya29.MINTED-TOKEN"
    # The manifest now references the planted pull secret.
    manifest = executor._build_runner_manifest()
    assert manifest["spec"]["imagePullSecrets"] == [{"name": "shifter-runner-pull"}]


def test_ensure_pull_secret_refreshes_existing_secret():
    core_api = MagicMock()
    core_api.create_namespaced_secret.side_effect = _ApiException(status=409)
    executor = _make_gcp_executor(core_api)

    executor._ensure_pull_secret()

    core_api.patch_namespaced_secret.assert_called_once()
    assert executor._pull_secret_name == "shifter-runner-pull"


def test_ensure_pull_secret_skipped_for_public_registry():
    core_api = MagicMock()
    executor = _make_executor(core_api)  # registry.example -> no credentials

    executor._ensure_pull_secret()

    core_api.create_namespaced_secret.assert_not_called()
    manifest = executor._build_runner_manifest()
    assert "imagePullSecrets" not in manifest["spec"]


def test_provision_key_returns_in_pod_path_not_local_file():
    executor = _make_executor(MagicMock())
    assert executor._key_path.startswith("/tmp/shifter-guest-key-")  # noqa: S108 - in-pod path
    # No local key file is created for the range transport.
    import os

    assert not os.path.exists(executor._key_path)


def test_runner_manifest_attaches_nad_without_static_ip():
    executor = _make_executor(MagicMock())
    manifest = executor._build_runner_manifest()
    annotation = manifest["metadata"]["annotations"]["k8s.v1.cni.cncf.io/networks"]
    networks = json.loads(annotation)
    assert networks == [{"name": "range-7-core", "interface": "net1"}]
    assert manifest["spec"]["containers"][0]["image"] == "registry.example/runner:latest"


def test_ensure_runner_creates_pod_and_waits_ready(monkeypatch):
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    core_api.read_namespaced_pod.return_value = _running_pod_with_segment_ip()
    executor = _make_executor(core_api)

    executor._ensure_runner()

    core_api.create_namespaced_pod.assert_called_once()
    assert executor._runner_ready is True


def test_ensure_runner_tolerates_existing_pod(monkeypatch):
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    core_api.create_namespaced_pod.side_effect = _ApiException(status=409)
    core_api.read_namespaced_pod.return_value = _running_pod_with_segment_ip()
    executor = _make_executor(core_api)

    executor._ensure_runner()

    assert executor._runner_ready is True


def test_invoke_ssh_runs_wrapped_command_via_exec(monkeypatch):
    executor = _make_executor(MagicMock())
    executor._runner_ready = True
    executor._key_planted = True
    calls = []

    def fake_exec(command, timeout_seconds):
        calls.append((command, timeout_seconds))
        return 0, b"hello\n", b""

    monkeypatch.setattr(executor, "_exec", fake_exec)

    ssh_args = ["ssh", "-i", executor._key_path, "kali@10.200.2.10", "bash", "-se"]
    rc, out, err = executor._invoke_ssh(ssh_args, b"echo hi\n", 42)

    assert (rc, out, err) == (0, b"hello\n", b"")
    command, timeout = calls[0]
    assert command[:2] == ["/bin/sh", "-c"]
    assert timeout == 42
    wrapper = command[2]
    # The guest command script is delivered base64-encoded then piped to ssh
    # via a runner-local file (never on the guest argv).
    assert base64.b64encode(b"echo hi\n").decode() in wrapper
    assert "base64 -d" in wrapper
    assert "ssh" in wrapper and "kali@10.200.2.10" in wrapper


def _make_executor_with_host_key(core_api):
    return RangePodSSHExecutor(
        core_api=core_api,
        client_module=MagicMock(),
        api_exception=_ApiException,
        namespace="range-7",
        network_name="range-7-core",
        runner_image="registry.example/runner:latest",
        private_key="PRIVATE-KEY-MATERIAL",
        username="kali",
        host_public_key="ssh-ed25519 AAAAHOSTKEY guest",
        known_hosts_host="10.200.2.10",
    )


def test_provision_known_hosts_returns_in_pod_path_and_captures_content():
    executor = _make_executor_with_host_key(MagicMock())
    assert executor._known_hosts_path.startswith("/tmp/shifter-known-hosts-")  # noqa: S108 - in-pod path
    assert executor._known_hosts_content == "10.200.2.10 ssh-ed25519 AAAAHOSTKEY guest\n"


def test_invoke_ssh_plants_known_hosts_and_pins_in_ssh_args(monkeypatch):
    executor = _make_executor_with_host_key(MagicMock())
    executor._runner_ready = True
    executor._key_planted = True
    planted = []
    calls = []

    def fake_exec(command, timeout_seconds):
        script = command[2]
        if executor._known_hosts_path in script and "base64 -d" in script and "shifter-cmd" not in script:
            planted.append(script)
            return 0, b"", b""
        calls.append(command)
        return 0, b"ok\n", b""

    monkeypatch.setattr(executor, "_exec", fake_exec)

    ssh_args = [
        "ssh",
        "-i",
        executor._key_path,
        "-o",
        f"UserKnownHostsFile={executor._known_hosts_path}",
        "kali@10.200.2.10",
        "bash",
        "-se",
    ]
    rc, _out, _err = executor._invoke_ssh(ssh_args, b"echo hi\n", 30)

    assert rc == 0
    # known_hosts planted exactly once, base64-encoded.
    assert len(planted) == 1
    assert base64.b64encode(b"10.200.2.10 ssh-ed25519 AAAAHOSTKEY guest\n").decode() in planted[0]
    # second invoke does not re-plant.
    executor._invoke_ssh(ssh_args, b"echo hi2\n", 30)
    assert len(planted) == 1


def test_ensure_key_planted_execs_once(monkeypatch):
    executor = _make_executor(MagicMock())
    execs = []
    monkeypatch.setattr(executor, "_exec", lambda command, timeout_seconds: execs.append(command) or (0, b"", b""))

    executor._ensure_key_planted()
    executor._ensure_key_planted()

    assert len(execs) == 1
    assert executor._key_planted is True
    assert base64.b64encode(b"PRIVATE-KEY-MATERIAL").decode() in execs[0][2]


def test_ensure_key_planted_raises_on_failure(monkeypatch):
    from executors.guest_ssh_executor import GuestSSHConnectionError

    executor = _make_executor(MagicMock())
    monkeypatch.setattr(executor, "_exec", lambda command, timeout_seconds: (1, b"", b"boom"))

    with pytest.raises(GuestSSHConnectionError, match="plant guest SSH key"):
        executor._ensure_key_planted()


@pytest.mark.parametrize(
    ("returncode_attr", "channel_payload", "expected"),
    [
        (0, None, 0),
        (None, json.dumps({"status": "Success"}), 0),
        (
            None,
            json.dumps({"status": "Failure", "details": {"causes": [{"reason": "ExitCode", "message": "255"}]}}),
            255,
        ),
        (None, json.dumps({"status": "Failure", "details": {}}), 1),
    ],
)
def test_exec_returncode_parsing(returncode_attr, channel_payload, expected):
    resp = MagicMock()
    resp.returncode = returncode_attr
    resp.read_channel.return_value = channel_payload
    assert RangePodSSHExecutor._exec_returncode(resp) == expected


# -- constructor validation --------------------------------------------------


def test_init_rejects_empty_namespace():
    with pytest.raises(ValueError, match="namespace and network_name"):
        RangePodSSHExecutor(
            core_api=MagicMock(),
            client_module=MagicMock(),
            api_exception=_ApiException,
            namespace="",
            network_name="range-7-core",
            runner_image="registry.example/runner:latest",
            private_key="K",
            username="kali",
        )


def test_init_rejects_empty_runner_image():
    with pytest.raises(ValueError, match="runner image"):
        RangePodSSHExecutor(
            core_api=MagicMock(),
            client_module=MagicMock(),
            api_exception=_ApiException,
            namespace="range-7",
            network_name="range-7-core",
            runner_image="",
            private_key="K",
            username="kali",
        )


# -- token minting (real _mint_registry_token via injected google.auth) ------


def _install_fake_google_auth(monkeypatch, token):
    import sys
    import types

    creds = types.SimpleNamespace(token=token, refresh=lambda _req: None)
    google_mod = types.ModuleType("google")
    auth_mod = types.ModuleType("google.auth")
    auth_mod.default = lambda scopes: (creds, "proj")
    transport_mod = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda: object()
    google_mod.auth = auth_mod
    auth_mod.transport = transport_mod
    transport_mod.requests = requests_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.auth", auth_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)


def test_mint_registry_token_returns_access_token(monkeypatch):
    _install_fake_google_auth(monkeypatch, "ya29.MINTED")
    executor = _make_executor(MagicMock())
    assert executor._mint_registry_token() == "ya29.MINTED"


def test_mint_registry_token_raises_when_no_token(monkeypatch):
    from executors.guest_ssh_executor import GuestSSHConnectionError

    _install_fake_google_auth(monkeypatch, "")
    executor = _make_executor(MagicMock())
    with pytest.raises(GuestSSHConnectionError, match="mint Artifact Registry"):
        executor._mint_registry_token()


def test_ensure_pull_secret_reraises_non_conflict_error():
    core_api = MagicMock()
    core_api.create_namespaced_secret.side_effect = _ApiException(status=500)
    executor = _make_gcp_executor(core_api)
    with pytest.raises(_ApiException):
        executor._ensure_pull_secret()


# -- runner segment-IP readiness ---------------------------------------------


def test_runner_has_segment_ip_false_without_status_annotation():
    executor = _make_executor(MagicMock())
    assert executor._runner_has_segment_ip({"metadata": {"annotations": {}}}) is False


def test_runner_has_segment_ip_false_on_malformed_status():
    executor = _make_executor(MagicMock())
    pod = {"metadata": {"annotations": {"k8s.v1.cni.cncf.io/network-status": "{not json"}}}
    assert executor._runner_has_segment_ip(pod) is False


def test_runner_has_segment_ip_false_when_net1_has_no_ips():
    executor = _make_executor(MagicMock())
    pod = {
        "metadata": {
            "annotations": {"k8s.v1.cni.cncf.io/network-status": json.dumps([{"interface": "net1", "ips": []}])}
        }
    }
    assert executor._runner_has_segment_ip(pod) is False


# -- runner lifecycle error paths --------------------------------------------


def test_ensure_runner_reraises_non_conflict_create_error(monkeypatch):
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    core_api.create_namespaced_pod.side_effect = _ApiException(status=500)
    executor = _make_executor(core_api)
    with pytest.raises(_ApiException):
        executor._ensure_runner()


def test_wait_for_runner_ready_retries_on_404_then_succeeds(monkeypatch):
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    core_api.read_namespaced_pod.side_effect = [_ApiException(status=404), _running_pod_with_segment_ip()]
    executor = _make_executor(core_api)
    executor._wait_for_runner_ready()  # returns without raising
    assert core_api.read_namespaced_pod.call_count == 2


def test_wait_for_runner_ready_reraises_non_404(monkeypatch):
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    core_api.read_namespaced_pod.side_effect = _ApiException(status=500)
    executor = _make_executor(core_api)
    with pytest.raises(_ApiException):
        executor._wait_for_runner_ready()


def test_wait_for_runner_ready_raises_on_failed_phase(monkeypatch):
    from executors.guest_ssh_executor import GuestSSHConnectionError

    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    core_api = MagicMock()
    failed = MagicMock()
    failed.to_dict.return_value = {"status": {"phase": "Failed"}, "metadata": {"annotations": {}}}
    core_api.read_namespaced_pod.return_value = failed
    executor = _make_executor(core_api)
    with pytest.raises(GuestSSHConnectionError, match="phase=Failed"):
        executor._wait_for_runner_ready()


def test_wait_for_runner_ready_times_out(monkeypatch):
    from executors.guest_ssh_executor import GuestSSHConnectionError

    monkeypatch.setattr("executors.range_pod_ssh_executor.time.sleep", lambda *_a, **_k: None)
    # monotonic jumps past the deadline on the second read so the loop exits.
    clock = iter([0.0, 0.0, 10_000.0, 10_000.0, 10_000.0])
    monkeypatch.setattr("executors.range_pod_ssh_executor.time.monotonic", lambda: next(clock))
    core_api = MagicMock()
    pending = MagicMock()
    pending.to_dict.return_value = {"status": {"phase": "Pending"}, "metadata": {"annotations": {}}}
    core_api.read_namespaced_pod.return_value = pending
    executor = _make_executor(core_api)
    with pytest.raises(GuestSSHConnectionError, match="did not become ready"):
        executor._wait_for_runner_ready()


def test_ensure_known_hosts_planted_raises_on_failure(monkeypatch):
    from executors.guest_ssh_executor import GuestSSHConnectionError

    executor = _make_executor_with_host_key(MagicMock())
    monkeypatch.setattr(executor, "_exec", lambda command, timeout_seconds: (1, b"", b"nope"))
    with pytest.raises(GuestSSHConnectionError, match="plant known_hosts"):
        executor._ensure_known_hosts_planted()


# -- exec stream transport ---------------------------------------------------


class _FakeStreamResp:
    def __init__(self, returncode=0, chunks=(("out", "err"),)):
        self.returncode = returncode
        self._chunks = list(chunks)
        self._closed = False

    def is_open(self):
        return bool(self._chunks)

    def update(self, timeout=0):
        self._current = self._chunks.pop(0)

    def peek_stdout(self):
        return bool(self._current[0])

    def read_stdout(self):
        return self._current[0]

    def peek_stderr(self):
        return bool(self._current[1])

    def read_stderr(self):
        return self._current[1]

    def close(self):
        self._closed = True


def test_exec_streams_stdout_and_stderr(monkeypatch):
    resp = _FakeStreamResp(returncode=0, chunks=[("hello\n", "warn\n")])
    monkeypatch.setattr("kubernetes.stream.stream", lambda *a, **k: resp)
    executor = _make_executor(MagicMock())
    rc, out, err = executor._exec(["/bin/sh", "-c", "echo hello"], timeout_seconds=30)
    assert rc == 0
    assert out == b"hello\n"
    assert err == b"warn\n"
    assert resp._closed is True


def test_exec_raises_on_timeout(monkeypatch):
    from executors.guest_ssh_executor import TimeoutError as GuestTimeoutError

    resp = _FakeStreamResp(returncode=0, chunks=[("x", "")])
    monkeypatch.setattr("kubernetes.stream.stream", lambda *a, **k: resp)
    executor = _make_executor(MagicMock())
    with pytest.raises(GuestTimeoutError, match="timed out"):
        executor._exec(["/bin/sh", "-c", "sleep"], timeout_seconds=-1)
    assert resp._closed is True


# -- exit-code extraction edge cases -----------------------------------------


def test_exec_returncode_channel_read_error_returns_1():
    resp = MagicMock()
    resp.returncode = None
    resp.read_channel.side_effect = RuntimeError("channel closed")
    assert RangePodSSHExecutor._exec_returncode(resp) == 1


def test_exit_code_from_error_status_empty_payload_is_success():
    assert RangePodSSHExecutor._exit_code_from_error_status("") == 0
    assert RangePodSSHExecutor._exit_code_from_error_status(None) == 0


def test_exit_code_from_error_status_malformed_json_falls_through():
    assert RangePodSSHExecutor._exit_code_from_error_status("{not json") == 1


def test_exit_code_from_causes_non_numeric_message_returns_1():
    status = {"details": {"causes": [{"reason": "ExitCode", "message": "not-a-number"}]}}
    assert RangePodSSHExecutor._exit_code_from_causes(status) == 1
