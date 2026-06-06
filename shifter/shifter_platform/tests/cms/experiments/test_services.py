"""Tests for experiment services.

Tests the business logic without calling real S3/infrastructure or the database.
All ORM access is mocked.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import PermissionDenied

from cms.experiments import services
from cms.experiments.exceptions import (
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.schemas import ExperimentCreateInput, ExperimentStatus

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


class TestListScripts:
    @pytest.fixture()
    def user(self):
        return _make_user(pk=1, username="svc_user")

    @pytest.fixture()
    def other_user(self):
        return _make_user(pk=2, username="other_user")

    @patch("cms.experiments.services.ScriptAsset")
    def test_returns_only_active_for_user(self, mock_script_model, user):
        """list_scripts queries ScriptAsset.objects (SoftDeleteManager, active-only)."""
        active_script = _make_script(pk=1, user=user, name="Active")
        qs = MagicMock()
        qs.count.return_value = 1
        qs.first.return_value = active_script
        mock_script_model.objects.filter.return_value.order_by.return_value = qs

        scripts = services.list_scripts(user)
        assert scripts.count() == 1
        assert scripts.first().name == "Active"
        mock_script_model.objects.filter.assert_called_once_with(user=user)

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
        """delete_script gets via ScriptAsset.objects (SoftDeleteManager)."""
        mock_script_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        script = _make_script(pk=10, user=user, name="ToDelete")
        script.deleted_at = None
        mock_script_model.objects.get.return_value = script

        services.delete_script(user, 10)

        mock_script_model.objects.get.assert_called_once_with(pk=10, user=user)
        assert script.deleted_at is not None
        script.save.assert_called_once_with(update_fields=["deleted_at"])

    @patch("cms.experiments.services.ScriptAsset")
    def test_cannot_delete_other_users_script(self, mock_script_model, user):
        mock_script_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_script_model.objects.get.side_effect = mock_script_model.DoesNotExist

        with pytest.raises(ScriptUploadError, match="not found"):
            services.delete_script(user, 99)


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


class TestCreateExperimentAccess:
    """Verify create_experiment enforces the canonical CMS authoring policy.

    Policy (see shared.auth.can_edit_cms_authoring): active staff users and
    active Threat Research group members may invoke create_experiment;
    unrelated authenticated users may not. Per-scenario availability is then
    enforced by check_scenario_access.
    """

    @pytest.fixture()
    def staff_user(self):
        return _make_user(pk=1, username="access_staff", is_staff=True)

    @pytest.fixture()
    def threat_research_user(self):
        return _make_user(pk=2, username="access_tr", is_staff=False, threat_research=True)

    @pytest.fixture()
    def unrelated_user(self):
        return _make_user(pk=3, username="access_unrelated", is_staff=False, threat_research=False)

    @pytest.fixture()
    def inactive_threat_research_user(self):
        return _make_user(pk=4, username="access_tr_inactive", is_staff=False, is_active=False, threat_research=True)

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_unrelated_user_blocked_before_disabled_scenario_validation(self, mock_check, mock_load, unrelated_user):
        data = ExperimentCreateInput(name="Blocked", scenario_id="basic")
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            services.create_experiment(unrelated_user, data)
        mock_check.assert_not_called()
        mock_load.assert_not_called()

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_unrelated_user_blocked_before_staff_only_scenario_validation(self, mock_check, mock_load, unrelated_user):
        data = ExperimentCreateInput(name="Blocked", scenario_id="basic")
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            services.create_experiment(unrelated_user, data)
        mock_check.assert_not_called()
        mock_load.assert_not_called()

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_inactive_threat_research_user_blocked(self, mock_check, mock_load, inactive_threat_research_user):
        data = ExperimentCreateInput(name="Blocked", scenario_id="basic")
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            services.create_experiment(inactive_threat_research_user, data)
        mock_check.assert_not_called()
        mock_load.assert_not_called()

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

    @patch("cms.experiments.services.audit_log")
    @patch("cms.experiments.services.ExperimentScript")
    @patch("cms.experiments.services.Experiment")
    @patch("cms.experiments.services.ScriptAsset")
    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_threat_research_user_reaches_scenario_access_check(
        self,
        mock_check,
        mock_load,
        mock_script_model,
        mock_exp_model,
        mock_es_model,
        mock_audit,
        threat_research_user,
    ):
        mock_instance = MagicMock()
        mock_instance.name = "Workstation"
        mock_template = MagicMock()
        mock_template.instances = [mock_instance]
        mock_load.return_value = mock_template

        mock_exp = _make_experiment(pk=51, user=threat_research_user)
        mock_exp_model.return_value = mock_exp

        data = ExperimentCreateInput(name="Allowed", scenario_id="basic")
        exp = services.create_experiment(threat_research_user, data)
        assert exp.pk == 51
        mock_check.assert_called_once_with("basic", threat_research_user)

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_threat_research_user_propagates_scenario_access_rejection(
        self, mock_check, mock_load, threat_research_user
    ):
        """A Threat Research user reaches check_scenario_access; if that rejects
        the scenario (e.g. staff_only=True), the service must surface the
        scenario-level denial — never a generic auth denial.
        """
        mock_check.side_effect = ValueError("Scenario 'hidden-internal' is not available")
        data = ExperimentCreateInput(name="Hidden", scenario_id="hidden-internal")
        with pytest.raises(ExperimentValidationError, match="Invalid scenario"):
            services.create_experiment(threat_research_user, data)
        mock_check.assert_called_once_with("hidden-internal", threat_research_user)
        mock_load.assert_not_called()

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_scenario_instances_blocks_unrelated_user(self, mock_check, mock_load, unrelated_user):
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            services.get_scenario_instances("basic", unrelated_user)
        mock_check.assert_not_called()
        mock_load.assert_not_called()

    @patch("cms.experiments.services.load_scenario_template")
    @patch("cms.experiments.services.check_scenario_access")
    def test_scenario_instances_allows_threat_research_user(self, mock_check, mock_load, threat_research_user):
        mock_template = MagicMock()
        mock_template.instances = []
        mock_load.return_value = mock_template

        result = services.get_scenario_instances("basic", threat_research_user)
        assert result == []
        mock_check.assert_called_once_with("basic", threat_research_user)
