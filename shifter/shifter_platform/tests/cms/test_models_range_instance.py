"""Tests for RangeInstance model.

RangeInstance tracks hydrated scenario configs sent to engine.

After GH issue #446:
- agent field is now a ForeignKey to AgentConfig (nullable)
- range_id remains an IntegerField (not FK) - CMS doesn't own Range
- user_id remains an IntegerField (not FK) - CMS doesn't own User

This decoupled design allows CMS to track:
- Which scenario template was used (scenario_id)
- Which range was created (range_id - integer, not FK)
- Which user requested it (user_id - integer, not FK)
- Which agent was used (agent - FK to AgentConfig, nullable)
"""

from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def RangeInstance():
    """Import and return the RangeInstance model class."""
    from cms.models import RangeInstance

    return RangeInstance


@pytest.fixture
def AgentConfig():
    """Import and return the AgentConfig model class."""
    from cms.models import AgentConfig

    return AgentConfig


@pytest.fixture
def make_agent_config(AgentConfig):
    """Factory that builds an in-memory AgentConfig (no DB save).

    Uses raw FK id columns (user_id, os_id) to avoid needing real
    User / OperatingSystem instances.
    """

    def _factory(**kwargs):
        defaults = {
            "id": 100,
            "name": "Test Agent",
            "user_id": 1,
            "os_id": 1,
            "s3_key": "agents/test/agent.deb",
            "original_filename": "agent.deb",
            "file_size_bytes": 1024,
            "sha256_hash": "a" * 64,
            "deleted_at": None,
        }
        defaults.update(kwargs)
        instance = AgentConfig.__new__(AgentConfig)
        # Initialise Django _state so descriptors work
        from django.db.models.base import ModelState

        instance._state = ModelState()
        for k, v in defaults.items():
            setattr(instance, k, v)
        instance.created_at = kwargs.get("created_at", datetime(2026, 1, 1, 0, 0, 0))
        return instance

    return _factory


@pytest.fixture
def make_range_instance(RangeInstance):
    """Factory that builds an in-memory RangeInstance (no DB save).

    Uses the model constructor which initialises Django's internal _state
    without touching the database.  We pass ``id`` so the instance looks
    like a saved row when tests check ``ri.id is not None``.
    """

    def _factory(**kwargs):
        defaults = {
            "id": 1,
            "range_id": 1,
            "scenario_id": "basic",
            "user_id": 1,
            "agent": None,
            "status": "pending",
            "range_spec": None,
            "deleted_at": None,
        }
        defaults.update(kwargs)
        # RangeInstance(...) sets _state and all field descriptors properly.
        # It does NOT hit the database.
        instance = RangeInstance(**defaults)
        # Manually set created_at since auto_now_add fields are not
        # populated by the constructor (only by save()).
        instance.created_at = kwargs.get("created_at", datetime(2026, 1, 1, 0, 0, 0))
        return instance

    return _factory


# ---------------------------------------------------------------------------
# TestRangeInstanceModel
# ---------------------------------------------------------------------------


class TestRangeInstanceModel:
    """Tests for RangeInstance model."""

    def test_model_can_be_imported(self):
        """RangeInstance model can be imported from cms.models."""
        from cms.models import RangeInstance

        assert RangeInstance is not None

    @pytest.mark.django_db
    def test_can_create_range_instance(self, RangeInstance):
        """RangeInstance can be created with required fields."""
        result = RangeInstance.objects.create(range_id=1, scenario_id="basic", user_id=1)
        assert result.id is not None
        assert result.range_id == 1
        assert result.scenario_id == "basic"
        assert result.user_id == 1
        assert RangeInstance.objects.get(pk=result.pk).range_id == 1

    def test_range_id_is_integer_not_fk(self, make_range_instance):
        """range_id is an IntegerField, not a ForeignKey."""
        from django.db.models import ForeignKey

        from cms.models import RangeInstance

        field = RangeInstance._meta.get_field("range_id")
        assert not isinstance(field, ForeignKey)

        # Should accept any integer value in-memory
        ri = make_range_instance(range_id=99999)
        assert ri.range_id == 99999

    def test_user_id_is_integer_not_fk(self, make_range_instance):
        """user_id is an IntegerField, not a ForeignKey."""
        from django.db.models import ForeignKey

        from cms.models import RangeInstance

        field = RangeInstance._meta.get_field("user_id")
        assert not isinstance(field, ForeignKey)

        ri = make_range_instance(user_id=99999)
        assert ri.user_id == 99999

    def test_agent_is_optional(self, make_range_instance):
        """agent FK can be None (for scenarios that don't require agent)."""
        ri = make_range_instance(agent=None)
        assert ri.agent is None

    def test_scenario_id_stores_template_name(self, make_range_instance):
        """scenario_id stores the template name (not the full config)."""
        ri = make_range_instance(scenario_id="ad_attack_lab")
        assert ri.scenario_id == "ad_attack_lab"

    def test_scenario_id_max_length(self, RangeInstance):
        """scenario_id has reasonable max_length (50 chars)."""
        field = RangeInstance._meta.get_field("scenario_id")
        assert field.max_length == 50

    def test_created_at_auto_set(self, RangeInstance):
        """created_at is auto-set on creation (auto_now_add=True)."""
        field = RangeInstance._meta.get_field("created_at")
        assert field.auto_now_add is True

    def test_range_id_is_optional(self, RangeInstance):
        """RangeInstance allows range_id to be None (for Request-based pattern)."""
        field = RangeInstance._meta.get_field("range_id")
        assert field.null is True

    def test_scenario_id_required(self, RangeInstance):
        """RangeInstance requires a scenario_id (not nullable)."""
        field = RangeInstance._meta.get_field("scenario_id")
        # CharField with null=False means DB enforces NOT NULL
        assert field.null is False

    def test_user_id_required(self, RangeInstance):
        """RangeInstance requires a user_id (not nullable)."""
        field = RangeInstance._meta.get_field("user_id")
        assert field.null is False

    def test_str_representation(self, make_range_instance):
        """RangeInstance has meaningful string representation."""
        ri = make_range_instance(range_id=123, scenario_id="basic")
        str_repr = str(ri)
        # Should contain scenario_id or range_id
        assert "basic" in str_repr or "123" in str_repr

    @pytest.mark.django_db
    def test_can_query_by_range_id(self, RangeInstance):
        """RangeInstance can be queried by range_id."""
        RangeInstance.objects.create(range_id=42, scenario_id="basic", user_id=1)
        assert RangeInstance.objects.filter(range_id=42).count() == 1

    @pytest.mark.django_db
    def test_can_query_by_scenario_id(self, RangeInstance):
        """RangeInstance can be queried by scenario_id."""
        RangeInstance.objects.create(range_id=7, scenario_id="ad_attack_lab", user_id=1)
        assert RangeInstance.objects.filter(scenario_id="ad_attack_lab").count() == 1

    @pytest.mark.django_db
    def test_can_query_by_user_id(self, RangeInstance):
        """RangeInstance can be queried by user_id."""
        RangeInstance.objects.create(range_id=8, scenario_id="basic", user_id=99)
        assert RangeInstance.objects.filter(user_id=99).count() == 1

    def test_unique_range_id(self, RangeInstance):
        """Each range_id should be unique (one RangeInstance per Range)."""
        field = RangeInstance._meta.get_field("range_id")
        assert field.unique is True


# ---------------------------------------------------------------------------
# TestRangeInstanceAgentFK
# ---------------------------------------------------------------------------


class TestRangeInstanceAgentFK:
    """Tests for RangeInstance.agent ForeignKey to AgentConfig.

    GH Issue #446: agent_id IntegerField converted to agent FK to AgentConfig.
    AgentConfig uses soft delete (deleted_at), so FK uses SET_NULL for edge cases.
    """

    def test_agent_is_fk_to_agent_config(self, RangeInstance, AgentConfig):
        """RangeInstance.agent is a ForeignKey to AgentConfig."""
        from django.db.models import ForeignKey

        agent_field = RangeInstance._meta.get_field("agent")
        assert isinstance(agent_field, ForeignKey)
        assert agent_field.related_model == AgentConfig

    def test_agent_fk_is_nullable(self, RangeInstance):
        """RangeInstance.agent can be None (for scenarios without agents)."""
        agent_field = RangeInstance._meta.get_field("agent")
        assert agent_field.null is True

    def test_agent_fk_can_be_set(self, make_range_instance, make_agent_config):
        """RangeInstance.agent can be set to an AgentConfig instance."""
        agent = make_agent_config(id=5, name="Test Agent")

        ri = make_range_instance(agent=agent)
        assert ri.agent == agent
        assert ri.agent.id == 5

    def test_agent_fk_on_delete_is_set_null(self, RangeInstance):
        """FK uses SET_NULL (not CASCADE) - RangeInstance preserved if agent hard-deleted."""
        from django.db.models import SET_NULL

        agent_field = RangeInstance._meta.get_field("agent")
        assert agent_field.remote_field.on_delete == SET_NULL

    def test_agent_fk_works_with_soft_deleted_agent(self, make_range_instance, make_agent_config):
        """RangeInstance.agent FK still works when agent is soft-deleted."""
        agent = make_agent_config(id=10, deleted_at=datetime(2026, 1, 15, 0, 0, 0))

        ri = make_range_instance(agent=agent)
        assert ri.agent == agent
        assert ri.agent.is_deleted is True

    def test_agent_fk_related_name(self, RangeInstance):
        """AgentConfig can access its RangeInstances via related_name."""
        agent_field = RangeInstance._meta.get_field("agent")
        assert agent_field.remote_field.related_name == "range_instances"

    @pytest.mark.django_db
    def test_agent_fk_select_related(self, RangeInstance):
        """RangeInstance.agent can be efficiently loaded with select_related."""
        from django.contrib.auth import get_user_model

        from cms.models import AgentConfig, OperatingSystem

        user = get_user_model().objects.create_user(username="ri-sr@e.com", email="ri-sr@e.com")
        os_obj, _ = OperatingSystem.objects.get_or_create(
            slug="linux-debian", defaults={"name": "Linux", "extensions": [".deb"]}
        )
        agent = AgentConfig.objects.create(
            user=user,
            os=os_obj,
            name="Select Related Agent",
            s3_key="agents/sr.deb",
            original_filename="sr.deb",
            file_size_bytes=1024,
        )
        RangeInstance.objects.create(range_id=105, scenario_id="basic", user_id=user.id, agent=agent)

        result = RangeInstance.objects.select_related("agent").get(range_id=105)
        assert result.agent.name == "Select Related Agent"


# ---------------------------------------------------------------------------
# TestRangeInstanceRangeSpec
# ---------------------------------------------------------------------------


class TestRangeInstanceRangeSpec:
    """Tests for RangeInstance.range_spec JSONField.

    The range_spec field stores the hydrated RangeSpec JSON that was
    sent to the engine during range creation. This allows CMS to
    provide instance details without calling back to the engine.
    """

    def test_range_spec_is_optional(self, RangeInstance):
        """range_spec can be None (field is nullable)."""
        field = RangeInstance._meta.get_field("range_spec")
        assert field.null is True

    def test_range_spec_stores_json(self, make_range_instance):
        """range_spec stores JSON data."""
        spec = {
            "scenario_id": "basic",
            "user_id": 1,
            "instances": [
                {"uuid": "abc-123", "role": "attacker", "os_type": "kali", "join_domain": False},
                {"uuid": "def-456", "role": "victim", "os_type": "windows", "join_domain": False},
            ],
        }

        ri = make_range_instance(range_spec=spec)
        assert ri.range_spec == spec

    def test_range_spec_instances_accessible(self, make_range_instance):
        """range_spec['instances'] can be accessed."""
        spec = {
            "scenario_id": "basic",
            "user_id": 1,
            "instances": [
                {"uuid": "abc-123", "role": "attacker", "os_type": "kali", "join_domain": False},
            ],
        }

        ri = make_range_instance(range_spec=spec)
        assert "instances" in ri.range_spec
        assert len(ri.range_spec["instances"]) == 1
        assert ri.range_spec["instances"][0]["role"] == "attacker"

    @pytest.mark.django_db
    def test_range_spec_persists_after_refresh(self, RangeInstance):
        """range_spec data round-trips through the DB (real refresh_from_db)."""
        spec = {
            "scenario_id": "ad_attack_lab",
            "user_id": 42,
            "instances": [
                {"uuid": "uuid-1", "role": "attacker", "os_type": "kali", "join_domain": False},
                {"uuid": "uuid-2", "role": "dc", "os_type": "windows", "join_domain": False},
                {"uuid": "uuid-3", "role": "victim", "os_type": "windows", "join_domain": True},
            ],
        }

        ri = RangeInstance.objects.create(range_id=203, scenario_id="ad_attack_lab", user_id=42, range_spec=spec)

        ri.refresh_from_db()
        assert ri.range_spec == spec
        assert len(ri.range_spec["instances"]) == 3

    def test_range_spec_with_agent_details(self, make_range_instance):
        """range_spec can include agent details in instances."""
        spec = {
            "scenario_id": "basic",
            "user_id": 1,
            "instances": [
                {
                    "uuid": "victim-uuid",
                    "role": "victim",
                    "os_type": "windows",
                    "join_domain": False,
                    "agent": {
                        "s3_key": "agents/user/agent.msi",
                        "filename": "agent.msi",
                        "sha256": "a" * 64,
                    },
                },
            ],
        }

        ri = make_range_instance(range_spec=spec)
        assert ri.range_spec["instances"][0]["agent"]["s3_key"] == "agents/user/agent.msi"

    def test_range_spec_field_is_json_field(self, RangeInstance):
        """range_spec is a JSONField."""
        from django.db.models import JSONField

        field = RangeInstance._meta.get_field("range_spec")
        assert isinstance(field, JSONField)
