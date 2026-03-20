"""Tests for experiment models."""

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from cms.experiments.models import (
    Experiment,
    ExperimentArtifact,
    ExperimentRun,
    ExperimentScript,
    RunArtifact,
    ScriptAsset,
)
from cms.experiments.schemas import ExperimentStatus, RunStatus, ScriptType

# Test password constant for all test users
TEST_PASSWORD = "testpass"  # nosec B105


class ScriptAssetModelTest(TestCase):
    """Test ScriptAsset model."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="testuser", password=TEST_PASSWORD, is_staff=True)

    def test_create_script(self):
        script = ScriptAsset.objects.create(
            name="Attack Script",
            user=self.user,
            s3_key="scripts/1/abc123_attack.py",
            original_filename="attack.py",
            file_size_bytes=512,
        )
        assert script.pk is not None
        assert str(script) == f"ScriptAsset(id={script.pk}, name=Attack Script, file=attack.py)"

    def test_soft_delete(self):
        script = ScriptAsset.objects.create(
            name="Temp",
            user=self.user,
            s3_key="scripts/1/x_temp.py",
            original_filename="temp.py",
            file_size_bytes=100,
        )
        assert not script.is_deleted
        from django.utils import timezone

        script.deleted_at = timezone.now()
        script.save()
        assert script.is_deleted

    def test_active_for_user(self):
        ScriptAsset.objects.create(
            name="Active",
            user=self.user,
            s3_key="scripts/1/a_active.py",
            original_filename="active.py",
            file_size_bytes=100,
        )
        from django.utils import timezone

        ScriptAsset.objects.create(
            name="Deleted",
            user=self.user,
            s3_key="scripts/1/b_deleted.py",
            original_filename="deleted.py",
            file_size_bytes=100,
            deleted_at=timezone.now(),
        )
        active = ScriptAsset.active_for_user(self.user)
        assert active.count() == 1
        assert active.first().name == "Active"

    def test_file_size_mb(self):
        script = ScriptAsset(file_size_bytes=1048576)
        assert script.file_size_mb == 1.0


class ExperimentModelTest(TestCase):
    """Test Experiment model."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="expuser", password=TEST_PASSWORD, is_staff=True)

    def test_create_experiment(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Test Exp",
            scenario_id="basic",
            total_runs=5,
            max_parallel_runs=3,
        )
        assert exp.uuid is not None
        assert exp.status == ExperimentStatus.DRAFT.value

    def test_transition_draft_to_queued(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Trans Test",
            scenario_id="basic",
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.QUEUED.value

    def test_transition_running_sets_started_at(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Start Test",
            scenario_id="basic",
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        exp.transition_to(ExperimentStatus.RUNNING)
        exp.refresh_from_db()
        assert exp.started_at is not None

    def test_transition_completed_sets_completed_at(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Complete Test",
            scenario_id="basic",
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        exp.transition_to(ExperimentStatus.RUNNING)
        exp.transition_to(ExperimentStatus.COMPLETED)
        exp.refresh_from_db()
        assert exp.completed_at is not None

    def test_invalid_transition_raises(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Bad Trans",
            scenario_id="basic",
        )
        with pytest.raises(ValueError, match="Cannot transition"):
            exp.transition_to(ExperimentStatus.COMPLETED)

    def test_clean_validates_parallel_vs_total(self):
        from django.core.exceptions import ValidationError

        exp = Experiment(
            user=self.user,
            name="Bad Params",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=5,
        )
        with pytest.raises(ValidationError):
            exp.clean()

    def test_str(self):
        exp = Experiment(name="My Exp", status=ExperimentStatus.DRAFT.value)
        assert str(exp) == f"Experiment(id={exp.pk}, name=My Exp, status=draft)"


class ExperimentScriptModelTest(TestCase):
    """Test ExperimentScript model."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="scriptuser", password=TEST_PASSWORD, is_staff=True)
        cls.experiment = Experiment.objects.create(
            user=cls.user,
            name="Script Test",
            scenario_id="basic",
        )
        cls.script = ScriptAsset.objects.create(
            name="Victim Script",
            user=cls.user,
            s3_key="scripts/1/x_victim.py",
            original_filename="victim.py",
            file_size_bytes=100,
        )

    def test_create_python_script(self):
        es = ExperimentScript.objects.create(
            experiment=self.experiment,
            instance_name="Workstation",
            script_type=ScriptType.PYTHON.value,
            script=self.script,
        )
        assert es.pk is not None

    def test_create_claude_script(self):
        es = ExperimentScript.objects.create(
            experiment=self.experiment,
            instance_name="Attacker",
            script_type=ScriptType.CLAUDE_CODE.value,
            claude_prompt="Attack {{Workstation.ip}}",
            execution_order=100,
        )
        assert es.claude_prompt == "Attack {{Workstation.ip}}"

    def test_unique_constraint(self):
        ExperimentScript.objects.create(
            experiment=self.experiment,
            instance_name="UniqueTest",
            script_type=ScriptType.PYTHON.value,
            script=self.script,
        )
        with pytest.raises(IntegrityError):
            ExperimentScript.objects.create(
                experiment=self.experiment,
                instance_name="UniqueTest",
                script_type=ScriptType.PYTHON.value,
                script=self.script,
            )

    def test_clean_python_requires_script(self):
        from django.core.exceptions import ValidationError

        es = ExperimentScript(
            experiment=self.experiment,
            instance_name="Bad",
            script_type=ScriptType.PYTHON.value,
        )
        with pytest.raises(ValidationError):
            es.clean()

    def test_clean_claude_requires_prompt(self):
        from django.core.exceptions import ValidationError

        es = ExperimentScript(
            experiment=self.experiment,
            instance_name="Bad",
            script_type=ScriptType.CLAUDE_CODE.value,
        )
        with pytest.raises(ValidationError):
            es.clean()


class ExperimentRunModelTest(TestCase):
    """Test ExperimentRun model."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="runuser", password=TEST_PASSWORD, is_staff=True)
        cls.experiment = Experiment.objects.create(
            user=cls.user,
            name="Run Test",
            scenario_id="basic",
        )

    def test_create_run(self):
        run = ExperimentRun.objects.create(
            experiment=self.experiment,
            run_number=1,
        )
        assert run.uuid is not None
        assert run.status == RunStatus.PENDING.value

    def test_transition_happy_path(self):
        run = ExperimentRun.objects.create(
            experiment=self.experiment,
            run_number=1,
        )
        run.transition_to(RunStatus.PROVISIONING)
        assert run.started_at is not None
        run.transition_to(RunStatus.EXECUTING_VICTIMS)
        run.transition_to(RunStatus.EXECUTING_ATTACKER)
        run.transition_to(RunStatus.COLLECTING)
        run.transition_to(RunStatus.COMPLETED)
        run.refresh_from_db()
        assert run.completed_at is not None

    def test_transition_to_failed(self):
        run = ExperimentRun.objects.create(
            experiment=self.experiment,
            run_number=2,
        )
        run.transition_to(RunStatus.PROVISIONING)
        run.transition_to(RunStatus.FAILED)
        run.refresh_from_db()
        assert run.completed_at is not None

    def test_invalid_transition_raises(self):
        run = ExperimentRun.objects.create(
            experiment=self.experiment,
            run_number=3,
        )
        with pytest.raises(ValueError, match="Cannot transition"):
            run.transition_to(RunStatus.EXECUTING_VICTIMS)

    def test_unique_constraint(self):
        ExperimentRun.objects.create(experiment=self.experiment, run_number=10)
        with pytest.raises(IntegrityError):
            ExperimentRun.objects.create(experiment=self.experiment, run_number=10)

    def test_metadata_json(self):
        run = ExperimentRun.objects.create(
            experiment=self.experiment,
            run_number=4,
            metadata={"instance_ips": {"Attacker": "10.1.1.5"}},
        )
        run.refresh_from_db()
        assert run.metadata["instance_ips"]["Attacker"] == "10.1.1.5"


class ArtifactModelTest(TestCase):
    """Test RunArtifact and ExperimentArtifact models."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="artuser", password=TEST_PASSWORD, is_staff=True)
        cls.experiment = Experiment.objects.create(
            user=cls.user,
            name="Art Test",
            scenario_id="basic",
        )
        cls.exp_run = ExperimentRun.objects.create(experiment=cls.experiment, run_number=1)

    def test_create_run_artifact(self):
        artifact = RunArtifact.objects.create(
            run=self.exp_run,
            instance_name="Attacker",
            artifact_type="claude_transcript",
            s3_key="experiments/1/runs/1/Attacker/claude_transcript.tar.gz",
            file_size_bytes=2048,
        )
        assert str(artifact) == "Attacker/claude_transcript"

    def test_create_experiment_artifact(self):
        bundle = ExperimentArtifact.objects.create(
            experiment=self.experiment,
            s3_key="experiments/1/bundle.zip",
            file_size_bytes=10240,
        )
        assert "Art Test" in str(bundle)

    def test_experiment_artifact_one_to_one(self):
        ExperimentArtifact.objects.create(
            experiment=self.experiment,
            s3_key="experiments/1/bundle.zip",
        )
        with pytest.raises(IntegrityError):
            ExperimentArtifact.objects.create(
                experiment=self.experiment,
                s3_key="experiments/1/bundle2.zip",
            )

    def test_run_artifact_cascade_delete(self):
        run = ExperimentRun.objects.create(experiment=self.experiment, run_number=99)
        run_pk = run.pk
        RunArtifact.objects.create(
            run=run,
            instance_name="Workstation",
            artifact_type="script_output",
            s3_key="experiments/1/runs/99/Workstation/script_output.tar.gz",
        )
        assert RunArtifact.objects.filter(run_id=run_pk).count() == 1
        run.delete()
        assert RunArtifact.objects.filter(run_id=run_pk).count() == 0
