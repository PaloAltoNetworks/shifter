"""Tests for exact running GKE image identity verification (#2084)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "verify_running_image_ids.py"
    spec = importlib.util.spec_from_file_location("verify_running_image_ids", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SHA = "a" * 40
_PORTAL_DIGEST = "sha256:" + "1" * 64
_GUACD_DIGEST = "sha256:" + "2" * 64
_GUACAMOLE_CLIENT_DIGEST = "sha256:" + "3" * 64
_EXPECTED = {
    "portal": {"root": "registry.example/release/portal", "digest": _PORTAL_DIGEST},
    "guacd": {"root": "registry.example/release/guacd", "digest": _GUACD_DIGEST},
    "guacamole-client": {
        "root": "registry.example/release/guacamole-client",
        "digest": _GUACAMOLE_CLIENT_DIGEST,
    },
}


def _container(name: str, root: str, digest: str) -> dict[str, str]:
    return {
        "name": name,
        "image": f"{root}@{digest}",
        "imageID": f"containerd://{root}@{digest}",
    }


def _valid_pods(module) -> dict[str, object]:
    items = []
    for component, containers in module._RELEASE_CONTAINERS.items():
        statuses = []
        for container_name, image_name in containers.items():
            image = _EXPECTED[image_name]
            statuses.append(_container(container_name, image["root"], image["digest"]))
        items.append(
            {
                "metadata": {
                    "name": f"{component}-abc123",
                    "labels": {
                        "app.kubernetes.io/part-of": "shifter",
                        "app.kubernetes.io/component": component,
                    },
                },
                "spec": {"containers": [{"name": item["name"], "image": item["image"]} for item in statuses]},
                "status": {"containerStatuses": statuses},
            }
        )
    return {"items": items}


def _pod_for(pods: dict[str, object], component: str) -> dict[str, object]:
    items = pods["items"]
    assert isinstance(items, list)
    return next(
        pod
        for pod in items
        if isinstance(pod, dict) and pod["metadata"]["labels"]["app.kubernetes.io/component"] == component
    )


def test_every_closed_release_container_must_match() -> None:
    module = _load_module()
    pods = _valid_pods(module)

    evidence = module.build_evidence(pods, _EXPECTED, source_sha=_SHA)

    assert evidence["source_sha"] == _SHA
    assert evidence["expected_images"]["portal"].endswith(f"@{_PORTAL_DIGEST}")
    assert len(evidence["running_containers"]) == len(module._RELEASE_CONTAINERS)


def test_every_closed_component_has_one_rollout_controller() -> None:
    module = _load_module()

    deployments = module.release_deployments()

    assert len(deployments) == len(module._RELEASE_CONTAINERS) == 15
    assert "portal-web" in deployments
    assert "worker-warm-pool-reconciler" in deployments


def test_deploy_workflow_waits_on_the_canonical_release_inventory() -> None:
    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")

    assert "verify_running_image_ids.py --list-deployments" in workflow
    assert 'for deployment in "${deployments[@]}"' in workflow
    assert workflow.index("--list-deployments") < workflow.index("Record running workload image IDs")


def test_provisioner_jobs_are_outside_the_verified_namespace() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/_gcp-dev.yml").read_text(encoding="utf-8")
    runtime = (root / "platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env").read_text(encoding="utf-8")

    assert "kubectl get pods -n shifter-platform" in workflow
    assert "ENGINE_TASK_NAMESPACE=shifter-jobs" in runtime


def test_one_stale_container_fails_even_when_another_container_matches() -> None:
    module = _load_module()
    stale = "sha256:" + "9" * 64
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["status"]["containerStatuses"][0]["imageID"] = f"containerd://{_EXPECTED['portal']['root']}@{stale}"

    with pytest.raises(ValueError, match=r"portal.*exact approved image identity"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_runtime_repository_must_match_even_when_declared_image_and_digest_match() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["status"]["containerStatuses"][0]["imageID"] = (
        f"containerd://registry.example/unrelated/image@{_PORTAL_DIGEST}"
    )

    with pytest.raises(ValueError, match=r"portal.*exact approved image identity"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_declared_image_must_match_even_when_runtime_status_is_correct() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["spec"]["containers"][0]["image"] = f"registry.example/unapproved/portal@{_PORTAL_DIGEST}"

    with pytest.raises(ValueError, match=r"portal.*declare its exact approved image identity"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_unapproved_status_sidecar_cannot_hide_behind_expected_release_containers() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["status"]["containerStatuses"].append(
        _container("unapproved-sidecar", "registry.example/attacker/image", _PORTAL_DIGEST)
    )

    with pytest.raises(ValueError, match=r"unexpected status containers.*unapproved-sidecar"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_unready_declared_sidecar_cannot_hide_by_omitting_its_status() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["spec"]["containers"].append(
        {
            "name": "unready-sidecar",
            "image": f"registry.example/attacker/image@{_PORTAL_DIGEST}",
        }
    )

    with pytest.raises(ValueError, match=r"unexpected declared containers.*unready-sidecar"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_unapproved_workload_cannot_enter_the_closed_namespace_inventory() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    pods["items"].append(
        {
            "metadata": {
                "name": "unapproved-workload",
                "labels": {
                    "app.kubernetes.io/part-of": "shifter",
                    "app.kubernetes.io/component": "unapproved",
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "malicious",
                        "image": f"registry.example/attacker/image@{_PORTAL_DIGEST}",
                    }
                ]
            },
            "status": {
                "containerStatuses": [_container("malicious", "registry.example/attacker/image", _PORTAL_DIGEST)]
            },
        }
    )

    with pytest.raises(ValueError, match=r"unexpected Shifter workload component"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_every_release_component_is_required() -> None:
    module = _load_module()
    pods = _valid_pods(module)
    pods["items"].remove(_pod_for(pods, "guacd"))

    with pytest.raises(ValueError, match=r"missing release components.*guacd"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)


def test_evidence_write_is_private_and_refuses_overwrite(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "running-image-ids.json"

    module._write_private_json(output, {"schema_version": 1})

    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module._write_private_json(output, {"schema_version": 1})


def _main_argv(pods_path: Path, output_path: Path) -> list[str]:
    argv = [
        "verify_running_image_ids.py",
        "--pods-json",
        str(pods_path),
        "--output",
        str(output_path),
        "--source-sha",
        _SHA,
    ]
    for name, image in _EXPECTED.items():
        argv.extend(["--expected-image", f"{name}={image['root']}@{image['digest']}"])
    return argv


def test_main_writes_evidence_for_exact_runtime_inventory(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    pods_path = tmp_path / "pods.json"
    output_path = tmp_path / "evidence.json"
    pods_path.write_text(json.dumps(_valid_pods(module)), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _main_argv(pods_path, output_path))

    assert module.main() == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_sha"] == _SHA


def test_main_exits_nonzero_for_runtime_image_mismatch(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    pods = _valid_pods(module)
    portal = _pod_for(pods, "portal")
    portal["status"]["containerStatuses"][0]["imageID"] = (
        f"containerd://{_EXPECTED['portal']['root']}@sha256:{'9' * 64}"
    )
    pods_path = tmp_path / "pods.json"
    output_path = tmp_path / "evidence.json"
    pods_path.write_text(json.dumps(pods), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _main_argv(pods_path, output_path))

    with pytest.raises(SystemExit) as caught:
        module.main()

    assert caught.value.code == 2
    assert not output_path.exists()


@pytest.mark.parametrize(
    "value",
    [
        "portal=registry.example/release/portal:latest",
        "portal=registry.example/release/portal@sha256:not-a-digest",
        "",
    ],
)
def test_expected_image_parser_rejects_mutable_or_malformed_references(value: str) -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="name=repository@sha256"):
        module.parse_expected_images([value])


def test_optional_broker_requires_explicit_release_enablement_and_both_components():
    module = _load_module()
    pods = _valid_pods(module)
    for component in ("model-broker", "model-access-control"):
        image = _EXPECTED["portal"]
        container = _container(component, image["root"], image["digest"])
        pods["items"].append(
            {
                "metadata": {
                    "name": component + "-123",
                    "labels": {"app.kubernetes.io/part-of": "shifter", "app.kubernetes.io/component": component},
                },
                "spec": {"containers": [{"name": component, "image": container["image"]}]},
                "status": {"containerStatuses": [container]},
            }
        )
    with pytest.raises(ValueError, match="unexpected"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA)
    assert (
        len(module.build_evidence(pods, _EXPECTED, source_sha=_SHA, model_broker_enabled=True)["running_containers"])
        == 17
    )
    pods["items"].pop()
    with pytest.raises(ValueError, match="missing release components"):
        module.build_evidence(pods, _EXPECTED, source_sha=_SHA, model_broker_enabled=True)
    assert {"model-broker", "model-access-control"} <= set(module.release_deployments(model_broker_enabled=True))
