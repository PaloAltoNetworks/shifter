"""Tests for scenario hydrator.

The hydrator takes a scenario template + agent info and produces
a fully resolved RangeSpec for Engine consumption.

Also tests NGFW hydration which extracts credential data for Engine.

Responsibilities:
- Resolve os_type "from_agent" to actual OS
- Embed agent details into instances with agent_slot
- Return consistent RangeSpec structure
- Extract NGFW credential data into InstanceSpec with nested NGFWAppSpec
- Input validation and error handling
"""

import pytest
from django.contrib.auth import get_user_model

from cms.models import NGFW, AgentConfig, Credential, CredentialType, OperatingSystem
from shared.schemas import RangeSpec

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com",
        email="test@example.com",
    )


@pytest.fixture
def windows_agent(user, db):
    """Windows agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Windows Agent",
        os=os,
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        file_size_bytes=5000000,
        sha256_hash="abc123def456",
    )


@pytest.fixture
def linux_agent(user, db):
    """Linux agent for testing."""
    os = OperatingSystem.objects.get(slug="linux-debian")
    return AgentConfig.objects.create(
        user=user,
        name="Linux Agent",
        os=os,
        s3_key="agents/456/agent.deb",
        original_filename="cortex_agent.deb",
        file_size_bytes=3000000,
        sha256_hash="def789ghi012",
    )


@pytest.mark.django_db
class TestHydrateScenario:
    """Tests for hydrate_scenario() function."""

    # --- Basic structure ---

    def test_returns_range_request(self, user, windows_agent):
        """hydrate_scenario returns a RangeSpec."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result, RangeSpec)

    def test_includes_scenario_id(self, user, windows_agent):
        """Result includes scenario_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.scenario_id == "basic"

    def test_includes_user_id(self, user, windows_agent):
        """Result includes user_id."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert result.user_id == user.id

    def test_includes_instances_list(self, user, windows_agent):
        """Result includes instances list."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert isinstance(result.instances, list)

    def test_basic_has_two_instances(self, user, windows_agent):
        """Basic scenario has attacker and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        assert len(result.instances) == 2
        roles = [i.role for i in result.instances]
        assert "attacker" in roles
        assert "victim" in roles

    def test_each_instance_has_uuid(self, user, windows_agent):
        """Each instance gets a unique UUID."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        uuids = [i.uuid for i in result.instances]
        assert all(uuid is not None for uuid in uuids)
        assert len(set(uuids)) == len(uuids)  # All unique

    def test_uuid_is_valid_format(self, user, windows_agent):
        """Instance UUIDs are valid UUID4 format."""
        import uuid

        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        for instance in result.instances:
            # Will raise ValueError if not valid UUID
            parsed = uuid.UUID(instance.uuid)
            assert parsed.version == 4

    # --- OS resolution from agent ---

    def test_resolves_from_agent_to_windows(self, user, windows_agent):
        """os_type 'from_agent' resolves to 'windows' for Windows agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.os_type == "windows"

    def test_resolves_from_agent_to_ubuntu(self, user, linux_agent):
        """os_type 'from_agent' resolves to 'ubuntu' for Linux agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, linux_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.os_type == "ubuntu"

    def test_attacker_remains_kali(self, user, windows_agent):
        """Attacker os_type remains 'kali' (not resolved from agent)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.instances if i.role == "attacker")
        assert attacker.os_type == "kali"

    # --- Agent embedding ---

    def test_embeds_agent_in_victim(self, user, windows_agent):
        """Agent details are embedded in victim instance."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent is not None

    def test_agent_has_s3_key(self, user, windows_agent):
        """Embedded agent has s3_key."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.s3_key == "agents/123/agent.msi"

    def test_agent_has_filename(self, user, windows_agent):
        """Embedded agent has filename."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.filename == "cortex_agent.msi"

    def test_agent_has_sha256(self, user, windows_agent):
        """Embedded agent has sha256."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent.sha256 == "abc123def456"

    def test_attacker_has_no_agent(self, user, windows_agent):
        """Attacker instance has no agent (no agent_slot)."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        attacker = next(i for i in result.instances if i.role == "attacker")
        assert attacker.agent is None

    # --- AD Attack Lab scenario ---

    def test_ad_attack_lab_has_three_instances(self, user, windows_agent):
        """AD attack lab has attacker, dc, and victim instances."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        assert len(result.instances) == 3
        roles = [i.role for i in result.instances]
        assert "attacker" in roles
        assert "dc" in roles
        assert "victim" in roles

    def test_ad_attack_lab_dc_has_dc_config(self, user, windows_agent):
        """DC instance has dc_config with domain settings."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.instances if i.role == "dc")
        assert dc.dc_config is not None
        assert dc.dc_config.domain_name is not None
        assert dc.dc_config.netbios_name is not None

    def test_ad_attack_lab_victim_joins_domain(self, user, windows_agent):
        """AD victim has join_domain flag."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.join_domain is True

    def test_ad_attack_lab_victim_has_agent(self, user, windows_agent):
        """AD victim has embedded agent."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        victim = next(i for i in result.instances if i.role == "victim")
        assert victim.agent is not None
        assert victim.agent.s3_key == "agents/123/agent.msi"

    def test_ad_attack_lab_dc_has_agent(self, user, windows_agent):
        """DC instance has agent for XDR monitoring."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("ad_attack_lab", user.id, windows_agent)
        dc = next(i for i in result.instances if i.role == "dc")
        assert dc.agent is not None
        assert dc.agent.s3_key == "agents/123/agent.msi"

    # --- Error handling ---

    def test_raises_for_unknown_scenario(self, user, windows_agent):
        """Raises CMSError for unknown scenario_id."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match="not found"):
            hydrate_scenario("nonexistent", user.id, windows_agent)

    def test_raises_when_agent_is_none(self, user):
        """Raises CMSError when agent is None."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_scenario

        with pytest.raises(CMSError, match=r"agent.*required"):
            hydrate_scenario("basic", user.id, None)

    # --- Model serialization ---

    def test_model_dump_returns_dict(self, user, windows_agent):
        """RangeSpec can be serialized to dict."""
        from cms.scenarios.hydrator import hydrate_scenario

        result = hydrate_scenario("basic", user.id, windows_agent)
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["scenario_id"] == "basic"
        assert dumped["user_id"] == user.id


@pytest.mark.django_db
class TestHydrateScenarioLogging:
    """Tests for hydrator logging behavior."""

    def test_logs_debug_on_success(self, user, windows_agent, caplog):
        """Logs debug on successful hydration."""
        import logging

        from cms.scenarios.hydrator import hydrate_scenario

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_scenario("basic", user.id, windows_agent)

        assert "basic" in caplog.text or "hydrat" in caplog.text.lower()

    def test_does_not_log_agent_secrets(self, user, windows_agent, caplog):
        """Does not log agent s3_key or sha256 (could be sensitive)."""
        import logging

        from cms.scenarios.hydrator import hydrate_scenario

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_scenario("basic", user.id, windows_agent)

        # s3_key and sha256 should not appear in logs
        assert "agents/123/agent.msi" not in caplog.text
        assert "abc123def456" not in caplog.text


# =============================================================================
# NGFW Hydration Tests
# =============================================================================


@pytest.fixture
def deployment_profile_type(db):
    """Create deployment profile credential type."""
    return CredentialType.objects.create(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_class="shared.schemas.DeploymentProfileSpec",
    )


@pytest.fixture
def scm_credential_type(db):
    """Create SCM credential type."""
    return CredentialType.objects.create(
        name="SCM Credential",
        slug="scm",
        spec_class="shared.schemas.SCMCredentialSpec",
    )


@pytest.fixture
def deployment_profile(user, deployment_profile_type, db):
    """Create a deployment profile credential for testing."""
    return Credential.objects.create(
        user=user,
        name="Test Deployment Profile",
        credential_type=deployment_profile_type,
        data={"authcode": "D1234567"},
    )


@pytest.fixture
def scm_credential(user, scm_credential_type, db):
    """Create an SCM credential for testing."""
    return Credential.objects.create(
        user=user,
        name="Test SCM Credential",
        credential_type=scm_credential_type,
        data={
            "scm_folder_name": "test-folder",
            "scm_pin_id": "pin-123",
            "scm_pin_value": "secret-pin-value",
            "sls_region": "americas",
        },
    )


@pytest.fixture
def ngfw(user, db):
    """Create an NGFW for testing."""
    from shared.enums import InstanceStatus

    return NGFW.objects.create(
        user=user,
        name="Test NGFW",
        status=InstanceStatus.PROVISIONING.value,
    )


@pytest.mark.django_db
class TestHydrateNgfw:
    """Tests for hydrate_ngfw() function.

    hydrate_ngfw extracts credential data from Credential models
    and packages into an InstanceSpec with nested NGFWAppSpec for Engine.
    """

    # --- PIN registration happy path ---

    def test_returns_instance_spec_for_pin(
        self, ngfw, deployment_profile, scm_credential
    ):
        """hydrate_ngfw returns InstanceSpec with nested NGFWAppSpec for PIN registration."""
        from cms.scenarios.hydrator import hydrate_ngfw
        from shared.schemas import InstanceSpec

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="pin",
            scm_credential=scm_credential,
        )

        assert isinstance(result, InstanceSpec)
        assert result.role == "ngfw"
        assert result.ngfw_app is not None
        assert result.ngfw_app.ngfw_id == ngfw.id
        assert result.ngfw_app.user_id == ngfw.user_id
        assert result.ngfw_app.name == "Test NGFW"
        assert result.ngfw_app.registration_method == "pin"

    def test_extracts_authcode_from_deployment_profile(
        self, ngfw, deployment_profile, scm_credential
    ):
        """authcode is extracted from deployment_profile.data."""
        from cms.scenarios.hydrator import hydrate_ngfw

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="pin",
            scm_credential=scm_credential,
        )

        assert result.ngfw_app.authcode == "D1234567"

    def test_extracts_scm_fields_for_pin(
        self, ngfw, deployment_profile, scm_credential
    ):
        """SCM fields are extracted from scm_credential.data."""
        from cms.scenarios.hydrator import hydrate_ngfw

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="pin",
            scm_credential=scm_credential,
        )

        assert result.ngfw_app.scm_folder_name == "test-folder"
        assert result.ngfw_app.scm_pin_id == "pin-123"
        assert result.ngfw_app.scm_pin_value == "secret-pin-value"
        assert result.ngfw_app.sls_region == "americas"

    def test_otp_fields_are_none_for_pin(
        self, ngfw, deployment_profile, scm_credential
    ):
        """OTP fields are None when using PIN registration."""
        from cms.scenarios.hydrator import hydrate_ngfw

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="pin",
            scm_credential=scm_credential,
        )

        assert result.ngfw_app.otp_value is None
        assert result.ngfw_app.otp_folder is None

    # --- OTP registration happy path ---

    def test_returns_instance_spec_for_otp(self, ngfw, deployment_profile):
        """hydrate_ngfw returns InstanceSpec for OTP registration."""
        from cms.scenarios.hydrator import hydrate_ngfw
        from shared.schemas import InstanceSpec

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="otp",
            otp_value="OTP123456",
            otp_folder="my-otp-folder",
        )

        assert isinstance(result, InstanceSpec)
        assert result.ngfw_app.ngfw_id == ngfw.id
        assert result.ngfw_app.registration_method == "otp"

    def test_extracts_otp_fields(self, ngfw, deployment_profile):
        """OTP fields are extracted from parameters."""
        from cms.scenarios.hydrator import hydrate_ngfw

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="otp",
            otp_value="OTP123456",
            otp_folder="my-otp-folder",
        )

        assert result.ngfw_app.otp_value == "OTP123456"
        assert result.ngfw_app.otp_folder == "my-otp-folder"

    def test_scm_fields_are_none_for_otp(self, ngfw, deployment_profile):
        """SCM fields are None when using OTP registration."""
        from cms.scenarios.hydrator import hydrate_ngfw

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="otp",
            otp_value="OTP123456",
            otp_folder="my-otp-folder",
        )

        assert result.ngfw_app.scm_folder_name is None
        assert result.ngfw_app.scm_pin_id is None
        assert result.ngfw_app.scm_pin_value is None
        assert result.ngfw_app.sls_region is None

    # --- Error handling ---

    def test_raises_when_authcode_missing(self, ngfw, deployment_profile_type, user):
        """Raises CMSError when deployment profile is missing authcode."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_ngfw

        # Create profile without authcode
        bad_profile = Credential.objects.create(
            user=user,
            name="Bad Profile",
            credential_type=deployment_profile_type,
            data={},  # No authcode
        )

        with pytest.raises(CMSError, match="authcode"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=bad_profile,
                registration_method="otp",
                otp_value="OTP123",
                otp_folder="folder",
            )

    def test_raises_when_scm_credential_missing_for_pin(self, ngfw, deployment_profile):
        """Raises CMSError when PIN registration lacks SCM credential."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_ngfw

        with pytest.raises(CMSError, match="SCM credential required"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="pin",
                scm_credential=None,  # Missing!
            )

    def test_raises_when_scm_fields_missing(
        self, ngfw, deployment_profile, scm_credential_type, user
    ):
        """Raises CMSError when SCM credential is missing required fields."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_ngfw

        # Create SCM credential missing some fields
        bad_scm = Credential.objects.create(
            user=user,
            name="Bad SCM",
            credential_type=scm_credential_type,
            data={"scm_folder_name": "folder"},  # Missing pin_id and pin_value
        )

        with pytest.raises(CMSError, match="missing required fields"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="pin",
                scm_credential=bad_scm,
            )

    def test_raises_when_otp_value_missing(self, ngfw, deployment_profile):
        """Raises CMSError when OTP registration lacks otp_value."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_ngfw

        with pytest.raises(CMSError, match="OTP value and folder required"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="otp",
                otp_value=None,  # Missing!
                otp_folder="folder",
            )

    def test_raises_when_otp_folder_missing(self, ngfw, deployment_profile):
        """Raises CMSError when OTP registration lacks otp_folder."""
        from cms.exceptions import CMSError
        from cms.scenarios.hydrator import hydrate_ngfw

        with pytest.raises(CMSError, match="OTP value and folder required"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="otp",
                otp_value="OTP123",
                otp_folder=None,  # Missing!
            )

    # --- Optional fields ---

    def test_sls_region_is_optional(
        self, ngfw, deployment_profile, scm_credential_type, user
    ):
        """sls_region is optional in SCM credential."""
        from cms.scenarios.hydrator import hydrate_ngfw

        # Create SCM credential without sls_region
        scm_no_region = Credential.objects.create(
            user=user,
            name="SCM No Region",
            credential_type=scm_credential_type,
            data={
                "scm_folder_name": "folder",
                "scm_pin_id": "pin-id",
                "scm_pin_value": "pin-value",
                # No sls_region
            },
        )

        result = hydrate_ngfw(
            ngfw=ngfw,
            deployment_profile=deployment_profile,
            registration_method="pin",
            scm_credential=scm_no_region,
        )

        assert result.ngfw_app.sls_region is None


@pytest.mark.django_db
class TestHydrateNgfwLogging:
    """Tests for hydrate_ngfw logging behavior."""

    def test_logs_debug_on_success(
        self, ngfw, deployment_profile, scm_credential, caplog
    ):
        """Logs debug on successful hydration."""
        import logging

        from cms.scenarios.hydrator import hydrate_ngfw

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="pin",
                scm_credential=scm_credential,
            )

        assert str(ngfw.id) in caplog.text or "hydrate_ngfw" in caplog.text

    def test_does_not_log_secrets(
        self, ngfw, deployment_profile, scm_credential, caplog
    ):
        """Does not log authcode or PIN values."""
        import logging

        from cms.scenarios.hydrator import hydrate_ngfw

        with caplog.at_level(logging.DEBUG, logger="cms.scenarios.hydrator"):
            hydrate_ngfw(
                ngfw=ngfw,
                deployment_profile=deployment_profile,
                registration_method="pin",
                scm_credential=scm_credential,
            )

        # Secrets should not appear in logs
        assert "D1234567" not in caplog.text  # authcode
        assert "secret-pin-value" not in caplog.text  # PIN value
