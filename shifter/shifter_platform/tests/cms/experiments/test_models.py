"""Tests for experiment models -- pure unit tests, no DB access."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from cms.experiments.models import (
    Experiment,
    ExperimentArtifact,
    ExperimentRun,
    ExperimentScript,
    RunArtifact,
    ScriptAsset,
)
from cms.experiments.schemas import ExperimentStatus, RunStatus, ScriptType

# ---------------------------------------------------------------------------
# Helpers -- build model instances bypassing descriptors and DB
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
    """Return a real User instance built in-memory (no DB)."""
    user = User.__new__(User)
    user.__dict__.update(
        {
            "id": kwargs.get("pk", 1),
            "pk": kwargs.get("pk", 1),
            "username": kwargs.get("username", "testuser"),
        }
    )
    return user


def _make_script_asset(**kwargs):
    """Build an in-memory ScriptAsset (no DB)."""
    user = kwargs.pop("user", _make_user())
    sa = ScriptAsset.__new__(ScriptAsset)
    sa.__dict__.update(
        {
            "id": kwargs.get("pk", 10),
            "pk": kwargs.get("pk", 10),
            "name": kwargs.get("name", "Attack Script"),
            "s3_key": kwargs.get("s3_key", "scripts/1/abc123_attack.py"),
            "original_filename": kwargs.get("original_filename", "attack.py"),
            "file_size_bytes": kwargs.get("file_size_bytes", 512),
            "deleted_at": kwargs.get("deleted_at"),
            "user_id": user.pk,
        }
    )
    # Set the FK cache directly to avoid descriptor validation
    sa.__dict__["user"] = user
    return sa


def _make_experiment(**kwargs):
    """Build an in-memory Experiment (no DB)."""
    user = kwargs.pop("user", _make_user())
    exp = Experiment.__new__(Experiment)
    exp.__dict__.update(
        {
            "id": kwargs.get("pk", 100),
            "pk": kwargs.get("pk", 100),
            "uuid": kwargs.get("uuid", uuid4()),
            "name": kwargs.get("name", "Test Exp"),
            "description": kwargs.get("description", ""),
            "scenario_id": kwargs.get("scenario_id", "basic"),
            "status": kwargs.get("status", ExperimentStatus.DRAFT.value),
            "total_runs": kwargs.get("total_runs", 5),
            "max_parallel_runs": kwargs.get("max_parallel_runs", 3),
            "started_at": kwargs.get("started_at"),
            "completed_at": kwargs.get("completed_at"),
            "error_message": kwargs.get("error_message", ""),
            "user_id": user.pk,
            "agent_id": None,
        }
    )
    exp.__dict__["user"] = user
    exp.__dict__["agent"] = None
    return exp


def _make_experiment_run(experiment=None, **kwargs):
    """Build an in-memory ExperimentRun (no DB)."""
    if experiment is None:
        experiment = _make_experiment()
    run = ExperimentRun.__new__(ExperimentRun)
    run.__dict__.update(
        {
            "id": kwargs.get("pk", 200),
            "pk": kwargs.get("pk", 200),
            "uuid": kwargs.get("uuid", uuid4()),
            "run_number": kwargs.get("run_number", 1),
            "request_id": kwargs.get("request_id"),
            "status": kwargs.get("status", RunStatus.PENDING.value),
            "started_at": kwargs.get("started_at"),
            "completed_at": kwargs.get("completed_at"),
            "error_message": kwargs.get("error_message", ""),
            "metadata": kwargs.get("metadata"),
            "experiment_id": experiment.pk,
        }
    )
    run.__dict__["experiment"] = experiment
    return run


def _make_experiment_script(experiment=None, **kwargs):
    """Build an in-memory ExperimentScript (no DB)."""
    if experiment is None:
        experiment = _make_experiment()
    script_asset = kwargs.pop("script", None)
    es = ExperimentScript.__new__(ExperimentScript)
    es.__dict__.update(
        {
            "id": kwargs.get("pk", 300),
            "pk": kwargs.get("pk", 300),
            "instance_name": kwargs.get("instance_name", "Workstation"),
            "script_type": kwargs.get("script_type", ScriptType.PYTHON.value),
            "claude_prompt": kwargs.get("claude_prompt", ""),
            "execution_order": kwargs.get("execution_order", 0),
            "experiment_id": experiment.pk,
            "script_id": script_asset.pk if script_asset else None,
        }
    )
    es.__dict__["experiment"] = experiment
    es.__dict__["script"] = script_asset
    return es


# ---------------------------------------------------------------------------
# ScriptAsset
# ---------------------------------------------------------------------------


class TestScriptAssetModel:
    """Test ScriptAsset model."""

    def test_str(self):
        script = _make_script_asset(pk=7, name="Attack Script", original_filename="attack.py")
        assert str(script) == "ScriptAsset(id=7, name=Attack Script, file=attack.py)"

    def test_is_deleted_false_when_deleted_at_none(self):
        script = _make_script_asset(deleted_at=None)
        assert not script.is_deleted

    def test_is_deleted_true_when_deleted_at_set(self):
        from django.utils import timezone

        script = _make_script_asset(deleted_at=timezone.now())
        assert script.is_deleted

    def test_active_for_user(self):
        """active_for_user chains SoftDeleteQuerySet.active() and the user filter."""
        user = _make_user()
        first_item = _make_script_asset(name="Active")
        fake_qs = MagicMock()
        fake_qs.count.return_value = 1
        fake_qs.first.return_value = first_item
        mock_active_qs = MagicMock()
        mock_active_qs.filter.return_value = fake_qs
        with patch.object(ScriptAsset.objects, "active", return_value=mock_active_qs) as mock_active:
            result = ScriptAsset.active_for_user(user)
            mock_active.assert_called_once_with()
            mock_active_qs.filter.assert_called_once_with(user=user)
            assert result.count() == 1
            assert result.first().name == "Active"

    def test_file_size_mb(self):
        script = _make_script_asset(file_size_bytes=1048576)
        assert script.file_size_mb == 1.0


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class TestExperimentModel:
    """Test Experiment model."""

    def test_default_status_is_draft(self):
        exp = _make_experiment()
        assert exp.status == ExperimentStatus.DRAFT.value

    def test_uuid_is_set(self):
        exp = _make_experiment()
        assert exp.uuid is not None

    @patch.object(Experiment, "save")
    def test_transition_draft_to_queued(self, mock_save):
        exp = _make_experiment(status=ExperimentStatus.DRAFT.value)
        exp.transition_to(ExperimentStatus.QUEUED)
        assert exp.status == ExperimentStatus.QUEUED.value
        mock_save.assert_called_once()

    @patch.object(Experiment, "save")
    def test_transition_running_sets_started_at(self, mock_save):
        exp = _make_experiment(status=ExperimentStatus.QUEUED.value)
        exp.transition_to(ExperimentStatus.RUNNING)
        assert exp.started_at is not None
        assert exp.status == ExperimentStatus.RUNNING.value

    @patch.object(Experiment, "save")
    def test_transition_completed_sets_completed_at(self, mock_save):
        exp = _make_experiment(status=ExperimentStatus.RUNNING.value, started_at="2024-01-01")
        exp.transition_to(ExperimentStatus.COMPLETED)
        assert exp.completed_at is not None
        assert exp.status == ExperimentStatus.COMPLETED.value

    def test_invalid_transition_raises(self):
        exp = _make_experiment(status=ExperimentStatus.DRAFT.value)
        with pytest.raises(ValueError, match="Cannot transition"):
            exp.transition_to(ExperimentStatus.COMPLETED)

    def test_clean_validates_parallel_vs_total(self):
        exp = _make_experiment(total_runs=2, max_parallel_runs=5)
        with pytest.raises(ValidationError):
            exp.clean()

    def test_clean_passes_when_valid(self):
        exp = _make_experiment(total_runs=5, max_parallel_runs=3)
        exp.clean()  # should not raise

    def test_str(self):
        exp = _make_experiment(pk=None, name="My Exp", status=ExperimentStatus.DRAFT.value)
        assert str(exp) == "Experiment(id=None, name=My Exp, status=draft)"


# ---------------------------------------------------------------------------
# ExperimentScript
# ---------------------------------------------------------------------------


class TestExperimentScriptModel:
    """Test ExperimentScript model."""

    def test_str(self):
        es = _make_experiment_script(
            instance_name="Workstation",
            script_type=ScriptType.PYTHON.value,
        )
        assert str(es) == "Workstation (python)"

    def test_clean_python_requires_script(self):
        es = _make_experiment_script(
            instance_name="Bad",
            script_type=ScriptType.PYTHON.value,
            script=None,
        )
        with pytest.raises(ValidationError):
            es.clean()

    def test_clean_claude_requires_prompt(self):
        es = _make_experiment_script(
            instance_name="Bad",
            script_type=ScriptType.CLAUDE_CODE.value,
            script=None,
            claude_prompt="",
        )
        with pytest.raises(ValidationError):
            es.clean()

    def test_clean_python_passes_with_script(self):
        script = _make_script_asset()
        es = _make_experiment_script(
            instance_name="Workstation",
            script_type=ScriptType.PYTHON.value,
            script=script,
        )
        es.clean()  # should not raise

    def test_clean_claude_passes_with_prompt(self):
        es = _make_experiment_script(
            instance_name="Attacker",
            script_type=ScriptType.CLAUDE_CODE.value,
            script=None,
            claude_prompt="Attack {{Workstation.ip}}",
        )
        es.clean()  # should not raise


# ---------------------------------------------------------------------------
# ExperimentRun
# ---------------------------------------------------------------------------


class TestExperimentRunModel:
    """Test ExperimentRun model."""

    def test_default_status_is_pending(self):
        run = _make_experiment_run()
        assert run.status == RunStatus.PENDING.value

    def test_uuid_is_set(self):
        run = _make_experiment_run()
        assert run.uuid is not None

    @patch.object(ExperimentRun, "save")
    def test_transition_happy_path(self, mock_save):
        run = _make_experiment_run()
        run.transition_to(RunStatus.PROVISIONING)
        assert run.started_at is not None
        run.transition_to(RunStatus.EXECUTING_VICTIMS)
        run.transition_to(RunStatus.EXECUTING_ATTACKER)
        run.transition_to(RunStatus.COLLECTING)
        run.transition_to(RunStatus.COMPLETED)
        assert run.completed_at is not None
        assert run.status == RunStatus.COMPLETED.value

    @patch.object(ExperimentRun, "save")
    def test_transition_to_failed(self, mock_save):
        run = _make_experiment_run()
        run.transition_to(RunStatus.PROVISIONING)
        run.transition_to(RunStatus.FAILED)
        assert run.completed_at is not None
        assert run.status == RunStatus.FAILED.value

    def test_invalid_transition_raises(self):
        run = _make_experiment_run()
        with pytest.raises(ValueError, match="Cannot transition"):
            run.transition_to(RunStatus.EXECUTING_VICTIMS)

    def test_metadata_stored(self):
        run = _make_experiment_run(metadata={"instance_ips": {"Attacker": "10.1.1.5"}})
        assert run.metadata["instance_ips"]["Attacker"] == "10.1.1.5"

    def test_str(self):
        exp = _make_experiment(pk=50)
        run = _make_experiment_run(experiment=exp, pk=7, run_number=3, status=RunStatus.PENDING.value)
        assert str(run) == "Run(id=7, experiment=50, num=3, status=pending)"


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class TestArtifactModels:
    """Test RunArtifact and ExperimentArtifact models."""

    def test_run_artifact_str(self):
        art = RunArtifact.__new__(RunArtifact)
        art.__dict__.update(
            {
                "instance_name": "Attacker",
                "artifact_type": "claude_transcript",
            }
        )
        assert str(art) == "Attacker/claude_transcript"

    def test_experiment_artifact_str(self):
        exp = _make_experiment(name="Art Test")
        bundle = ExperimentArtifact.__new__(ExperimentArtifact)
        # OneToOneField descriptor uses _state.fields_cache, so we must init it
        from django.db.models.base import ModelState

        bundle._state = ModelState()
        bundle.__dict__.update(
            {
                "s3_key": "experiments/1/bundle.zip",
                "file_size_bytes": 10240,
                "experiment_id": exp.pk,
            }
        )
        # Cache the experiment in the descriptor's cache
        bundle._state.fields_cache["experiment"] = exp
        assert "Art Test" in str(bundle)
