"""DRF serializers for Scenario Editor API."""

from rest_framework import serializers


class DCConfigSerializer(serializers.Serializer):
    """Serializer for domain controller configuration."""

    domain_name = serializers.CharField(max_length=255)
    netbios_name = serializers.CharField(max_length=15)


class InstanceConfigSerializer(serializers.Serializer):
    """Serializer for a single instance in a scenario definition."""

    name = serializers.CharField(max_length=100)
    role = serializers.ChoiceField(choices=["attacker", "victim", "dc", "ngfw"])
    os_type = serializers.ChoiceField(
        choices=["kali", "ubuntu", "windows", "from_agent", "panos"]
    )
    xdr_agent = serializers.BooleanField(default=False)
    domain_controller = serializers.BooleanField(default=False)
    join_domain = serializers.BooleanField(default=False)
    dc_config = DCConfigSerializer(required=False, allow_null=True, default=None)


class SubnetConfigSerializer(serializers.Serializer):
    """Serializer for a subnet definition in a scenario."""

    name = serializers.CharField(max_length=100)
    instances = serializers.ListField(
        child=serializers.CharField(max_length=100),
        min_length=1,
    )
    connected_to = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )


class ScenarioDefinitionSerializer(serializers.Serializer):
    """Serializer for the structural part of a scenario definition.

    This validates the 'definition' field of a Scenario model,
    which contains instances, subnets, and the ngfw flag.
    """

    instances = InstanceConfigSerializer(many=True, min_length=1)
    subnets = SubnetConfigSerializer(many=True, required=False, default=list)
    ngfw = serializers.BooleanField(default=False)


class ScenarioCreateSerializer(serializers.Serializer):
    """Serializer for creating a new custom scenario."""

    scenario_id = serializers.SlugField(
        max_length=100,
        help_text="URL-safe unique identifier (e.g., 'my-custom-lab')",
    )
    name = serializers.CharField(max_length=200)
    description = serializers.CharField()
    definition = ScenarioDefinitionSerializer()


class ScenarioUpdateSerializer(serializers.Serializer):
    """Serializer for updating an existing custom scenario.

    All fields are optional - only provided fields are updated.
    """

    name = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False)
    definition = ScenarioDefinitionSerializer(required=False)


class ScenarioMetadataSerializer(serializers.Serializer):
    """Serializer for updating scenario metadata (enabled, staff_only)."""

    enabled = serializers.BooleanField(required=False)
    staff_only = serializers.BooleanField(required=False)

    def validate(self, data):
        if not data:
            raise serializers.ValidationError(
                "At least one of 'enabled' or 'staff_only' must be provided"
            )
        return data


class ScenarioListSerializer(serializers.Serializer):
    """Serializer for scenario list responses."""

    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    enabled = serializers.BooleanField()
    ngfw = serializers.BooleanField()
    staff_only = serializers.BooleanField()
    is_default = serializers.BooleanField()
    instances = InstanceConfigSerializer(many=True)
    subnets = SubnetConfigSerializer(many=True, required=False)
    agent_requirements = serializers.DictField(required=False)


class ScenarioDetailSerializer(ScenarioListSerializer):
    """Serializer for scenario detail responses (same as list for now)."""


class ScenarioCloneSerializer(serializers.Serializer):
    """Serializer for cloning a scenario."""

    new_scenario_id = serializers.SlugField(
        max_length=100,
        help_text="URL-safe identifier for the cloned scenario",
    )
    new_name = serializers.CharField(max_length=200, required=False)


class ScenarioValidateSerializer(serializers.Serializer):
    """Serializer for scenario validation requests."""

    definition = serializers.DictField(
        help_text="Full scenario definition to validate (id, name, description, instances, ...)"
    )


class ScenarioYAMLSerializer(serializers.Serializer):
    """Serializer for YAML-based scenario operations."""

    yaml_content = serializers.CharField(
        help_text="Raw YAML content defining the scenario"
    )


class ScenarioMetadataResponseSerializer(serializers.Serializer):
    """Serializer for metadata update responses."""

    scenario_id = serializers.CharField()
    enabled = serializers.BooleanField()
    staff_only = serializers.BooleanField()
    updated_at = serializers.DateTimeField()
