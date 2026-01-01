"""Tests for RangeInstance model.

RangeInstance tracks hydrated scenario configs sent to engine.
Uses integer IDs only - NO ForeignKey relationships to external models.
See GH issue #446 for planned migration to use FK for agent_id.

This decoupled design allows CMS to track:
- Which scenario template was used (scenario_id)
- Which range was created (range_id - integer, not FK)
- Which user requested it (user_id - integer, not FK)
- Which agent was used (agent_id - integer, not FK, nullable)
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

    def test_agent_id_is_optional(self, db):
        """agent_id can be None (for scenarios that don't require agent)."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=1,
            agent_id=None,
        )
        assert ri.agent_id is None

    def test_agent_id_can_be_set(self, db):
        """agent_id can be set to an integer."""
        from cms.models import RangeInstance

        ri = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=1,
            agent_id=42,
        )
        assert ri.agent_id == 42

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
