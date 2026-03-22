"""Tests for experiment services.

Tests the business logic without calling real S3/infrastructure or the database.
All ORM access is mocked.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from cms.experiments import services
from cms.experiments.exceptions import (
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus
from shared.constants import USER_CANNOT_BE_NONE

# ---------------------------------------------------------------------------
# Module-wide fixture: neutralize transaction.atomic so no DB connection needed
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_db_transactions():
    """Replace transaction.atomic and _check_result_type so no DB connection needed."""
    with (
        patch("cms.experiments.services.transaction") as mock_tx,
        patch("cms.experiments.services._check_result_type"),
    ):
        mock_tx.atomic.return_value = nullcontext()
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(pk=1, username="testuser", is_staff=True):
    """Create a MagicMock user with the minimum attributes services need."""
    user = MagicMock()
    user.pk = pk
    user.id = pk
    user.username = username
    user.is_staff = is_staff
    return user


def _make_script(pk=1, user=None, name="script", deleted_at=None):
    """Create a MagicMock ScriptAsset."""
    script = MagicMock()
    script.pk = pk
    script.name = name
    script.user = user
    script.deleted_at = deleted_at
    script.s3_key = f"scripts/{pk}/test.py"
    script.original_filename = "test.py"
    script.file_size_bytes = 100
    return script


def _make_experiment(
    pk=1,
    user=None,
    name="Test Exp",
    scenario_id="basic",
    status=ExperimentStatus.DRAFT.value,
    total_runs=3,
    max_parallel_runs=1,
):
    """Create a MagicMock Experiment."""
    exp = MagicMock()
    exp.pk = pk
    exp.name = name
    exp.user = user
    exp.scenario_id = scenario_id
    exp.status = status
    exp.total_runs = total_runs
    exp.max_parallel_runs = max_parallel_runs
    exp.scripts = MagicMock()
    return exp


# ---------------------------------------------------------------------------
# ListScriptsTest
# ---------------------------------------------------------------------------


class TestListScripts:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="svc_user")

    @pytest.fixture()
    def other_user(self):
        return _make_user(pk=2, username="other_user")

    @patch("cms.experiments.services.ScriptAsset")
    def test_returns_only_active_for_user(self, mock_script_model, user):
        active_script = _make_script(pk=1, user=user, name="Active")
        qs = MagicMock()
        qs.count.return_value = 1
        qs.first.return_value = active_script
        mock_script_model.objects.filter.return_value.order_by.return_value = qs

        scripts = services.list_scripts(user)
        assert scripts.count() == 1
        assert scripts.first().name == "Active"
        mock_script_model.objects.filter.assert_called_once_with(user=user, deleted_at__isnull=True)

    @patch("cms.experiments.services.ScriptAsset")
    def test_other_user_sees_own(self, mock_script_model, other_user):
        other_script = _make_script(pk=3, user=other_user, name="Other")
        qs = MagicMock()
        qs.count.return_value = 1
        qs.first.return_value = other_script
        mock_script_model.objects.filter.return_value.order_by.return_value = qs

        scripts = services.list_scripts(other_user)
        assert scripts.count() == 1
        assert scripts.first().name == "Other"


# ---------------------------------------------------------------------------
# DeleteScriptTest
# ---------------------------------------------------------------------------


class TestDeleteScript:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="del_user")

    @pytest.fixture()
    def other_user(self):
        return _make_user(pk=2, username="del_other")

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ScriptAsset")
    def test_soft_deletes_own_script(self, mock_script_model, mock_audit, user):
        mock_script_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        script = _make_script(pk=10, user=user, name="ToDelete")
        script.deleted_at = None
        mock_script_model.objects.get.return_value = script

        services.delete_script(user, 10)

        mock_script_model.objects.get.assert_called_once_with(pk=10, user=user, deleted_at__isnull=True)
        assert script.deleted_at is not None
        script.save.assert_called_once()

    @patch("cms.experiments.services.ScriptAsset")
    def test_cannot_delete_other_users_script(self, mock_script_model, user):
        mock_script_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_script_model.objects.get.side_effect = mock_script_model.DoesNotExist

        with pytest.raises(ScriptUploadError, match="not found"):
            services.delete_script(user, 99)


# ---------------------------------------------------------------------------
# CreateExperimentTest
# ---------------------------------------------------------------------------


class TestCreateExperiment:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="create_user")

    @pytest.fixture()
    def script(self, user):
        return _make_script(pk=5, user=user, name="Victim Script")

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ExperimentScript")
    @patch("cms.experiments.services.Experiment")
    @patch("cms.experiments.services.ScriptAsset")
    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_create_basic_experiment(
        self, mock_check, mock_load, mock_script_model, mock_exp_model, mock_es_model, mock_audit, user
    ):
        # Scenario template with instances
        mock_instance = MagicMock()
        mock_instance.name = "Workstation"
        mock_template = MagicMock()
        mock_template.instances = [mock_instance]
        mock_load.return_value = mock_template

        # The Experiment() constructor returns a mock that we control
        mock_exp = _make_experiment(pk=42, user=user, total_runs=3)
        mock_exp_model.return_value = mock_exp

        data = ExperimentCreateInput(
            name="Test Experiment",
            scenario_id="basic",
            total_runs=3,
            max_parallel_runs=2,
        )
        exp = services.create_experiment(user, data)

        assert exp.pk == 42
        assert exp.status == ExperimentStatus.DRAFT.value
        mock_exp.full_clean.assert_called_once()
        mock_exp.save.assert_called_once()

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ExperimentScript")
    @patch("cms.experiments.services.Experiment")
    @patch("cms.experiments.services.ScriptAsset")
    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_create_with_script_assignments(
        self, mock_check, mock_load, mock_script_model, mock_exp_model, mock_es_model, mock_audit, user, script
    ):
        mock_workstation = MagicMock()
        mock_workstation.name = "Workstation"
        mock_attacker = MagicMock()
        mock_attacker.name = "Attacker"
        mock_template = MagicMock()
        mock_template.instances = [mock_workstation, mock_attacker]
        mock_load.return_value = mock_template

        # Script validation: pretend the script exists for the user
        mock_script_model.objects.filter.return_value.values_list.return_value = {script.pk}

        mock_exp = _make_experiment(pk=43, user=user)
        mock_exp.scripts.count.return_value = 2
        mock_exp_model.return_value = mock_exp

        data = ExperimentCreateInput(
            name="With Scripts",
            scenario_id="basic",
            total_runs=1,
            scripts=[
                {
                    "instance_name": "Workstation",
                    "script_type": "python",
                    "script_id": script.pk,
                    "execution_order": 0,
                },
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.ip}}",
                    "execution_order": 100,
                },
            ],
        )
        services.create_experiment(user, data)
        # ExperimentScript constructor called twice
        assert mock_es_model.call_count == 2

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_invalid_scenario_raises(self, mock_check, mock_load, user):
        mock_check.side_effect = ValueError("Scenario not found")

        data = ExperimentCreateInput(
            name="Bad Scenario",
            scenario_id="nonexistent",
        )
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.create_experiment(user, data)

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_invalid_instance_name_raises(self, mock_check, mock_load, user, script):
        mock_instance = MagicMock()
        mock_instance.name = "Workstation"
        mock_template = MagicMock()
        mock_template.instances = [mock_instance]
        mock_load.return_value = mock_template

        data = ExperimentCreateInput(
            name="Bad Instance",
            scenario_id="basic",
            scripts=[
                {
                    "instance_name": "NonExistentBox",
                    "script_type": "python",
                    "script_id": script.pk,
                }
            ],
        )
        with pytest.raises(ExperimentValidationError, match="not found in scenario"):
            services.create_experiment(user, data)

    def test_invalid_template_variable_rejected(self):
        """Pure Pydantic validation - no DB needed."""
        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Bad Template Var",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{NonExistent.ip}}",
                    "execution_order": 100,
                },
            ],
        }
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="Unknown instance"):
            ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})

    def test_invalid_template_property_rejected(self):
        """Pure Pydantic validation - no DB needed."""
        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Bad Template Prop",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.password}}",
                    "execution_order": 100,
                },
            ],
        }
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="Unknown property"):
            ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ExperimentScript")
    @patch("cms.experiments.services.Experiment")
    @patch("cms.experiments.services.ScriptAsset")
    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_valid_template_variable_accepted(
        self, mock_check, mock_load, mock_script_model, mock_exp_model, mock_es_model, mock_audit, user
    ):
        mock_workstation = MagicMock()
        mock_workstation.name = "Workstation"
        mock_attacker = MagicMock()
        mock_attacker.name = "Attacker"
        mock_template = MagicMock()
        mock_template.instances = [mock_workstation, mock_attacker]
        mock_load.return_value = mock_template

        mock_exp = _make_experiment(pk=44, user=user)
        mock_exp.scripts.count.return_value = 1
        mock_exp_model.return_value = mock_exp

        instance_names = {"Workstation", "Attacker"}
        input_data = {
            "name": "Good Template",
            "scenario_id": "basic",
            "scripts": [
                {
                    "instance_name": "Attacker",
                    "script_type": "claude_code",
                    "claude_prompt": "Attack {{Workstation.ip}} named {{Workstation.name}}",
                    "execution_order": 100,
                },
            ],
        }
        data = ExperimentCreateInput.model_validate(input_data, context={"instance_names": instance_names})
        exp = services.create_experiment(user, data)
        assert exp.pk == 44


# ---------------------------------------------------------------------------
# CreateExperimentAccessTest
# ---------------------------------------------------------------------------


class TestCreateExperimentAccess:
    """Verify that create_experiment enforces scenario access controls."""

    @pytest.fixture()
    def staff_user(self):
        return _make_user(pk=1, username="access_staff", is_staff=True)

    @pytest.fixture()
    def regular_user(self):
        return _make_user(pk=2, username="access_regular", is_staff=False)

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_disabled_scenario_blocked_for_non_staff(self, mock_check, mock_load, regular_user):
        mock_check.side_effect = ValueError("Scenario is disabled")

        data = ExperimentCreateInput(name="Blocked", scenario_id="basic")
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.create_experiment(regular_user, data)

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_staff_only_scenario_blocked_for_non_staff(self, mock_check, mock_load, regular_user):
        mock_check.side_effect = ValueError("Scenario is staff-only")

        data = ExperimentCreateInput(name="Blocked", scenario_id="basic")
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.create_experiment(regular_user, data)

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ExperimentScript")
    @patch("cms.experiments.services.Experiment")
    @patch("cms.experiments.services.ScriptAsset")
    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_staff_only_scenario_allowed_for_staff(
        self, mock_check, mock_load, mock_script_model, mock_exp_model, mock_es_model, mock_audit, staff_user
    ):
        mock_instance = MagicMock()
        mock_instance.name = "Workstation"
        mock_template = MagicMock()
        mock_template.instances = [mock_instance]
        mock_load.return_value = mock_template

        mock_exp = _make_experiment(pk=50, user=staff_user)
        mock_exp_model.return_value = mock_exp

        data = ExperimentCreateInput(name="Allowed", scenario_id="basic")
        exp = services.create_experiment(staff_user, data)
        assert exp.pk == 50


# ---------------------------------------------------------------------------
# StartExperimentTest
# ---------------------------------------------------------------------------


class TestStartExperiment:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="start_user")

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.publish_experiment_event")
    @patch("cms.experiments.services.ExperimentRun")
    @patch("cms.experiments.services.Experiment")
    def test_start_creates_runs_and_queues(self, mock_exp_model, mock_run_model, mock_publish, mock_audit, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=60, user=user, status=ExperimentStatus.DRAFT.value, total_runs=3)
        mock_exp_model.objects.select_for_update.return_value.get.return_value = mock_exp

        result = services.start_experiment(user, 60)

        assert mock_run_model.objects.bulk_create.called
        mock_exp.transition_to.assert_called_once_with(ExperimentStatus.QUEUED)
        assert result is mock_exp

    @patch("cms.experiments.services.Experiment")
    def test_start_non_draft_raises(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=61, user=user, status=ExperimentStatus.QUEUED.value)
        mock_exp_model.objects.select_for_update.return_value.get.return_value = mock_exp

        with pytest.raises(ExperimentStateError, match="draft state"):
            services.start_experiment(user, 61)

    @patch("cms.experiments.services.Experiment")
    def test_start_nonexistent_raises(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp_model.objects.select_for_update.return_value.get.side_effect = mock_exp_model.DoesNotExist

        with pytest.raises(ExperimentError, match="not found"):
            services.start_experiment(user, 99999)

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.publish_experiment_event")
    @patch("cms.experiments.services.ExperimentRun")
    @patch("cms.experiments.services.Experiment")
    def test_start_publishes_event(self, mock_exp_model, mock_run_model, mock_publish, mock_audit, user):
        """Verify that starting an experiment publishes experiment.start event."""
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=62, user=user, status=ExperimentStatus.DRAFT.value, total_runs=1)
        mock_exp_model.objects.select_for_update.return_value.get.return_value = mock_exp

        services.start_experiment(user, 62)

        mock_publish.assert_called_once_with(
            event_type="experiment.start",
            payload={"experiment_id": 62},
        )

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.publish_experiment_event")
    @patch("cms.experiments.services.ExperimentRun")
    @patch("cms.experiments.services.Experiment")
    def test_start_continues_if_event_fails(self, mock_exp_model, mock_run_model, mock_publish, mock_audit, user):
        """Verify that experiment start succeeds even if event publishing fails."""
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_publish.side_effect = Exception("SQS unavailable")

        mock_exp = _make_experiment(pk=63, user=user, status=ExperimentStatus.DRAFT.value, total_runs=1)
        mock_exp_model.objects.select_for_update.return_value.get.return_value = mock_exp

        result = services.start_experiment(user, 63)

        mock_exp.transition_to.assert_called_once_with(ExperimentStatus.QUEUED)
        assert result is mock_exp


# ---------------------------------------------------------------------------
# CancelExperimentTest
# ---------------------------------------------------------------------------


class TestCancelExperiment:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="cancel_user")

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.Experiment")
    def test_cancel_queued(self, mock_exp_model, mock_audit, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=70, user=user, status=ExperimentStatus.QUEUED.value)
        mock_exp_model.objects.get.return_value = mock_exp

        result = services.cancel_experiment(user, 70)

        mock_exp.transition_to.assert_called_once_with(ExperimentStatus.CANCELLED)
        assert result is mock_exp

    @patch("cms.experiments.services.Experiment")
    def test_cancel_draft_raises(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=71, user=user, status=ExperimentStatus.DRAFT.value)
        mock_exp_model.objects.get.return_value = mock_exp

        with pytest.raises(ExperimentStateError, match="Cannot cancel"):
            services.cancel_experiment(user, 71)


# ---------------------------------------------------------------------------
# GetExperimentTest
# ---------------------------------------------------------------------------


class TestGetExperiment:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="get_user")

    @pytest.fixture()
    def other_user(self):
        return _make_user(pk=2, username="get_other")

    @patch("cms.experiments.services.Experiment")
    def test_get_own_experiment(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp = _make_experiment(pk=80, user=user)
        mock_exp_model.objects.prefetch_related.return_value.get.return_value = mock_exp

        result = services.get_experiment(user, 80)
        assert result.pk == 80

    @patch("cms.experiments.services.Experiment")
    def test_get_other_users_experiment_raises(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp_model.objects.prefetch_related.return_value.get.side_effect = mock_exp_model.DoesNotExist

        with pytest.raises(ExperimentError, match="not found"):
            services.get_experiment(user, 99)


# ---------------------------------------------------------------------------
# ListExperimentsTest
# ---------------------------------------------------------------------------


class TestListExperiments:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="list_user")

    @patch("cms.experiments.services.Experiment")
    def test_list_returns_experiments(self, mock_exp_model, user):
        qs = MagicMock()
        qs.count.return_value = 1
        mock_exp_model.objects.filter.return_value.annotate.return_value.order_by.return_value = qs

        exps = services.list_experiments(user)
        assert exps.count() == 1

    @patch("cms.experiments.services.Experiment")
    def test_annotates_run_counts(self, mock_exp_model, user):
        mock_exp = MagicMock()
        mock_exp.total_run_count = 3
        mock_exp.completed_runs = 1

        qs = MagicMock()
        qs.first.return_value = mock_exp
        mock_exp_model.objects.filter.return_value.annotate.return_value.order_by.return_value = qs

        exps = services.list_experiments(user)
        exp = exps.first()
        assert exp.total_run_count == 3
        assert exp.completed_runs == 1


# ---------------------------------------------------------------------------
# ScenarioInstancesTest
# ---------------------------------------------------------------------------


class TestScenarioInstances:
    @patch("cms.experiments.services.load_scenario_template")
    def test_basic_scenario_returns_instances(self, mock_load):
        mock_inst = MagicMock()
        mock_inst.name = "Workstation"
        mock_inst.role = "victim"
        mock_inst.os_type = "windows"
        mock_template = MagicMock()
        mock_template.instances = [mock_inst]
        mock_load.return_value = mock_template

        instances = services.get_scenario_instances("basic")
        assert len(instances) == 1
        assert instances[0]["name"] == "Workstation"

    @patch("cms.experiments.services.load_scenario_template")
    def test_invalid_scenario_raises(self, mock_load):
        mock_load.side_effect = ValueError("Scenario not found")

        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.get_scenario_instances("nonexistent_scenario_123")


# ---------------------------------------------------------------------------
# UserValidationTest
# ---------------------------------------------------------------------------


class TestUserValidation:
    """Verify service functions reject None/invalid users."""

    def test_list_scripts_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_scripts(None)

    def test_create_experiment_none_user(self):
        data = ExperimentCreateInput(name="Test", scenario_id="basic")
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.create_experiment(None, data)

    def test_start_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.start_experiment(None, 1)

    def test_get_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_experiment(None, 1)

    def test_list_experiments_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.list_experiments(None)

    def test_delete_script_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.delete_script(None, 1)

    def test_cancel_experiment_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.cancel_experiment(None, 1)


# ---------------------------------------------------------------------------
# CatchAllExceptionTest
# ---------------------------------------------------------------------------


class TestCatchAllException:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="catchall_user")

    @patch("cms.experiments.services.Experiment")
    def test_get_experiment_logs_unexpected_error(self, mock_exp_model, user):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_exp_model.objects.prefetch_related.return_value.get.side_effect = RuntimeError("DB gone")

        with pytest.raises(RuntimeError, match="DB gone"):
            services.get_experiment(user, 1)


# ---------------------------------------------------------------------------
# ConcurrentStartTest - mocked select_for_update behavior
# ---------------------------------------------------------------------------


class TestConcurrentStart:
    """Verify that concurrent start_experiment() calls are serialized by select_for_update().

    Since we mock away the DB, we simulate the concurrency guard by having the
    second call see a non-draft status after the first call transitions it.
    """

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.publish_experiment_event")
    @patch("cms.experiments.services.ExperimentRun")
    @patch("cms.experiments.services.Experiment")
    def test_only_one_concurrent_start_succeeds(self, mock_exp_model, mock_run_model, mock_publish, mock_audit):
        mock_exp_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        user = _make_user(pk=1, username="concurrent_user")

        # First call sees DRAFT, second call sees QUEUED (simulating the lock)
        mock_exp_first = _make_experiment(pk=90, user=user, status=ExperimentStatus.DRAFT.value, total_runs=3)
        mock_exp_second = _make_experiment(pk=90, user=user, status=ExperimentStatus.QUEUED.value, total_runs=3)

        call_count = {"n": 0}

        def get_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_exp_first
            return mock_exp_second

        mock_exp_model.objects.select_for_update.return_value.get.side_effect = get_side_effect

        # First call succeeds
        result = services.start_experiment(user, 90)
        mock_exp_first.transition_to.assert_called_once_with(ExperimentStatus.QUEUED)
        assert result is mock_exp_first

        # Second call fails because status is now QUEUED
        with pytest.raises(ExperimentStateError, match="draft state"):
            services.start_experiment(user, 90)
