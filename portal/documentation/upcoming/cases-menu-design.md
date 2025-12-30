# Cases Menu: Architectural Design

## Overview

The Cases feature introduces automated attack simulation to Shifter using Atomic Red Team (ART) as the underlying execution framework. Users select high-level attack scenarios from a curated menu; Shifter handles all orchestration automatically.

**Key Principle:** Users select *what* kind of case they want. Shifter handles *how* it executes.

---

## What is Atomic Red Team?

[Atomic Red Team](https://github.com/redcanaryco/atomic-red-team) is an open-source library of 1,700+ tests mapped to MITRE ATT&CK techniques. Each "atomic test" is a self-contained script that emulates a specific adversary behavior.

**Relevance to Shifter:**
- Pre-built attack scripts eliminate custom development
- MITRE ATT&CK mapping provides credibility for demos
- Multi-platform support (Windows, Linux) matches Shifter's range instances
- Tests designed for fast execution (under 5 minutes each)

---

## UI Design

### Sidebar Integration

The Cases menu follows the existing Assets submenu pattern in the Cortex XDR sidebar:

```
┌────────────────────────────────────────┐
│ Dashboard                              │
│ Assets             →                   │
│ Cases              →  ← New submenu    │
│ Terminal                               │
│ Docs                                   │
└────────────────────────────────────────┘
```

**Submenu Items:**
| Item | Description |
|------|-------------|
| Run Case | Launch case execution wizard |
| History | View past case executions |
| Templates | Browse available case templates (read-only) |

### Cases Icon

Use a "play circle" or "crosshairs" icon consistent with XDR iconography:

```svg
<!-- Suggested: crosshairs/target icon representing precision strikes -->
<svg width="24" height="24" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="2"/>
    <circle cx="12" cy="12" r="3" fill="currentColor"/>
    <path d="M12 2V6M12 18V22M2 12H6M18 12H22" stroke="currentColor" stroke-width="2"/>
</svg>
```

---

## Case Categories

Cases are grouped by attack scenario type. Each category maps to one or more MITRE ATT&CK tactics.

### Proposed Categories

| Category | Description | ATT&CK Tactics | Example Techniques |
|----------|-------------|----------------|-------------------|
| Initial Access | Phishing, drive-by, malicious docs | TA0001 | T1566, T1189 |
| Execution | PowerShell, command line, scripts | TA0002 | T1059, T1204 |
| Persistence | Registry run keys, scheduled tasks | TA0003 | T1547, T1053 |
| Credential Access | Mimikatz, credential dumping | TA0006 | T1003, T1558 |
| Discovery | System/network enumeration | TA0007 | T1082, T1016 |
| Lateral Movement | PsExec, WMI, RDP | TA0008 | T1021, T1570 |
| Exfiltration | Data staging and transfer | TA0010 | T1041, T1048 |
| Ransomware Sim | File encryption simulation (safe) | TA0040 | T1486 (simulated) |

### Case Templates

A **Case Template** bundles multiple atomic tests into a coherent scenario:

```yaml
# Example: credential-theft-demo.yaml
name: Credential Theft Demo
description: Demonstrates credential dumping attacks for XDR detection
category: credential_access
estimated_duration: 3-5 minutes
target_platforms:
  - windows
requires_agent: true
requires_domain: false

steps:
  - technique: T1003.001  # LSASS Memory
    atomic_test: 1
    description: Dump credentials using Mimikatz
  - technique: T1003.002  # Security Account Manager
    atomic_test: 1
    description: Extract SAM database hashes
  - technique: T1558.003  # Kerberoasting
    atomic_test: 1
    description: Extract service account tickets

cleanup: true
```

---

## Technical Architecture

### New Database Models

```
┌─────────────────────┐       ┌─────────────────────┐
│    CaseTemplate     │       │    CaseExecution    │
├─────────────────────┤       ├─────────────────────┤
│ id                  │       │ id                  │
│ name                │←──────│ template_id (FK)    │
│ slug                │       │ range_id (FK)       │
│ category            │       │ user_id (FK)        │
│ description         │       │ status              │
│ estimated_duration  │       │ started_at          │
│ target_platforms    │       │ completed_at        │
│ requires_agent      │       │ error_message       │
│ requires_domain     │       │ step_results (JSON) │
│ steps_config (JSON) │       └─────────────────────┘
│ is_active           │
│ created_at          │
│ updated_at          │
└─────────────────────┘
```

**CaseTemplate:**
- Managed by Shifter admins (not user-creatable initially)
- `steps_config` contains the YAML-like step definitions
- `is_active` allows disabling templates without deletion

**CaseExecution:**
- Tracks each run of a case template
- Links to the Range it executed on
- `step_results` captures per-step success/failure and output

### Status Values

```
pending → running → completed
                  ↘ failed
                  ↘ cancelled
```

### Service Layer

```
portal/cases/
├── __init__.py
├── models.py           # CaseTemplate, CaseExecution
├── services/
│   ├── __init__.py
│   ├── validation.py   # Prerequisite checks
│   ├── executor.py     # Orchestration logic
│   └── templates.py    # Template loading/management
├── views.py            # Run Case wizard, History
├── urls.py
└── templates/
    └── cases/
        ├── run_wizard.html
        ├── history.html
        └── templates_list.html
```

### Integration with Shifter Engine

Cases leverage the existing engine architecture:

```
Portal                          Shifter Engine
┌─────────────────┐            ┌─────────────────────────────┐
│ CaseExecutor    │            │ CaseExecutionPlan           │
│                 │───────────▶│                             │
│ - validate()    │  ECS Task  │ - download ART atomics      │
│ - execute()     │            │ - run each step via SSM     │
│ - get_status()  │            │ - capture output            │
│                 │◀───────────│ - update step_results       │
└─────────────────┘  RDS Write │                             │
                               └─────────────────────────────┘
```

**Execution Flow:**
1. User selects case template in Portal
2. Portal validates prerequisites (range active, agent installed, etc.)
3. Portal creates `CaseExecution` record (status=pending)
4. Portal triggers ECS task with `execute-case --execution-id N`
5. Engine downloads required ART atomics
6. Engine runs each step via SSM/SSH on target instance
7. Engine updates `CaseExecution` with results
8. Portal shows real-time progress (polling or WebSocket)

### New Engine Component

```python
# shifter-engine/components/plans/case_execution.py

class CaseExecutionPlan(SetupPlan):
    """Execute an Atomic Red Team case on a range instance."""

    def __init__(self, case_config: CaseConfig):
        self.case_config = case_config

    @property
    def steps(self) -> List[SetupStep]:
        steps = [
            SetupStep(
                name="download_art",
                script=self._art_download_script(),
                timeout_seconds=120
            )
        ]

        for step in self.case_config.steps:
            steps.append(SetupStep(
                name=f"execute_{step.technique}",
                script=self._atomic_execution_script(step),
                timeout_seconds=step.timeout or 300
            ))

        if self.case_config.cleanup:
            steps.append(SetupStep(
                name="cleanup",
                script=self._cleanup_script(),
                timeout_seconds=120
            ))

        return steps
```

---

## User Flow

### Run Case Wizard

```
┌─────────────────────────────────────────────────────────────────┐
│  RUN CASE                                                    X  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1: Select Category                                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │ Credential  │ │  Execution  │ │  Discovery  │  ...          │
│  │   Access    │ │             │ │             │               │
│  └─────────────┘ └─────────────┘ └─────────────┘               │
│                                                                 │
│  Step 2: Select Template                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ ○ Credential Theft Demo           [3-5 min] [Windows]    │  │
│  │   Mimikatz credential dumping for XDR detection          │  │
│  │                                                           │  │
│  │ ○ Kerberoasting Attack            [2-3 min] [Windows]    │  │
│  │   Service account ticket extraction                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Step 3: Confirm Prerequisites                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ ✓ Active range with Windows victim                       │  │
│  │ ✓ XDR agent installed on victim                          │  │
│  │ ✗ Domain Controller required (not provisioned)           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│               [ Cancel ]              [ Run Case ]              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Execution Progress View

```
┌─────────────────────────────────────────────────────────────────┐
│  CASE EXECUTION: Credential Theft Demo                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Range: My XDR Demo Range                                       │
│  Started: 2 minutes ago                                         │
│                                                                 │
│  Progress:                                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ ✓ Download ART framework                    [0:12]       │  │
│  │ ✓ T1003.001 - LSASS Memory Dump             [0:45]       │  │
│  │ ● T1003.002 - SAM Database Extract          [running]    │  │
│  │ ○ T1558.003 - Kerberoasting                 [pending]    │  │
│  │ ○ Cleanup                                   [pending]    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [ View in XSIAM ]                    [ Cancel Execution ]      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites Validation

Before case execution, the system validates:

| Prerequisite | Check | Error Message |
|--------------|-------|---------------|
| Active range | `Range.status == 'ready'` | No active range. Launch a range first. |
| Correct platform | Template platform matches victim OS | This case requires Windows. Your victim runs Linux. |
| Agent installed | `Range.agent` is not null | XDR agent required. Configure an agent before running cases. |
| Domain (if needed) | Template `requires_domain` vs `Range.scenario` | This case requires Active Directory. Launch an AD Attack Lab range. |
| No concurrent case | No `CaseExecution` with `status=running` for this range | A case is already running on this range. |

---

## ART Integration Details

### Atomic Test Structure

Each ART atomic test is defined in YAML:

```yaml
attack_technique: T1003.001
display_name: "OS Credential Dumping: LSASS Memory"
atomic_tests:
  - name: Dump LSASS with Mimikatz
    auto_generated_guid: abc123
    description: Uses Mimikatz to dump LSASS memory
    supported_platforms:
      - windows
    input_arguments:
      output_file:
        description: Path for dump file
        type: path
        default: C:\Windows\Temp\lsass.dmp
    executor:
      command: |
        mimikatz.exe "sekurlsa::logonpasswords" "exit"
      name: command_prompt
      elevation_required: true
    cleanup_command: |
      del /f #{output_file}
```

### Execution Strategy

**Option A: Bundle ART in Range AMI (Recommended)**
- Pre-install Invoke-Atomic PowerShell module in Windows AMI
- Pre-clone atomics to `/opt/atomic-red-team` in Linux AMI
- Faster execution, no download delay

**Option B: Download at Runtime**
- Engine downloads required techniques on demand
- Slower but always up-to-date
- Requires internet access from range

### Invoke-Atomic Integration

Use [Invoke-AtomicRedTeam](https://github.com/redcanaryco/invoke-atomicredteam) for Windows execution:

```powershell
# Install (pre-baked in AMI)
Install-Module -Name invoke-atomicredteam -Force

# Execute a specific test
Invoke-AtomicTest T1003.001 -TestNumbers 1 -GetPrereqs
Invoke-AtomicTest T1003.001 -TestNumbers 1

# Cleanup
Invoke-AtomicTest T1003.001 -TestNumbers 1 -Cleanup
```

---

## Implementation Phases

### Phase 1: Foundation
- Add Cases submenu to sidebar (UI only)
- Create `CaseTemplate` and `CaseExecution` models
- Build template browser view (read-only)
- Seed 5-10 curated templates

### Phase 2: Execution
- Implement `CaseExecutionPlan` in Shifter Engine
- Build Run Case wizard with validation
- Add execution progress view with polling
- Store and display step results

### Phase 3: Enhancement
- Real-time progress via WebSocket
- Execution history with filtering
- Template categories and search
- Custom input arguments for advanced users

---

## Security Considerations

1. **No user-uploaded tests:** Only admin-curated templates execute
2. **Range isolation:** Cases run only on user's own range instances
3. **Audit logging:** All case executions logged in ActivityLog
4. **Cleanup mandatory:** All templates must include cleanup steps
5. **No persistence:** Attacks don't persist across range restarts

---

## Database Migration

```python
# portal/cases/migrations/0001_initial.py

class Migration(migrations.Migration):
    operations = [
        migrations.CreateModel(
            name='CaseTemplate',
            fields=[
                ('id', models.BigAutoField(primary_key=True)),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(unique=True)),
                ('category', models.CharField(max_length=50, choices=[
                    ('initial_access', 'Initial Access'),
                    ('execution', 'Execution'),
                    ('persistence', 'Persistence'),
                    ('credential_access', 'Credential Access'),
                    ('discovery', 'Discovery'),
                    ('lateral_movement', 'Lateral Movement'),
                    ('exfiltration', 'Exfiltration'),
                    ('ransomware_sim', 'Ransomware Simulation'),
                ])),
                ('description', models.TextField()),
                ('estimated_duration', models.CharField(max_length=20)),
                ('target_platforms', models.JSONField()),
                ('requires_agent', models.BooleanField(default=True)),
                ('requires_domain', models.BooleanField(default=False)),
                ('steps_config', models.JSONField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='CaseExecution',
            fields=[
                ('id', models.BigAutoField(primary_key=True)),
                ('template', models.ForeignKey('CaseTemplate', on_delete=models.PROTECT)),
                ('range', models.ForeignKey('mission_control.Range', on_delete=models.CASCADE)),
                ('user', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)),
                ('status', models.CharField(max_length=20, choices=[
                    ('pending', 'Pending'),
                    ('running', 'Running'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('cancelled', 'Cancelled'),
                ], default='pending')),
                ('started_at', models.DateTimeField(null=True)),
                ('completed_at', models.DateTimeField(null=True)),
                ('error_message', models.TextField(blank=True)),
                ('step_results', models.JSONField(default=dict)),
            ],
        ),
    ]
```

---

## Open Questions

1. **Template sourcing:** Should templates be stored in database or as YAML files in repo?
2. **Cross-range execution:** Should cases support running from Kali against victim, or only on victim directly?
3. **Custom parameters:** Allow users to modify input_arguments or keep it simple?
4. **Scheduling:** Add ability to schedule cases for later execution?

---

## References

- [Atomic Red Team GitHub](https://github.com/redcanaryco/atomic-red-team)
- [Invoke-AtomicRedTeam](https://github.com/redcanaryco/invoke-atomicredteam)
- [MITRE ATT&CK Framework](https://attack.mitre.org/)
- Shifter Engine: `shifter-engine/components/setup_orchestrator.py`
- Sidebar pattern: `portal/templates/partials/icon_sidebar.html`
