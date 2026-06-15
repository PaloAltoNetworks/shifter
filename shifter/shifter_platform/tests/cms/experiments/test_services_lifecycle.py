"""Tests for experiment services.

Tests the business logic without calling real S3/infrastructure or the database.
All ORM access is mocked.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, call, patch

import pytest

from cms.experiments import services
from cms.experiments.exceptions import (
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
)
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus, RunStatus
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


def _make_user(pk=1, username="testuser", is_staff=True, is_active=True, threat_research=False):
    """Create a MagicMock user with the minimum attributes services need.

    The ``threat_research`` flag controls what
    ``user.groups.filter(name=THREAT_RESEARCH_GROUP).exists()`` returns —
    set to ``True`` for non-staff Threat Research members. Default ``False``
    so non-staff fixtures resolve as unrelated authenticated users.
    """
    user = MagicMock()
    user.pk = pk
    user.id = pk
    user.username = username
    user.is_staff = is_staff
    user.is_active = is_active
    user.groups.filter.return_value.exists.return_value = bool(threat_research)
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

        mock_run_model.assert_has_calls(
            [
                call(experiment=mock_exp, run_number=1),
                call(experiment=mock_exp, run_number=2),
                call(experiment=mock_exp, run_number=3),
            ]
        )
        bulk_create_args = mock_run_model.objects.bulk_create.call_args.args
        assert len(bulk_create_args) == 1
        assert len(bulk_create_args[0]) == mock_exp.total_runs

        from cms.experiments.models import ExperimentRun

        status_field = ExperimentRun._meta.get_field("status")
        assert status_field.default == RunStatus.PENDING.value
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
