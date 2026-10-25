from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "reconcile_retired_cluster_artifacts.py"
SPEC = importlib.util.spec_from_file_location("reconcile_retired_cluster_artifacts", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "retired.json"
    path.write_text(
        json.dumps(
            {
                "network_policies": [{"namespace": "jobs", "name": "old-policy", "replacement": "new-policy"}],
                "secrets": [{"namespace": "platform", "name": "old-identity", "obsolete_job": "old-job"}],
                "deployment_annotations": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_retirement_checks_replacement_and_absent_job_before_delete(tmp_path, monkeypatch):
    calls = []

    def fake_kubectl(context, namespace, *args, may_be_absent=False):
        calls.append((context, namespace, args))
        return not (args[:2] == ("get", "job") and may_be_absent)

    monkeypatch.setattr(MODULE, "_kubectl", fake_kubectl)
    MODULE.reconcile("context", _manifest(tmp_path))
    assert calls == [
        ("context", "jobs", ("get", "networkpolicy", "new-policy")),
        ("context", "jobs", ("delete", "networkpolicy", "old-policy", "--ignore-not-found")),
        ("context", "platform", ("get", "job", "old-job")),
        ("context", "platform", ("delete", "secret", "old-identity", "--ignore-not-found")),
    ]


def test_retirement_refuses_to_delete_an_active_job_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "_kubectl", lambda *_args, **_kwargs: True)
    with pytest.raises(ValueError, match="still present"):
        MODULE.reconcile("context", _manifest(tmp_path))


def test_retirement_skips_annotation_that_is_already_absent(tmp_path, monkeypatch):
    manifest = json.loads(_manifest(tmp_path).read_text(encoding="utf-8"))
    manifest["deployment_annotations"] = [
        {"namespace": "platform", "name": "worker", "annotation": "kubectl.kubernetes.io/restartedAt"}
    ]
    path = tmp_path / "retired.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []

    def fake_kubectl(*args, may_be_absent=False):
        calls.append(args)
        return not (args[2:4] == ("get", "job") and may_be_absent)

    monkeypatch.setattr(MODULE, "_kubectl", fake_kubectl)
    monkeypatch.setattr(MODULE, "_has_deployment_annotation", lambda *_args: False)
    MODULE.reconcile("context", path)
    assert all("annotate" not in args for args in calls)
