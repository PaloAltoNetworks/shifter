"""Tests for behaviour DSL schemas - actions, steps, objectives, and behaviours."""

import pytest


class TestActionSpecValidation:
    """Tests for Action spec validation."""

    def test_generic_action_creates_with_valid_operation(self):
        """GenericActionSpec creates with valid operation."""
        from cyberscript.schemas import GenericActionSpec

        action = GenericActionSpec(
            name="Test action",
            description="A test action",
            operation="do_something",
            parameters={"key": "value"},
        )
        assert action.action_type == "generic"
        assert action.operation == "do_something"
        assert action.parameters == {"key": "value"}

    def test_generic_action_rejects_empty_operation(self):
        """GenericActionSpec rejects empty operation."""
        from cyberscript.schemas import GenericActionSpec

        with pytest.raises(ValueError, match="operation cannot be empty"):
            GenericActionSpec(
                name="Test action",
                operation="",
            )

    def test_generic_action_rejects_whitespace_operation(self):
        """GenericActionSpec rejects whitespace-only operation."""
        from cyberscript.schemas import GenericActionSpec

        with pytest.raises(ValueError, match="operation cannot be empty"):
            GenericActionSpec(
                name="Test action",
                operation="   ",
            )

    def test_command_action_creates_with_valid_command(self):
        """CommandActionSpec creates with valid command."""
        from cyberscript.schemas import CommandActionSpec

        action = CommandActionSpec(
            name="Run whoami",
            description="Execute whoami command",
            command="whoami",
            shell="/bin/bash",
            timeout_seconds=60,
        )
        assert action.action_type == "command"
        assert action.command == "whoami"
        assert action.shell == "/bin/bash"
        assert action.timeout_seconds == 60

    def test_command_action_rejects_empty_command(self):
        """CommandActionSpec rejects empty command."""
        from cyberscript.schemas import CommandActionSpec

        with pytest.raises(ValueError, match="command cannot be empty"):
            CommandActionSpec(
                name="Test",
                command="",
            )

    def test_command_action_rejects_non_positive_timeout(self):
        """CommandActionSpec rejects non-positive timeout."""
        from cyberscript.schemas import CommandActionSpec

        with pytest.raises(ValueError, match="timeout_seconds must be a positive"):
            CommandActionSpec(
                name="Test",
                command="whoami",
                timeout_seconds=0,
            )

    def test_file_action_creates_with_valid_path(self):
        """FileActionSpec creates with valid path."""
        from cyberscript.schemas import FileActionSpec

        action = FileActionSpec(
            name="Read passwd",
            file_operation="read",
            path="/etc/passwd",
        )
        assert action.action_type == "file"
        assert action.file_operation == "read"
        assert action.path == "/etc/passwd"

    def test_file_action_rejects_empty_path(self):
        """FileActionSpec rejects empty path."""
        from cyberscript.schemas import FileActionSpec

        with pytest.raises(ValueError, match="path cannot be empty"):
            FileActionSpec(
                name="Test",
                file_operation="read",
                path="",
            )

    def test_network_action_creates_with_valid_target(self):
        """NetworkActionSpec creates with valid target."""
        from cyberscript.schemas import NetworkActionSpec

        action = NetworkActionSpec(
            name="Connect to server",
            network_operation="connect",
            target_host="192.168.1.1",
            target_port=22,
            protocol="tcp",
        )
        assert action.action_type == "network"
        assert action.network_operation == "connect"
        assert action.target_host == "192.168.1.1"
        assert action.target_port == 22

    def test_network_action_rejects_invalid_port(self):
        """NetworkActionSpec rejects invalid port numbers."""
        from cyberscript.schemas import NetworkActionSpec

        with pytest.raises(ValueError, match="target_port must be between 1 and 65535"):
            NetworkActionSpec(
                name="Test",
                network_operation="connect",
                target_port=70000,
            )

        with pytest.raises(ValueError, match="target_port must be between 1 and 65535"):
            NetworkActionSpec(
                name="Test",
                network_operation="connect",
                target_port=0,
            )

    def test_action_preconditions_rejects_empty_strings(self):
        """ActionSpecBase rejects empty precondition strings."""
        from cyberscript.schemas import GenericActionSpec

        with pytest.raises(ValueError, match="Condition at index 1 cannot be empty"):
            GenericActionSpec(
                name="Test",
                operation="test",
                preconditions=["valid_condition", ""],
            )

    def test_action_effects_rejects_empty_strings(self):
        """ActionSpecBase rejects empty effect strings."""
        from cyberscript.schemas import GenericActionSpec

        with pytest.raises(ValueError, match="Condition at index 0 cannot be empty"):
            GenericActionSpec(
                name="Test",
                operation="test",
                effects=["  "],
            )

    def test_action_discriminated_union_routing(self):
        """ActionSpec discriminated union routes correctly."""
        from cyberscript.schemas import ActionSpec, CommandActionSpec, GenericActionSpec

        from pydantic import TypeAdapter

        adapter = TypeAdapter(ActionSpec)

        # Parse generic action
        generic_data = {"action_type": "generic", "operation": "test"}
        action = adapter.validate_python(generic_data)
        assert isinstance(action, GenericActionSpec)

        # Parse command action
        command_data = {"action_type": "command", "command": "whoami"}
        action = adapter.validate_python(command_data)
        assert isinstance(action, CommandActionSpec)


class TestStepSpecValidation:
    """Tests for Step spec validation."""

    def test_step_creates_with_valid_action(self):
        """StepSpec creates with valid action."""
        from cyberscript.schemas import CommandActionSpec, FailureAction, StepSpec

        action = CommandActionSpec(
            name="Run command",
            command="whoami",
        )
        step = StepSpec(
            name="Execute whoami",
            description="Run the whoami command",
            action=action,
            order=0,
            timeout_seconds=60,
            on_failure=FailureAction.ABORT,
        )
        assert step.name == "Execute whoami"
        assert step.order == 0
        assert step.action.action_type == "command"
        assert step.on_failure == FailureAction.ABORT

    def test_step_rejects_negative_order(self):
        """StepSpec rejects negative order."""
        from cyberscript.schemas import GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")

        with pytest.raises(ValueError, match="order must be non-negative"):
            StepSpec(
                name="Test",
                action=action,
                order=-1,
            )

    def test_step_rejects_non_positive_timeout(self):
        """StepSpec rejects non-positive timeout."""
        from cyberscript.schemas import GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")

        with pytest.raises(ValueError, match="timeout_seconds must be a positive"):
            StepSpec(
                name="Test",
                action=action,
                timeout_seconds=0,
            )

    def test_step_rejects_negative_max_retries(self):
        """StepSpec rejects negative max_retries."""
        from cyberscript.schemas import GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")

        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            StepSpec(
                name="Test",
                action=action,
                max_retries=-1,
            )

    def test_step_validates_retry_configuration(self):
        """StepSpec validates retry configuration consistency."""
        from cyberscript.schemas import FailureAction, GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")

        with pytest.raises(ValueError, match="max_retries must be > 0 when on_failure is RETRY"):
            StepSpec(
                name="Test",
                action=action,
                on_failure=FailureAction.RETRY,
                max_retries=0,
            )

    def test_step_rejects_empty_dependency_names(self):
        """StepSpec rejects empty dependency names."""
        from cyberscript.schemas import GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")

        with pytest.raises(ValueError, match="Dependency at index 0 cannot be empty"):
            StepSpec(
                name="Test",
                action=action,
                depends_on=[""],
            )


class TestObjectiveSpecValidation:
    """Tests for Objective spec validation."""

    def test_objective_creates_with_valid_description(self):
        """ObjectiveSpec creates with valid description."""
        from cyberscript.schemas import ObjectivePriority, ObjectiveSpec, ObjectiveType

        objective = ObjectiveSpec(
            name="Gain access",
            description="Obtain shell access to the target system",
            objective_type=ObjectiveType.ACHIEVE,
            priority=ObjectivePriority.CRITICAL,
        )
        assert objective.name == "Gain access"
        assert objective.description == "Obtain shell access to the target system"
        assert objective.objective_type == ObjectiveType.ACHIEVE
        assert objective.priority == ObjectivePriority.CRITICAL

    def test_objective_rejects_empty_description(self):
        """ObjectiveSpec rejects empty description."""
        from cyberscript.schemas import ObjectiveSpec

        with pytest.raises(ValueError, match="description cannot be empty"):
            ObjectiveSpec(
                name="Test",
                description="",
            )

    def test_objective_rejects_whitespace_description(self):
        """ObjectiveSpec rejects whitespace-only description."""
        from cyberscript.schemas import ObjectiveSpec

        with pytest.raises(ValueError, match="description cannot be empty"):
            ObjectiveSpec(
                name="Test",
                description="   ",
            )

    def test_objective_rejects_empty_tag_strings(self):
        """ObjectiveSpec rejects empty tag strings."""
        from cyberscript.schemas import ObjectiveSpec

        with pytest.raises(ValueError, match="Item at index 1 cannot be empty"):
            ObjectiveSpec(
                name="Test",
                description="Valid description",
                tags=["MITRE:T1059", ""],
            )

    def test_objective_type_enum_values(self):
        """ObjectiveType enum has expected values."""
        from cyberscript.schemas import ObjectiveType

        assert ObjectiveType.ACHIEVE == "achieve"
        assert ObjectiveType.MAINTAIN == "maintain"
        assert ObjectiveType.PREVENT == "prevent"

    def test_objective_priority_enum_values(self):
        """ObjectivePriority enum has expected values."""
        from cyberscript.schemas import ObjectivePriority

        assert ObjectivePriority.CRITICAL == "critical"
        assert ObjectivePriority.HIGH == "high"
        assert ObjectivePriority.MEDIUM == "medium"
        assert ObjectivePriority.LOW == "low"


class TestBehaviourSpecValidation:
    """Tests for Behaviour spec validation."""

    def test_attack_behaviour_creates_with_valid_data(self):
        """AttackBehaviourSpec creates with valid data."""
        from cyberscript.schemas import (
            AttackBehaviourSpec,
            CapabilityType,
            CommandActionSpec,
            ObjectivePriority,
            ObjectiveSpec,
            ObjectiveType,
            StepSpec,
        )

        action = CommandActionSpec(command="whoami")
        step = StepSpec(name="Step 1", action=action, order=0)
        objective = ObjectiveSpec(
            name="Objective 1",
            description="Test objective",
            objective_type=ObjectiveType.ACHIEVE,
            priority=ObjectivePriority.CRITICAL,
        )

        behaviour = AttackBehaviourSpec(
            name="Recon",
            description="Basic reconnaissance behavior",
            objectives=[objective],
            steps=[step],
            required_capabilities=[CapabilityType.SHELL_ACCESS],
            target_os_types=["linux", "windows"],
            version="1.0.0",
        )
        assert behaviour.behaviour_type == "attack"
        assert behaviour.name == "Recon"
        assert len(behaviour.objectives) == 1
        assert len(behaviour.steps) == 1
        assert CapabilityType.SHELL_ACCESS in behaviour.required_capabilities

    def test_defender_behaviour_creates_with_valid_data(self):
        """DefenderBehaviourSpec creates with valid data."""
        from cyberscript.schemas import DefenderBehaviourSpec

        behaviour = DefenderBehaviourSpec(
            name="Detection",
            description="Detect suspicious activity",
        )
        assert behaviour.behaviour_type == "defender"

    def test_simulated_user_behaviour_creates_with_valid_data(self):
        """SimulatedUserBehaviourSpec creates with valid data."""
        from cyberscript.schemas import SimulatedUserBehaviourSpec

        behaviour = SimulatedUserBehaviourSpec(
            name="Normal user",
            description="Simulate normal user activity",
        )
        assert behaviour.behaviour_type == "simulated_user"

    def test_behaviour_rejects_empty_version(self):
        """BehaviourSpecBase rejects empty version."""
        from cyberscript.schemas import AttackBehaviourSpec

        with pytest.raises(ValueError, match="version cannot be empty"):
            AttackBehaviourSpec(
                name="Test",
                version="",
            )

    def test_behaviour_rejects_empty_tag_strings(self):
        """BehaviourSpecBase rejects empty tag strings."""
        from cyberscript.schemas import AttackBehaviourSpec

        with pytest.raises(ValueError, match="Tag at index 0 cannot be empty"):
            AttackBehaviourSpec(
                name="Test",
                tags=["  "],
            )

    def test_behaviour_validates_unique_step_orders(self):
        """BehaviourSpecBase validates that step orders are unique."""
        from cyberscript.schemas import AttackBehaviourSpec, GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")
        step1 = StepSpec(name="Step 1", action=action, order=0)
        step2 = StepSpec(name="Step 2", action=action, order=0)  # Duplicate order

        with pytest.raises(ValueError, match="Step orders must be unique"):
            AttackBehaviourSpec(
                name="Test",
                steps=[step1, step2],
            )

    def test_behaviour_validates_step_dependencies(self):
        """BehaviourSpecBase validates step dependencies reference existing steps."""
        from cyberscript.schemas import AttackBehaviourSpec, GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")
        step = StepSpec(name="Step 1", action=action, order=0, depends_on=["NonExistent"])

        with pytest.raises(ValueError, match="depends on unknown step 'NonExistent'"):
            AttackBehaviourSpec(
                name="Test",
                steps=[step],
            )

    def test_behaviour_sorted_steps_property(self):
        """BehaviourSpecBase.sorted_steps returns steps in order."""
        from cyberscript.schemas import AttackBehaviourSpec, GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")
        step1 = StepSpec(name="Step 1", action=action, order=2)
        step2 = StepSpec(name="Step 2", action=action, order=0)
        step3 = StepSpec(name="Step 3", action=action, order=1)

        behaviour = AttackBehaviourSpec(
            name="Test",
            steps=[step1, step2, step3],
        )

        sorted_names = [s.name for s in behaviour.sorted_steps]
        assert sorted_names == ["Step 2", "Step 3", "Step 1"]

    def test_behaviour_critical_objectives_property(self):
        """BehaviourSpecBase.critical_objectives returns critical priority objectives."""
        from cyberscript.schemas import (
            AttackBehaviourSpec,
            ObjectivePriority,
            ObjectiveSpec,
        )

        obj1 = ObjectiveSpec(
            name="Obj 1",
            description="Critical objective",
            priority=ObjectivePriority.CRITICAL,
        )
        obj2 = ObjectiveSpec(
            name="Obj 2",
            description="High objective",
            priority=ObjectivePriority.HIGH,
        )
        obj3 = ObjectiveSpec(
            name="Obj 3",
            description="Another critical",
            priority=ObjectivePriority.CRITICAL,
        )

        behaviour = AttackBehaviourSpec(
            name="Test",
            objectives=[obj1, obj2, obj3],
        )

        critical = behaviour.critical_objectives
        assert len(critical) == 2
        assert all(o.priority == ObjectivePriority.CRITICAL for o in critical)

    def test_behaviour_has_verification_steps_property(self):
        """BehaviourSpecBase.has_verification_steps property works correctly."""
        from cyberscript.schemas import AttackBehaviourSpec, GenericActionSpec, StepSpec

        action = GenericActionSpec(operation="test")
        step1 = StepSpec(name="Step 1", action=action, order=0, is_verification=False)
        step2 = StepSpec(name="Step 2", action=action, order=1, is_verification=True)

        behaviour_with_verify = AttackBehaviourSpec(
            name="Test",
            steps=[step1, step2],
        )
        assert behaviour_with_verify.has_verification_steps is True

        behaviour_without_verify = AttackBehaviourSpec(
            name="Test",
            steps=[step1],
        )
        assert behaviour_without_verify.has_verification_steps is False

    def test_behaviour_discriminated_union_routing(self):
        """BehaviourSpec discriminated union routes correctly."""
        from cyberscript.schemas import (
            AttackBehaviourSpec,
            BehaviourSpec,
            DefenderBehaviourSpec,
            SimulatedUserBehaviourSpec,
        )

        from pydantic import TypeAdapter

        adapter = TypeAdapter(BehaviourSpec)

        # Parse attack behaviour
        attack_data = {"behaviour_type": "attack", "name": "Test attack"}
        behaviour = adapter.validate_python(attack_data)
        assert isinstance(behaviour, AttackBehaviourSpec)

        # Parse defender behaviour
        defender_data = {"behaviour_type": "defender", "name": "Test defender"}
        behaviour = adapter.validate_python(defender_data)
        assert isinstance(behaviour, DefenderBehaviourSpec)

        # Parse simulated_user behaviour
        user_data = {"behaviour_type": "simulated_user", "name": "Test user"}
        behaviour = adapter.validate_python(user_data)
        assert isinstance(behaviour, SimulatedUserBehaviourSpec)


class TestBehaviourContextValidation:
    """Tests for Behaviour context validation."""

    def test_behaviour_context_rejects_invalid_behaviour_id(self):
        """BehaviourContextBase rejects invalid behaviour_id."""
        from cyberscript.schemas import AttackBehaviourContext

        with pytest.raises(ValueError, match="behaviour_id must be a positive integer"):
            AttackBehaviourContext(
                behaviour_id=0,
                name="Test",
            )

        with pytest.raises(ValueError, match="behaviour_id cannot be empty"):
            AttackBehaviourContext(
                behaviour_id="  ",
                name="Test",
            )

    def test_behaviour_context_accepts_valid_ids(self):
        """BehaviourContextBase accepts valid behaviour_ids."""
        from cyberscript.schemas import AttackBehaviourContext

        # Integer ID
        ctx = AttackBehaviourContext(behaviour_id=1, name="Test")
        assert ctx.behaviour_id == 1

        # String ID
        ctx = AttackBehaviourContext(behaviour_id="abc-123", name="Test")
        assert ctx.behaviour_id == "abc-123"

    def test_behaviour_context_computed_properties(self):
        """BehaviourContextBase computed properties work correctly."""
        from cyberscript.schemas import AttackBehaviourContext, BehaviourStatus

        ctx = AttackBehaviourContext(
            behaviour_id=1,
            name="Test",
            status=BehaviourStatus.RUNNING,
        )
        assert ctx.is_running is True
        assert ctx.is_complete is False

        ctx = AttackBehaviourContext(
            behaviour_id=1,
            name="Test",
            status=BehaviourStatus.COMPLETED,
        )
        assert ctx.is_running is False
        assert ctx.is_complete is True


class TestBehaviourResultValidation:
    """Tests for BehaviourResult validation."""

    def test_behaviour_result_rejects_negative_counts(self):
        """BehaviourResult rejects negative counts."""
        from cyberscript.schemas import BehaviourResult, BehaviourStatus

        with pytest.raises(ValueError, match="Count must be non-negative"):
            BehaviourResult(
                behaviour_id=1,
                status=BehaviourStatus.COMPLETED,
                objectives_achieved=-1,
            )

    def test_behaviour_result_rejects_negative_duration(self):
        """BehaviourResult rejects negative duration."""
        from cyberscript.schemas import BehaviourResult, BehaviourStatus

        with pytest.raises(ValueError, match="duration_seconds must be non-negative"):
            BehaviourResult(
                behaviour_id=1,
                status=BehaviourStatus.COMPLETED,
                duration_seconds=-1.0,
            )

    def test_behaviour_result_success_rate(self):
        """BehaviourResult.success_rate calculates correctly."""
        from cyberscript.schemas import BehaviourResult, BehaviourStatus

        # 3 achieved, 1 failed = 75% success
        result = BehaviourResult(
            behaviour_id=1,
            status=BehaviourStatus.COMPLETED,
            objectives_achieved=3,
            objectives_failed=1,
        )
        assert result.success_rate == 0.75

        # No objectives = 0%
        result = BehaviourResult(
            behaviour_id=1,
            status=BehaviourStatus.COMPLETED,
            objectives_achieved=0,
            objectives_failed=0,
        )
        assert result.success_rate == 0.0

    def test_behaviour_result_is_successful(self):
        """BehaviourResult.is_successful works correctly."""
        from cyberscript.schemas import BehaviourResult, BehaviourStatus

        # Completed with no failures = successful
        result = BehaviourResult(
            behaviour_id=1,
            status=BehaviourStatus.COMPLETED,
            objectives_achieved=3,
            objectives_failed=0,
        )
        assert result.is_successful is True

        # Completed with failures = not successful
        result = BehaviourResult(
            behaviour_id=1,
            status=BehaviourStatus.COMPLETED,
            objectives_achieved=3,
            objectives_failed=1,
        )
        assert result.is_successful is False

        # Not completed = not successful
        result = BehaviourResult(
            behaviour_id=1,
            status=BehaviourStatus.FAILED,
            objectives_achieved=0,
            objectives_failed=0,
        )
        assert result.is_successful is False


class TestCapabilityTypeEnum:
    """Tests for CapabilityType enum."""

    def test_capability_type_values(self):
        """CapabilityType enum has expected values."""
        from cyberscript.schemas import CapabilityType

        assert CapabilityType.SHELL_ACCESS == "shell_access"
        assert CapabilityType.ROOT_ACCESS == "root_access"
        assert CapabilityType.NETWORK_ACCESS == "network_access"
        assert CapabilityType.FILE_SYSTEM_ACCESS == "file_system_access"
        assert CapabilityType.PROCESS_CONTROL == "process_control"
        assert CapabilityType.USER_CONTEXT == "user_context"
        assert CapabilityType.GUI_ACCESS == "gui_access"
        assert CapabilityType.ADMIN_ACCESS == "admin_access"


class TestStepResultValidation:
    """Tests for StepResult validation."""

    def test_step_result_rejects_empty_step_id(self):
        """StepResult rejects empty step_id."""
        from cyberscript.schemas.step import StepResult, StepStatus

        with pytest.raises(ValueError, match="step_id cannot be empty"):
            StepResult(
                step_id="",
                status=StepStatus.SUCCEEDED,
            )

    def test_step_result_rejects_negative_duration(self):
        """StepResult rejects negative duration."""
        from cyberscript.schemas.step import StepResult, StepStatus

        with pytest.raises(ValueError, match="duration_seconds must be non-negative"):
            StepResult(
                step_id="test-step",
                status=StepStatus.SUCCEEDED,
                duration_seconds=-1.0,
            )

    def test_step_result_rejects_negative_retries(self):
        """StepResult rejects negative retries_used."""
        from cyberscript.schemas.step import StepResult, StepStatus

        with pytest.raises(ValueError, match="retries_used must be non-negative"):
            StepResult(
                step_id="test-step",
                status=StepStatus.SUCCEEDED,
                retries_used=-1,
            )


class TestObjectiveResultValidation:
    """Tests for ObjectiveResult validation."""

    def test_objective_result_rejects_empty_objective_id(self):
        """ObjectiveResult rejects empty objective_id."""
        from cyberscript.schemas.objective import ObjectiveResult, ObjectiveStatus

        with pytest.raises(ValueError, match="objective_id cannot be empty"):
            ObjectiveResult(
                objective_id="",
                status=ObjectiveStatus.ACHIEVED,
            )

    def test_objective_result_creates_with_valid_data(self):
        """ObjectiveResult creates with valid data."""
        from cyberscript.schemas.objective import ObjectiveResult, ObjectiveStatus

        result = ObjectiveResult(
            objective_id="obj-123",
            status=ObjectiveStatus.ACHIEVED,
            achieved_at_step="Step 3",
            evaluation_notes="Objective met after successful command execution",
        )
        assert result.objective_id == "obj-123"
        assert result.status == ObjectiveStatus.ACHIEVED
        assert result.achieved_at_step == "Step 3"
