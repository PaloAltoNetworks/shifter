# NGFW SCM Integration Plan

Complete plan for migrating NGFW provisioning to Strata Cloud Manager (SCM) with Shifter Engine architecture.

## Overview

| Component | Current State | Target State |
|-----------|--------------|--------------|
| Panorama Auth | `vm-auth-key` + server IP | SCM PIN ID + PIN value |
| Provisioning | User data only, fire-and-forget | Shifter Engine with SSHExecutor |
| Verification | None | Poll NGFW for SCM registration status |
| UI | NGFWConfig under separate nav | Assets sidebar with Agents, Strata subsections |
| Data Model | Flat AgentConfig, NGFWConfig | Asset hierarchy with FileAsset |

---

## Phase 1: Data Model Changes

### 1.1 Asset Class Hierarchy

```
Asset (abstract)
├── user, name, created_at, updated_at
│
├── FileAsset (abstract)
│   ├── s3_key
│   ├── s3_bucket (from settings, not stored)
│   ├── get_presigned_url()
│   │
│   ├── AgentConfig
│   │   └── os_type, os_version
│   │
│   └── (future: MalwareSample, CustomInstaller, etc.)
│
└── StrataConfig
    └── scm_folder_name, scm_pin_id, scm_pin_value
```

### 1.2 Base Asset Model

**File:** `portal/mission_control/models.py`

```python
class Asset(models.Model):
    """Abstract base for all range assets.

    Assets are user-owned configurations or files used during range provisioning.
    """

    class Meta:
        abstract = True

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='%(class)s_assets',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.__class__.__name__})"
```

### 1.3 FileAsset Model

**File:** `portal/mission_control/models.py`

```python
class FileAsset(Asset):
    """Abstract base for assets backed by S3 files.

    Provides common functionality for file upload, presigned URLs, etc.
    """

    class Meta:
        abstract = True

    s3_key = models.CharField(
        max_length=512,
        help_text="S3 object key (path within bucket)"
    )
    file_size = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="File size in bytes"
    )
    content_type = models.CharField(
        max_length=128,
        blank=True,
        help_text="MIME type of the file"
    )

    @property
    def s3_bucket(self) -> str:
        """Get S3 bucket from settings."""
        return settings.AGENT_S3_BUCKET

    def get_presigned_url(self, expires_in: int = 3600) -> str:
        """Generate a presigned URL for downloading this asset.

        Args:
            expires_in: URL expiration time in seconds (default 1 hour)

        Returns:
            Presigned S3 URL string
        """
        import boto3
        s3_client = boto3.client('s3')
        return s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.s3_bucket,
                'Key': self.s3_key,
            },
            ExpiresIn=expires_in,
        )

    def delete_s3_object(self) -> bool:
        """Delete the S3 object when asset is deleted.

        Returns:
            True if deletion succeeded
        """
        import boto3
        s3_client = boto3.client('s3')
        try:
            s3_client.delete_object(Bucket=self.s3_bucket, Key=self.s3_key)
            return True
        except Exception:
            return False
```

### 1.4 Refactored AgentConfig

**File:** `portal/mission_control/models.py`

```python
class AgentConfig(FileAsset):
    """XDR/XSIAM agent installer configuration.

    Stores metadata about uploaded agent installers and their S3 location.
    """

    class OsType(models.TextChoices):
        WINDOWS = 'windows', 'Windows'
        LINUX = 'linux', 'Linux'
        MACOS = 'macos', 'macOS'

    os_type = models.CharField(
        max_length=20,
        choices=OsType.choices,
        default=OsType.WINDOWS,
    )
    os_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="OS version (e.g., 'Windows Server 2022', 'Ubuntu 22.04')"
    )
    agent_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="XDR agent version if known"
    )

    class Meta:
        verbose_name = "XDR Agent"
        verbose_name_plural = "XDR Agents"
        ordering = ['-created_at']
```

### 1.5 New StrataConfig Model

**File:** `portal/mission_control/models.py`

```python
class StrataConfig(Asset):
    """Strata Cloud Manager configuration for NGFW instances.

    Stores SCM registration credentials for VM-Series bootstrap.
    Note: Inherits from Asset, not FileAsset (no file storage needed).
    """

    scm_folder_name = models.CharField(
        max_length=255,
        help_text="SCM folder name (Configuration > Folders in SCM)"
    )
    scm_pin_id = models.CharField(
        max_length=255,
        help_text="Auto-registration PIN ID (Assets > Device Certificates in SCM)"
    )
    scm_pin_value = models.CharField(
        max_length=255,
        help_text="Auto-registration PIN value"
    )

    class Meta:
        verbose_name = "Strata Config"
        verbose_name_plural = "Strata Configs"
        ordering = ['-created_at']

    def get_init_cfg_context(self) -> dict:
        """Get context dict for init-cfg.txt template rendering.

        Returns:
            Dict with pin_id, pin_value, folder_name
        """
        return {
            'pin_id': self.scm_pin_id,
            'pin_value': self.scm_pin_value,
            'folder_name': self.scm_folder_name,
        }
```

### 1.6 Update Range Model

**File:** `portal/mission_control/models.py`

```python
class Range(models.Model):
    # ... existing fields ...

    # Rename ngfw_config to strata_config
    strata_config = models.ForeignKey(
        'StrataConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ranges',
        help_text="Strata/NGFW configuration for this range"
    )

    # Keep ngfw_enabled for backward compatibility, but rename in future
    ngfw_enabled = models.BooleanField(
        default=False,
        help_text="Whether NGFW is enabled for this range"
    )
```

### 1.7 Migration Strategy

**Migration 0025: Add Asset hierarchy**

```python
# portal/mission_control/migrations/0025_asset_hierarchy.py

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('mission_control', '0024_range_dc_agent'),
    ]

    operations = [
        # 1. Add new fields to AgentConfig (from FileAsset)
        migrations.AddField(
            model_name='agentconfig',
            name='file_size',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='agentconfig',
            name='content_type',
            field=models.CharField(max_length=128, blank=True),
        ),
        migrations.AddField(
            model_name='agentconfig',
            name='description',
            field=models.TextField(blank=True),
        ),

        # 2. Create StrataConfig model
        migrations.CreateModel(
            name='StrataConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('scm_folder_name', models.CharField(max_length=255)),
                ('scm_pin_id', models.CharField(max_length=255)),
                ('scm_pin_value', models.CharField(max_length=255)),
                ('user', models.ForeignKey(
                    on_delete=models.CASCADE,
                    to=settings.AUTH_USER_MODEL,
                    related_name='strataconfig_assets',
                )),
            ],
            options={
                'verbose_name': 'Strata Config',
                'verbose_name_plural': 'Strata Configs',
                'ordering': ['-created_at'],
            },
        ),

        # 3. Add strata_config FK to Range
        migrations.AddField(
            model_name='range',
            name='strata_config',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=models.SET_NULL,
                to='mission_control.strataconfig',
                related_name='ranges',
            ),
        ),

        # 4. Migrate data from ngfw_config to strata_config (if any exists)
        # This would be a RunPython operation if there's data to migrate

        # 5. Remove old NGFWConfig model (in separate migration after verification)
    ]
```

---

## Phase 2: Pulumi Provisioner Changes

### 2.1 Update Config Pipeline

**File:** `pulumi-provisioner/config.py`

```python
@dataclass
class RangeConfig:
    # ... existing fields ...

    # Strata/NGFW fields (replacing old Panorama fields)
    ngfw_enabled: bool = False
    strata_folder_name: str = ""
    strata_pin_id: str = ""
    strata_pin_value: str = ""


def get_range_from_db(range_id: int, conn) -> dict:
    """Fetch range config from database."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            r.id,
            r.user_id,
            r.subnet_index,
            r.agent_id,
            r.instance_config,
            a.s3_key as agent_s3_key,
            a.os_type as agent_os_slug,
            r.dc_agent_id,
            da.s3_key as dc_agent_s3_key,
            r.ngfw_enabled,
            sc.scm_folder_name,
            sc.scm_pin_id,
            sc.scm_pin_value
        FROM mission_control_range r
        LEFT JOIN mission_control_agentconfig a ON r.agent_id = a.id
        LEFT JOIN mission_control_agentconfig da ON r.dc_agent_id = da.id
        LEFT JOIN mission_control_strataconfig sc ON r.strata_config_id = sc.id
        WHERE r.id = %s
    """, (range_id,))

    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Range {range_id} not found")

    return {
        "id": row[0],
        "user_id": row[1],
        "subnet_index": row[2],
        "agent_id": row[3],
        "instance_config": row[4],
        "agent_s3_key": row[5],
        "agent_os_slug": row[6],
        "dc_agent_id": row[7],
        "dc_agent_s3_key": row[8],
        "ngfw_enabled": row[9],
        "strata_folder_name": row[10] or "",
        "strata_pin_id": row[11] or "",
        "strata_pin_value": row[12] or "",
    }
```

### 2.2 Update init-cfg Template

**File:** `pulumi-provisioner/templates/ngfw_init_cfg.txt.j2`

```
type=dhcp-client
hostname={{ hostname }}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id={{ pin_id }}
vm-series-auto-registration-pin-value={{ pin_value }}
dgname={{ folder_name }}
```

### 2.3 Update NGFWComponent

**File:** `pulumi-provisioner/components/ngfw.py`

Update constructor parameters:

```python
def __init__(
    self,
    name: str,
    range_id: int,
    user_id: int,
    vpc_id: str,
    subnet_id: str,
    security_group_id: str,
    ami_id: str,
    instance_type: str,
    bootstrap_bucket: str,
    cidr_prefix: str,
    subnet_index: int,
    environment: str,
    instance_profile_name: str = "",
    # SCM parameters (replacing Panorama params)
    strata_pin_id: str = "",
    strata_pin_value: str = "",
    strata_folder_name: str = "",
    opts: Optional[pulumi.ResourceOptions] = None,
):
```

Update `_generate_init_cfg()`:

```python
def _generate_init_cfg(
    self,
    hostname: str,
    pin_id: str,
    pin_value: str,
    folder_name: str,
) -> str:
    """Generate init-cfg.txt content for SCM bootstrap."""
    templates_dir = os.environ.get(
        "TEMPLATES_DIR",
        str(Path(__file__).parent.parent / "templates"),
    )
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
    )

    template = env.get_template("ngfw_init_cfg.txt.j2")
    return template.render(
        hostname=hostname,
        pin_id=pin_id,
        pin_value=pin_value,
        folder_name=folder_name,
    )
```

### 2.4 Create SSHExecutor

**File:** `pulumi-provisioner/components/ssh_executor.py`

```python
"""SSH command executor for PAN-OS devices.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import io
import logging
import socket
import time
from dataclasses import dataclass
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


class SSHExecutorError(Exception):
    """Base exception for SSH executor errors."""
    pass


class CommandError(SSHExecutorError):
    """Raised when a command fails."""
    def __init__(self, message: str, exit_code: int = -1, stderr: str = ""):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"{message} (exit_code={exit_code})")


class TimeoutError(SSHExecutorError):
    """Raised when an operation times out."""
    pass


class ConnectionError(SSHExecutorError):
    """Raised when SSH connection fails."""
    pass


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str


class SSHExecutor:
    """SSH command executor for PAN-OS devices.

    Executes CLI commands on VM-Series via SSH.
    Same interface as SSMExecutor for orchestrator compatibility.
    """

    DEFAULT_USERNAME = "admin"
    DEFAULT_SSH_PORT = 22

    def __init__(
        self,
        private_key: str,
        username: str = DEFAULT_USERNAME,
        port: int = DEFAULT_SSH_PORT,
        poll_interval_seconds: int = 30,
    ):
        """Initialize SSH executor.

        Args:
            private_key: PEM-encoded private key string
            username: SSH username (default: admin)
            port: SSH port (default: 22)
            poll_interval_seconds: How often to poll for availability
        """
        self._private_key = private_key
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds

        # Parse the private key
        self._pkey = paramiko.RSAKey.from_private_key(
            file_obj=io.StringIO(private_key)
        )

    def run_command(
        self,
        host: str,
        script: str,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        """Run a CLI command on a PAN-OS device via SSH.

        Args:
            host: Target IP address or hostname
            script: PAN-OS CLI command to execute
            timeout_seconds: Maximum time to wait for completion

        Returns:
            CommandResult with success status, exit code, stdout, stderr

        Raises:
            CommandError: If the command fails
            TimeoutError: If the command doesn't complete in time
            ConnectionError: If SSH connection fails
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            logger.info(f"Connecting to {host}:{self._port} as {self._username}")
            client.connect(
                hostname=host,
                port=self._port,
                username=self._username,
                pkey=self._pkey,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )

            logger.info(f"Executing command: {script[:100]}...")
            stdin, stdout, stderr = client.exec_command(
                script,
                timeout=timeout_seconds,
            )

            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode('utf-8')
            stderr_text = stderr.read().decode('utf-8')

            logger.info(f"Command completed with exit code {exit_code}")

            if exit_code != 0:
                raise CommandError(
                    f"Command failed on {host}",
                    exit_code=exit_code,
                    stderr=stderr_text,
                )

            return CommandResult(
                success=True,
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )

        except paramiko.SSHException as e:
            raise ConnectionError(f"SSH connection failed to {host}: {e}")
        except socket.timeout:
            raise TimeoutError(f"SSH command timed out on {host}")
        finally:
            client.close()

    def wait_for_agent(
        self,
        host: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """Wait for SSH to become available on a PAN-OS device.

        VM-Series takes 15-25 minutes to fully boot. This method polls
        until SSH responds.

        Args:
            host: Target IP address
            timeout_seconds: Maximum time to wait (default 30 min)

        Returns:
            True if SSH is available

        Raises:
            TimeoutError: If SSH doesn't become available in time
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"SSH on {host} did not become available "
                    f"within {timeout_seconds}s"
                )

            if self._check_ssh_available(host):
                logger.info(f"SSH available on {host} after {elapsed:.1f}s")
                return True

            logger.info(
                f"Waiting for SSH on {host}... "
                f"({elapsed:.1f}s / {timeout_seconds}s)"
            )
            time.sleep(self._poll_interval)

    def _check_ssh_available(self, host: str) -> bool:
        """Check if SSH port is accepting connections and auth works."""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host,
                port=self._port,
                username=self._username,
                pkey=self._pkey,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            client.close()
            return True
        except Exception:
            return False

    def reboot_and_wait(
        self,
        host: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """Reboot PAN-OS device and wait for it to come back.

        Args:
            host: Target IP address
            timeout_seconds: Maximum time to wait for device to return

        Returns:
            True if device is back online

        Raises:
            TimeoutError: If device doesn't come back in time
        """
        logger.info(f"Rebooting {host}...")

        # Issue reboot command
        try:
            self.run_command(host, "request restart system", timeout_seconds=30)
        except (ConnectionError, CommandError, TimeoutError):
            # Connection may drop during reboot - that's expected
            logger.info("Connection dropped during reboot (expected)")

        # Wait for SSH to go down
        logger.info("Waiting for device to go offline...")
        time.sleep(60)

        # Wait for SSH to come back up
        logger.info("Waiting for device to come back online...")
        return self.wait_for_agent(host, timeout_seconds=timeout_seconds - 60)
```

### 2.5 Create NGFWVerificationPlan

**File:** `pulumi-provisioner/components/plans/ngfw_verification.py`

```python
"""NGFW verification plan for checking SCM registration.

Verifies that VM-Series has successfully registered with Strata Cloud Manager.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


class NGFWVerificationPlan:
    """Verification plan for NGFW SCM registration.

    This plan has no setup steps - the NGFW bootstraps itself via
    S3 init-cfg. We only verify that registration succeeded.

    Verification:
    - Run `show panorama-status` and check for connected status
    """

    steps: List[SetupStep] = []  # No setup steps - bootstrap is automatic

    verify_step: SetupStep = SetupStep(
        name="verify_scm_registration",
        script="show panorama-status",
        timeout_seconds=60,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables (none needed for verification).

        Args:
            instance: NGFW instance (unused)

        Returns:
            Empty dict - no template variables needed
        """
        return {}

    @staticmethod
    def parse_panorama_status(output: str) -> dict:
        """Parse output of 'show panorama-status' command.

        Expected output format (connected):
            Panorama Server 1 : cloud
                Connected     : yes
                HA state      : n/a

        Expected output format (not connected):
            Panorama Server 1 : cloud
                Connected     : no

        Args:
            output: Raw CLI output

        Returns:
            Dict with parsed status fields:
            - connected: bool
            - server: str (e.g., "cloud")
        """
        result = {
            "connected": False,
            "server": None,
        }

        for line in output.splitlines():
            line_lower = line.strip().lower()

            # Check for server line
            if "panorama server" in line_lower:
                parts = line.split(":")
                if len(parts) >= 2:
                    result["server"] = parts[1].strip()

            # Check for connected status
            if "connected" in line_lower:
                if "yes" in line_lower:
                    result["connected"] = True
                elif "no" in line_lower:
                    result["connected"] = False

        return result

    @staticmethod
    def is_registered(output: str) -> bool:
        """Check if NGFW is registered based on panorama-status output.

        Args:
            output: Raw CLI output from 'show panorama-status'

        Returns:
            True if connected to SCM/Panorama
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)
        return status["connected"]
```

### 2.6 Integrate Verification into NGFWComponent

**File:** `pulumi-provisioner/components/ngfw.py`

Add verification method:

```python
def run_verification(
    self,
    ssh_private_key: str,
    timeout_seconds: int = 1800,
) -> pulumi.Output[bool]:
    """Verify NGFW registered with SCM.

    Uses SSHExecutor to connect to NGFW and check Panorama status.

    Args:
        ssh_private_key: PEM private key for SSH auth
        timeout_seconds: Max time to wait for NGFW to be ready

    Returns:
        Output[bool] that resolves to True on success

    Raises:
        SetupError: If verification fails
    """
    from .ssh_executor import SSHExecutor
    from .setup_orchestrator import SetupOrchestrator, SetupError
    from .plans.ngfw_verification import NGFWVerificationPlan

    def do_verification(mgmt_ip: str) -> bool:
        pulumi.log.info(f"Starting NGFW verification for {mgmt_ip}")

        executor = SSHExecutor(private_key=ssh_private_key)
        orchestrator = SetupOrchestrator(executor=executor)

        # Wait for NGFW to be SSH-accessible (boot takes 15-25 min)
        pulumi.log.info(f"Waiting for NGFW {mgmt_ip} to boot (this may take 15-25 minutes)...")
        executor.wait_for_agent(mgmt_ip, timeout_seconds=timeout_seconds)
        pulumi.log.info(f"NGFW {mgmt_ip} is SSH-accessible")

        # Run verification plan
        pulumi.log.info(f"Verifying SCM registration on {mgmt_ip}...")
        plan = NGFWVerificationPlan()
        result = orchestrator.orchestrate(mgmt_ip, plan, {})

        # Check result
        if result.verification_result:
            if not NGFWVerificationPlan.is_registered(result.verification_result.stdout):
                raise SetupError(
                    f"NGFW {mgmt_ip} failed to register with SCM. "
                    f"Output: {result.verification_result.stdout}"
                )

        pulumi.log.info(f"NGFW {mgmt_ip} successfully registered with SCM")
        return True

    return self.mgmt_private_ip.apply(do_verification)
```

### 2.7 Update range_stack.py

**File:** `pulumi-provisioner/components/range_stack.py`

```python
if config.ngfw_enabled:
    # Generate SSH key for NGFW
    ngfw_ssh_key = tls.PrivateKey(
        f"{name}-ngfw-key",
        algorithm="RSA",
        rsa_bits=4096,
        opts=pulumi.ResourceOptions(parent=self),
    )

    self.ngfw = NGFWComponent(
        f"{name}-ngfw",
        range_id=config.range_id,
        user_id=config.user_id,
        vpc_id=config.vpc_id,
        subnet_id=self.network.subnet_id,
        security_group_id=config.ngfw_security_group_id,
        ami_id=config.ngfw_ami_id,
        instance_type=config.ngfw_instance_type,
        bootstrap_bucket=config.agent_s3_bucket,
        cidr_prefix=cidr_prefix,
        subnet_index=config.subnet_index,
        environment=config.environment,
        instance_profile_name=config.instance_profile_name,
        # SCM config
        strata_pin_id=config.strata_pin_id,
        strata_pin_value=config.strata_pin_value,
        strata_folder_name=config.strata_folder_name,
        ssh_private_key=ngfw_ssh_key,
        opts=pulumi.ResourceOptions(parent=self),
    )

    # Run verification - blocks until NGFW registers with SCM
    self.ngfw_verified = self.ngfw.run_verification(
        ssh_private_key=ngfw_ssh_key.private_key_pem,
        timeout_seconds=1800,  # 30 min for boot + registration
    )

    # Store NGFW outputs
    self.ngfw_outputs = self.ngfw.to_output_dict()
```

---

## Phase 3: Frontend Changes

### 3.1 Assets Sidebar Structure

**File:** `portal/templates/mission_control/partials/sidebar.html`

```html
<!-- Assets dropdown -->
<li class="nav-item">
    <a class="nav-link d-flex align-items-center justify-content-between {% if 'assets' in request.path %}active{% endif %}"
       data-bs-toggle="collapse"
       href="#assetsSubmenu"
       role="button"
       aria-expanded="{% if 'agents' in request.path or 'strata' in request.path %}true{% else %}false{% endif %}">
        <span>
            <i class="bi bi-box-seam me-2"></i>
            Assets
        </span>
        <i class="bi bi-chevron-down"></i>
    </a>
    <div class="collapse {% if 'agents' in request.path or 'strata' in request.path %}show{% endif %}"
         id="assetsSubmenu">
        <ul class="nav flex-column ms-4 mt-1">
            <li class="nav-item">
                <a class="nav-link py-1 {% if 'agents' in request.path %}active{% endif %}"
                   href="{% url 'mission_control:agents' %}">
                    <i class="bi bi-shield-check me-2"></i>
                    XDR Agents
                </a>
            </li>
            <li class="nav-item">
                <a class="nav-link py-1 {% if 'strata' in request.path %}active{% endif %}"
                   href="{% url 'mission_control:strata_configs' %}">
                    <i class="bi bi-hdd-network me-2"></i>
                    Strata (NGFW)
                </a>
            </li>
        </ul>
    </div>
</li>
```

### 3.2 Strata Config Views

**File:** `portal/mission_control/views.py`

```python
@login_required
def strata_configs(request):
    """List user's Strata configurations."""
    configs = StrataConfig.objects.filter(user=request.user)
    return render(request, 'mission_control/strata_configs.html', {
        'configs': configs,
        'page_title': 'Strata Configs',
    })


@login_required
def strata_config_create(request):
    """Create new Strata configuration."""
    if request.method == 'POST':
        form = StrataConfigForm(request.POST)
        if form.is_valid():
            config = form.save(commit=False)
            config.user = request.user
            config.save()
            messages.success(request, f'Strata config "{config.name}" created.')
            return redirect('mission_control:strata_configs')
    else:
        form = StrataConfigForm()

    return render(request, 'mission_control/strata_config_form.html', {
        'form': form,
        'page_title': 'Add Strata Config',
    })


@login_required
def strata_config_edit(request, pk):
    """Edit existing Strata configuration."""
    config = get_object_or_404(StrataConfig, pk=pk, user=request.user)

    if request.method == 'POST':
        form = StrataConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, f'Strata config "{config.name}" updated.')
            return redirect('mission_control:strata_configs')
    else:
        form = StrataConfigForm(instance=config)

    return render(request, 'mission_control/strata_config_form.html', {
        'form': form,
        'config': config,
        'page_title': f'Edit {config.name}',
    })


@login_required
def strata_config_delete(request, pk):
    """Delete Strata configuration."""
    config = get_object_or_404(StrataConfig, pk=pk, user=request.user)

    if request.method == 'POST':
        name = config.name
        config.delete()
        messages.success(request, f'Strata config "{name}" deleted.')
        return redirect('mission_control:strata_configs')

    return render(request, 'mission_control/strata_config_confirm_delete.html', {
        'config': config,
        'page_title': f'Delete {config.name}',
    })
```

### 3.3 URL Routes

**File:** `portal/mission_control/urls.py`

```python
urlpatterns = [
    # ... existing patterns ...

    # Strata configs
    path('strata/', views.strata_configs, name='strata_configs'),
    path('strata/add/', views.strata_config_create, name='strata_config_create'),
    path('strata/<int:pk>/edit/', views.strata_config_edit, name='strata_config_edit'),
    path('strata/<int:pk>/delete/', views.strata_config_delete, name='strata_config_delete'),
]
```

### 3.4 Update Dashboard Launch Flow

**File:** `portal/static/js/dashboard.js`

```javascript
// Update launch request to use strata_config
async function launchRange() {
    const agentId = document.getElementById('agentSelect').value;
    const scenario = document.getElementById('scenarioSelect').value;
    const strataEnabled = document.getElementById('strataEnabled')?.checked || false;
    const strataConfigId = document.getElementById('strataConfigSelect')?.value;

    const body = {
        agent_id: parseInt(agentId),
        scenario: scenario,
        strata_enabled: strataEnabled,
    };

    if (strataEnabled && strataConfigId) {
        body.strata_config_id = parseInt(strataConfigId);
    }

    const response = await fetch('/api/ranges/launch/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify(body),
    });

    // ... handle response
}
```

### 3.5 Update Launch View

**File:** `portal/mission_control/views.py`

```python
@login_required
@require_POST
def launch_range(request):
    """Launch a new range."""
    data = json.loads(request.body)

    agent_id = data.get('agent_id')
    scenario = data.get('scenario', 'basic')
    strata_enabled = data.get('strata_enabled', False)
    strata_config_id = data.get('strata_config_id')

    # Validate agent
    agent = get_object_or_404(AgentConfig, pk=agent_id, user=request.user)

    # Validate strata config if enabled
    strata_config = None
    if strata_enabled:
        if not strata_config_id:
            return JsonResponse({'error': 'Strata config required when NGFW enabled'}, status=400)
        strata_config = get_object_or_404(StrataConfig, pk=strata_config_id, user=request.user)

    # Create range
    range_obj = Range.objects.create(
        user=request.user,
        agent=agent,
        scenario=scenario,
        ngfw_enabled=strata_enabled,
        strata_config=strata_config,
        status='pending',
    )

    # ... trigger provisioning
```

---

## Phase 4: Testing

### 4.1 Model Tests

**File:** `portal/mission_control/tests/test_asset_models.py`

```python
class TestAssetHierarchy(TestCase):
    """Test Asset model hierarchy."""

    def test_agent_config_is_file_asset(self):
        """AgentConfig should inherit from FileAsset."""
        agent = AgentConfig(name="Test", s3_key="test/key")
        self.assertTrue(hasattr(agent, 's3_key'))
        self.assertTrue(hasattr(agent, 'get_presigned_url'))

    def test_strata_config_is_not_file_asset(self):
        """StrataConfig should inherit from Asset, not FileAsset."""
        config = StrataConfig(name="Test", scm_pin_id="123")
        self.assertFalse(hasattr(config, 's3_key'))

    def test_strata_config_init_cfg_context(self):
        """StrataConfig should provide init-cfg context."""
        config = StrataConfig(
            scm_folder_name="MyFolder",
            scm_pin_id="pin123",
            scm_pin_value="secret456",
        )
        context = config.get_init_cfg_context()
        self.assertEqual(context['folder_name'], "MyFolder")
        self.assertEqual(context['pin_id'], "pin123")
        self.assertEqual(context['pin_value'], "secret456")
```

### 4.2 SSHExecutor Tests

**File:** `pulumi-provisioner/tests/test_ssh_executor.py`

```python
class TestSSHExecutor(TestCase):
    """Test SSHExecutor with mocked paramiko."""

    @patch('paramiko.SSHClient')
    def test_run_command_success(self, mock_ssh_class):
        """Successful command execution."""
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"Connected: yes"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)
        result = executor.run_command("10.0.0.1", "show panorama-status")

        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Connected", result.stdout)
```

### 4.3 Verification Plan Tests

**File:** `pulumi-provisioner/tests/test_ngfw_verification_plan.py`

```python
class TestNGFWVerificationPlan(TestCase):
    """Test NGFW verification plan."""

    def test_parse_connected_status(self):
        """Parse successful connection output."""
        output = """
        Panorama Server 1 : cloud
            Connected     : yes
            HA state      : n/a
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)
        self.assertTrue(status['connected'])
        self.assertEqual(status['server'], 'cloud')

    def test_parse_disconnected_status(self):
        """Parse failed connection output."""
        output = """
        Panorama Server 1 : cloud
            Connected     : no
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)
        self.assertFalse(status['connected'])

    def test_is_registered(self):
        """is_registered helper method."""
        connected_output = "Connected     : yes"
        disconnected_output = "Connected     : no"

        self.assertTrue(NGFWVerificationPlan.is_registered(connected_output))
        self.assertFalse(NGFWVerificationPlan.is_registered(disconnected_output))
```

---

## Phase 5: Documentation Updates

### 5.1 Update Provisioner Docs

Add section to `portal/documentation/docs/execution/provisioner.md`:

```markdown
## NGFW/Strata Provisioning

NGFW instances use a different provisioning pattern than DC/victim instances:

| Aspect | DC/Victims | NGFW |
|--------|------------|------|
| Bootstrap | SSM Run Command | S3 init-cfg.txt |
| Executor | SSMExecutor | SSHExecutor |
| Verification | SSM command | SSH CLI |

### Why Different?

VM-Series runs PAN-OS, which doesn't support SSM agent. Configuration
happens via S3 bootstrap (init-cfg.txt read at boot), and verification
uses SSH to the management interface.

### SSHExecutor

Same interface as SSMExecutor for orchestrator compatibility:

- `run_command(host, script, timeout)` - Execute PAN-OS CLI
- `wait_for_agent(host, timeout)` - Wait for SSH availability
- `reboot_and_wait(host, timeout)` - Reboot and wait for return

### Verification Flow

1. NGFW boots and reads init-cfg.txt from S3
2. Provisioner waits for SSH to become available (~20 min)
3. Provisioner runs `show panorama-status` via SSH
4. If "Connected: yes", range is ready
5. If not connected, provisioning fails
```

---

## Implementation Order

| # | Task | Dependencies | Status |
|---|------|--------------|--------|
| 1 | Asset/FileAsset/StrataConfig models | None | ✅ DONE |
| 2 | Migration (add StrataConfig, update Range FK) | Models | ✅ DONE |
| 3 | Update config.py SQL + dataclass | Migration | ❌ TODO |
| 4 | Update init-cfg.txt.j2 template | None | ❌ TODO |
| 5 | Update NGFWComponent params | Config pipeline | ❌ TODO |
| 6 | Create SSHExecutor | None | ❌ TODO |
| 7 | Create NGFWVerificationPlan | SSHExecutor | ❌ TODO |
| 8 | Integrate verification into range_stack | Plan + NGFW component | ❌ TODO |
| 9 | Frontend: Assets sidebar | None | ❌ TODO |
| 10 | Frontend: StrataConfig CRUD views | Models | ❌ TODO |
| 11 | Frontend: Update dashboard launch | Views | ❌ TODO |
| 12 | Tests (models, executor, plan) | All above | ⏳ PARTIAL |
| 13 | Documentation updates | All above | ❌ TODO |

### Completed Work (Phase 1)

**Models implemented:**
- `Asset` abstract base class (`models.py:7-36`)
- `FileAsset` abstract class extending Asset (`models.py:39-60`)
- `AgentConfig` refactored to inherit from FileAsset (`models.py:117-146`)
- `StrataConfig` model with SCM fields (`models.py:134-213`)
- Range model updated with `strata_config` FK (`models.py:361-368`)

**Migrations created:**
- `0025_strata_config.py` - Creates StrataConfig model
- `0026_add_strata_config_to_range.py` - Adds strata_config FK, updates AgentConfig fields

**Tests written:**
- `tests/test_strata_config.py` - 23 tests for StrataConfig model
- `tests/test_asset_hierarchy.py` - 21 tests for Asset/FileAsset hierarchy
- All 367 existing tests pass

---

## Decisions (Resolved)

1. **PIN value encryption**: ✅ Yes - encrypt `scm_pin_value` at rest (real creds to expensive systems)

2. **Legacy cleanup**: ✅ Drop `NGFWConfig` model ASAP

3. **Timeout tuning**: ✅ 30 min is fine for now; tighten up once we have real-world data

4. **Retry logic**: ✅ Retry once, then fail

## Open Questions

1. **AgentConfig migration**: Backfill `file_size`, `content_type` for existing agents?
