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

import pytest
from django.db import IntegrityError


@pytest.mark.django_db
class TestRangeInstanceModel:
    """Tests for RangeInstance model."""

    def test_model_can_be_imported(self):
        """RangeInstance model can be imported from cms.models."""
        from cms.models import RangeInstance

        assert RangeInstance is not None

    def test_can_create_range_instance(self, db):
        """RangeInstance can be created with required fields."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=1,
        )
        assert ri.id is not None
        assert ri.range_id == 1
        assert ri.scenario_id == "basic"
        assert ri.user_id == 1

    def test_range_id_is_integer_not_fk(self, db):
        """range_id is an IntegerField, not a ForeignKey."""
        from cms.models import RangeInstance

        # Should accept any integer, even if no Range with that ID exists
        ri = RangeInstance.objects.create(
            range_id=99999,
            scenario_id="basic",
            user_id=1,
        )
        assert ri.range_id == 99999

    def test_user_id_is_integer_not_fk(self, db):
        """user_id is an IntegerField, not a ForeignKey."""
        from cms.models import RangeInstance

        # Should accept any integer, even if no User with that ID exists
        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=99999,
        )
        assert ri.user_id == 99999

    def test_agent_is_optional(self, db):
        """agent FK can be None (for scenarios that don't require agent)."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=1,
            agent=None,
        )
        assert ri.agent is None

    def test_scenario_id_stores_template_name(self, db):
        """scenario_id stores the template name (not the full config)."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="ad_attack_lab",
            user_id=1,
        )
        assert ri.scenario_id == "ad_attack_lab"

    def test_scenario_id_max_length(self, db):
        """scenario_id has reasonable max_length (50 chars)."""
        from cms.models import RangeInstance

        long_id = "a" * 50
        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id=long_id,
            user_id=1,
        )
        assert ri.scenario_id == long_id

    def test_created_at_auto_set(self, db):
        """created_at is auto-set on creation."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=1,
        )
        assert ri.created_at is not None

    def test_range_id_required(self, db):
        """RangeInstance requires a range_id."""
        from cms.models import RangeInstance

        with pytest.raises(IntegrityError):
            RangeInstance.objects.create(
                range_id=None,
                scenario_id="basic",
                user_id=1,
            )

    def test_scenario_id_required(self, db):
        """RangeInstance requires a scenario_id."""
        from cms.models import RangeInstance

        with pytest.raises(IntegrityError):
            RangeInstance.objects.create(
                range_id=1,
                scenario_id=None,
                user_id=1,
            )

    def test_user_id_required(self, db):
        """RangeInstance requires a user_id."""
        from cms.models import RangeInstance

        with pytest.raises(IntegrityError):
            RangeInstance.objects.create(
                range_id=1,
                scenario_id="basic",
                user_id=None,
            )

    def test_str_representation(self, db):
        """RangeInstance has meaningful string representation."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=123,
            scenario_id="basic",
            user_id=1,
        )
        str_repr = str(ri)
        # Should contain scenario_id or range_id
        assert "basic" in str_repr or "123" in str_repr

    def test_can_query_by_range_id(self, db):
        """RangeInstance can be queried by range_id."""
        from cms.models import RangeInstance

        RangeInstance.objects.create(range_id=42, scenario_id="basic", user_id=1)

        result = RangeInstance.objects.filter(range_id=42)
        assert result.count() == 1

    def test_can_query_by_scenario_id(self, db):
        """RangeInstance can be queried by scenario_id."""
        from cms.models import RangeInstance

        RangeInstance.objects.create(range_id=1, scenario_id="ad_attack_lab", user_id=1)

        result = RangeInstance.objects.filter(scenario_id="ad_attack_lab")
        assert result.count() == 1

    def test_can_query_by_user_id(self, db):
        """RangeInstance can be queried by user_id."""
        from cms.models import RangeInstance

        RangeInstance.objects.create(range_id=1, scenario_id="basic", user_id=99)

        result = RangeInstance.objects.filter(user_id=99)
        assert result.count() == 1

    def test_unique_range_id(self, db):
        """Each range_id should be unique (one RangeInstance per Range)."""
        from cms.models import RangeInstance

        RangeInstance.objects.create(range_id=1, scenario_id="basic", user_id=1)

        with pytest.raises(IntegrityError):
            RangeInstance.objects.create(range_id=1, scenario_id="basic", user_id=1)


@pytest.mark.django_db
class TestRangeInstanceAgentFK:
    """Tests for RangeInstance.agent ForeignKey to AgentConfig.

    GH Issue #446: agent_id IntegerField converted to agent FK to AgentConfig.
    AgentConfig uses soft delete (deleted_at), so FK uses SET_NULL for edge cases.
    """

    def test_agent_is_fk_to_agent_config(self, db):
        """RangeInstance.agent is a ForeignKey to AgentConfig."""
        from django.db.models import ForeignKey

        from cms.models import AgentConfig, RangeInstance

        agent_field = RangeInstance._meta.get_field("agent")
        assert isinstance(agent_field, ForeignKey)
        assert agent_field.related_model == AgentConfig

    def test_agent_fk_is_nullable(self, db):
        """RangeInstance.agent can be None (for scenarios without agents)."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=100,
            scenario_id="basic",
            user_id=1,
            agent=None,
        )
        assert ri.agent is None

    def test_agent_fk_can_be_set(self, db):
        """RangeInstance.agent can be set to an AgentConfig instance."""
        from django.contrib.auth import get_user_model

        from cms.models import AgentConfig, OperatingSystem, RangeInstance

        User = get_user_model()
        user = User.objects.create_user(username="test@example.com", password="test")
        os = OperatingSystem.objects.create(name="Linux", slug="linux", extensions="deb")
        agent = AgentConfig.objects.create(
            name="Test Agent",
            user=user,
            os=os,
            s3_key="agents/test/agent.deb",
            original_filename="agent.deb",
            file_size_bytes=1024,
            sha256_hash="a" * 64,
        )

        ri = RangeInstance.objects.create(
            range_id=101,
            scenario_id="basic",
            user_id=user.id,
            agent=agent,
        )
        assert ri.agent == agent
        assert ri.agent.id == agent.id

    def test_agent_fk_on_delete_is_set_null(self, db):
        """FK uses SET_NULL (not CASCADE) - RangeInstance preserved if agent hard-deleted."""
        from django.db.models import SET_NULL

        from cms.models import RangeInstance

        agent_field = RangeInstance._meta.get_field("agent")
        # Verify on_delete is SET_NULL (preserves history if admin hard-deletes)
        assert agent_field.remote_field.on_delete == SET_NULL

    def test_agent_fk_works_with_soft_deleted_agent(self, db):
        """RangeInstance.agent FK still works when agent is soft-deleted."""
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from cms.models import AgentConfig, OperatingSystem, RangeInstance

        User = get_user_model()
        user = User.objects.create_user(username="soft@example.com", password="test")
        os, _ = OperatingSystem.objects.get_or_create(
            slug="windows-soft-test",
            defaults={"name": "Windows Soft Test", "extensions": "msi"},
        )
        agent = AgentConfig.objects.create(
            name="Soft Delete Agent",
            user=user,
            os=os,
            s3_key="agents/test/agent-soft.msi",
            original_filename="agent-soft.msi",
            file_size_bytes=2048,
            sha256_hash="b" * 64,
        )

        ri = RangeInstance.objects.create(
            range_id=102,
            scenario_id="basic",
            user_id=user.id,
            agent=agent,
        )

        # Soft delete the agent (set deleted_at)
        agent.deleted_at = timezone.now()
        agent.save()

        # FK still works - RangeInstance still references the soft-deleted agent
        ri.refresh_from_db()
        assert ri.agent == agent
        assert ri.agent.is_deleted is True

    def test_agent_fk_related_name(self, db):
        """AgentConfig can access its RangeInstances via related_name."""
        from django.contrib.auth import get_user_model

        from cms.models import AgentConfig, OperatingSystem, RangeInstance

        User = get_user_model()
        user = User.objects.create_user(username="related@example.com", password="test")
        os = OperatingSystem.objects.create(name="Kali", slug="kali", extensions="deb")
        agent = AgentConfig.objects.create(
            name="Related Test Agent",
            user=user,
            os=os,
            s3_key="agents/test/agent2.deb",
            original_filename="agent2.deb",
            file_size_bytes=1024,
            sha256_hash="c" * 64,
        )

        ri1 = RangeInstance.objects.create(
            range_id=103,
            scenario_id="basic",
            user_id=user.id,
            agent=agent,
        )
        ri2 = RangeInstance.objects.create(
            range_id=104,
            scenario_id="ad_attack_lab",
            user_id=user.id,
            agent=agent,
        )

        # Access RangeInstances via related_name
        related_instances = agent.range_instances.all()
        assert related_instances.count() == 2
        assert ri1 in related_instances
        assert ri2 in related_instances

    def test_agent_fk_select_related(self, db):
        """RangeInstance.agent can be efficiently loaded with select_related."""
        from django.contrib.auth import get_user_model

        from cms.models import AgentConfig, OperatingSystem, RangeInstance

        User = get_user_model()
        user = User.objects.create_user(username="select@example.com", password="test")
        os = OperatingSystem.objects.create(name="Ubuntu", slug="ubuntu", extensions="deb")
        agent = AgentConfig.objects.create(
            name="Select Related Agent",
            user=user,
            os=os,
            s3_key="agents/test/agent3.deb",
            original_filename="agent3.deb",
            file_size_bytes=1024,
            sha256_hash="d" * 64,
        )

        RangeInstance.objects.create(
            range_id=105,
            scenario_id="basic",
            user_id=user.id,
            agent=agent,
        )

        # Should be able to use select_related to load agent efficiently
        ri = RangeInstance.objects.select_related("agent").get(range_id=105)
        assert ri.agent.name == "Select Related Agent"
