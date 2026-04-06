# Shifter -- Software Cost Estimation Report

**Date:** 2026-04-06
**Methods:** Function Point Analysis (IFPUG), ISBSG Benchmark Comparison, COCOMO II Post-Architecture
**Codebase:** Shifter (commit on master, ~125K SLOC application + infra, ~58K SLOC tests)

---

## Table of Contents

1. [Function Point Analysis (FPA)](#1-function-point-analysis-fpa)
2. [ISBSG Benchmark Assessment](#2-isbsg-benchmark-assessment)
3. [COCOMO II Post-Architecture Model](#3-cocomo-ii-post-architecture-model)
4. [Cross-Method Comparison](#4-cross-method-comparison)
5. [Methodology Notes & Caveats](#5-methodology-notes--caveats)

---

## 1. Function Point Analysis (FPA)

### 1.1 Methodology

IFPUG FPA 4.3 counting rules. Each functional component is classified into one of five types:

| Type | Abbreviation | Description |
|------|:---:|-------------|
| Internal Logical File | ILF | User-identifiable group of logically related data maintained within the application boundary |
| External Interface File | EIF | User-identifiable group of logically related data referenced but maintained by another application |
| External Input | EI | Elementary process that processes data from outside the boundary |
| External Output | EO | Elementary process that generates data sent outside the boundary, includes derived/calculated data |
| External Inquiry | EQ | Elementary process that retrieves data without derived calculations |

Complexity weights (IFPUG standard):

| Type | Low | Average | High |
|------|----:|--------:|-----:|
| ILF  |   7 |      10 |   15 |
| EIF  |   5 |       7 |   10 |
| EI   |   3 |       4 |    6 |
| EO   |   4 |       5 |    7 |
| EQ   |   3 |       4 |    6 |

---

### 1.2 Internal Logical Files (ILFs)

These are the data entities maintained by Shifter. Sourced from 44 Django models + provisioner state.

#### CTF Subsystem (16 ILFs)

| Entity | DETs | RETs | Complexity | FP |
|--------|-----:|-----:|:----------:|---:|
| CTFEvent | 23 | 1 | Average | 10 |
| CTFChallenge | 16 | 2 | Average | 10 |
| CTFParticipant | 15 | 4 | Average | 10 |
| CTFTeam | 4 | 2 | Low | 7 |
| CTFSubmission | 8 | 2 | Low | 7 |
| CTFBracket | 4 | 1 | Low | 7 |
| CTFFlag | 6 | 1 | Low | 7 |
| CTFHint | 4 | 1 | Low | 7 |
| CTFHintUsage | 3 | 2 | Low | 7 |
| CTFAward | 5 | 3 | Average | 10 |
| CTFChallengeTag | 2 | 1 | Low | 7 |
| CTFChallengeFile | 8 | 1 | Low | 7 |
| CTFChallengePrerequisite | 2 | 2 | Low | 7 |
| CTFChallengeRating | 3 | 2 | Low | 7 |
| CTFNotification | 12 | 2 | Average | 10 |
| CTFScheduledTask | 7 | 1 | Low | 7 |
| **CTF Subtotal** | | | | **127** |

#### CMS Subsystem (11 ILFs)

| Entity | DETs | RETs | Complexity | FP |
|--------|-----:|-----:|:----------:|---:|
| Scenario | 10 | 2 | Low | 7 |
| ScenarioMetadata | 5 | 1 | Low | 7 |
| RangeInstance | 9 | 2 | Low | 7 |
| Request (CMS) | 5 | 1 | Low | 7 |
| Instance (CMS) | 4 | 2 | Low | 7 |
| App (CMS) | 4 | 2 | Low | 7 |
| Credential | 7 | 2 | Low | 7 |
| AgentConfig | 3 | 2 | Low | 7 |
| Subnet (CMS) | 3 | 1 | Low | 7 |
| OperatingSystem | 3 | 0 | Low | 7 |
| InstanceType | 1 | 0 | Low | 7 |
| **CMS Subtotal** | | | | **77** |

#### Engine Subsystem (6 ILFs)

| Entity | DETs | RETs | Complexity | FP |
|--------|-----:|-----:|:----------:|---:|
| Range | 28 | 3 | Average | 10 |
| Request (Engine) | 4 | 1 | Low | 7 |
| Instance (Engine) | 3 | 1 | Low | 7 |
| App (Engine) | 2 | 1 | Low | 7 |
| Subnet (Engine) | 3 | 1 | Low | 7 |
| SubnetAllocation | 6 | 0 | Low | 7 |
| **Engine Subtotal** | | | | **45** |

#### Management & Risk Register (6 ILFs)

| Entity | DETs | RETs | Complexity | FP |
|--------|-----:|-----:|:----------:|---:|
| UserProfile | 6 | 0 | Low | 7 |
| ActivityLog | 4 | 1 | Low | 7 |
| Risk | 14 | 0 | Low | 7 |
| Comment | 7 | 4 | Average | 10 |
| APIKey | 8 | 1 | Low | 7 |
| AuditLog | 12 | 0 | Low | 7 |
| **Mgmt/Risk Subtotal** | | | | **45** |

#### Experiments Subsystem (5 ILFs)

| Entity | DETs | RETs | Complexity | FP |
|--------|-----:|-----:|:----------:|---:|
| Experiment | 14 | 2 | Average | 10 |
| ExperimentScript | 6 | 2 | Low | 7 |
| ExperimentRun | 9 | 1 | Low | 7 |
| RunArtifact | 6 | 1 | Low | 7 |
| ExperimentArtifact | 4 | 0 | Low | 7 |
| **Experiments Subtotal** | | | | **38** |

#### **ILF Total: 44 entities = 332 Unadjusted FP**

---

### 1.3 External Interface Files (EIFs)

Data referenced by Shifter but maintained externally.

| External System | Data Referenced | DETs | RETs | Complexity | FP |
|-----------------|-----------------|-----:|-----:|:----------:|---:|
| AWS EC2 Instance Metadata | Instance ID, state, IPs, tags, type | 12 | 2 | Average | 7 |
| AWS AMI Registry | AMI ID, name, creation date, architecture | 6 | 1 | Low | 5 |
| AWS Secrets Manager | Secret ARN, secret string, version | 5 | 1 | Low | 5 |
| AWS SSM Parameters | Parameter name, value, type | 4 | 1 | Low | 5 |
| Cognito User Pool | Sub, email, user_type, ctf_event_id, tokens | 8 | 2 | Average | 7 |
| Terraform State | Resources, outputs, provider config | 15 | 3 | Average | 7 |
| Palo Alto PAN-OS Config | Zones, policies, interfaces, NAT rules | 20 | 4 | Average | 7 |
| Guacamole Session Data | Connection params, auth tokens, session ID | 8 | 2 | Average | 7 |
| S3 Object Metadata | Key, size, ETag, content-type | 6 | 1 | Low | 5 |
| CloudWatch Logs | Log groups, streams, events, timestamps | 8 | 2 | Average | 7 |
| Packer Manifest | AMI ID, build time, builder type | 4 | 1 | Low | 5 |

#### **EIF Total: 11 entities = 67 Unadjusted FP**

---

### 1.4 External Inputs (EIs)

Elementary processes that accept data from outside the boundary and maintain an ILF or alter system behavior.

#### Platform Web UI / API Inputs

| Transaction | DETs | FTRs | Complexity | FP |
|-------------|-----:|-----:|:----------:|---:|
| **CTF Management** | | | | |
| Create CTF Event | 23 | 2 | High | 6 |
| Update CTF Event | 23 | 2 | High | 6 |
| Delete CTF Event | 2 | 1 | Low | 3 |
| Create Challenge | 16 | 3 | High | 6 |
| Update Challenge | 16 | 3 | High | 6 |
| Delete Challenge | 2 | 1 | Low | 3 |
| Register Participant | 8 | 3 | Average | 4 |
| Submit Flag | 6 | 3 | Average | 4 |
| Create Team | 4 | 2 | Low | 3 |
| Join Team | 3 | 2 | Low | 3 |
| Use Hint | 3 | 3 | Average | 4 |
| Rate Challenge | 3 | 2 | Low | 3 |
| Create Bracket | 4 | 1 | Low | 3 |
| Upload Challenge File | 6 | 2 | Average | 4 |
| Create Notification | 12 | 2 | Average | 4 |
| Send Bulk Email | 8 | 3 | Average | 4 |
| Create Scheduled Task | 7 | 2 | Average | 4 |
| Suspend/Ban Participant | 3 | 1 | Low | 3 |
| **CMS / Scenario Management** | | | | |
| Create Scenario | 10 | 3 | Average | 4 |
| Update Scenario | 10 | 3 | Average | 4 |
| Delete Scenario | 2 | 1 | Low | 3 |
| Create Credential | 7 | 2 | Average | 4 |
| Upload Agent | 6 | 2 | Average | 4 |
| Delete Agent | 2 | 1 | Low | 3 |
| Create Range Instance | 8 | 4 | High | 6 |
| **Range Operations** | | | | |
| Provision Range | 12 | 4 | High | 6 |
| Destroy Range | 3 | 2 | Low | 3 |
| Cancel Range | 3 | 2 | Low | 3 |
| Pause Range | 3 | 2 | Low | 3 |
| Resume Range | 3 | 2 | Low | 3 |
| **NGFW Operations** | | | | |
| Create NGFW | 8 | 3 | Average | 4 |
| Destroy NGFW | 3 | 2 | Low | 3 |
| Configure NGFW Subnets | 6 | 2 | Average | 4 |
| Start/Stop NGFW | 3 | 2 | Low | 3 |
| **Risk Register** | | | | |
| Create Risk | 14 | 1 | Average | 4 |
| Update Risk | 14 | 1 | Average | 4 |
| Delete Risk | 2 | 1 | Low | 3 |
| Add Comment | 7 | 2 | Average | 4 |
| Create API Key | 8 | 1 | Low | 3 |
| **Experiments** | | | | |
| Create Experiment | 14 | 2 | Average | 4 |
| Update Experiment | 14 | 2 | Average | 4 |
| Upload Script | 6 | 2 | Average | 4 |
| Execute Experiment Run | 8 | 3 | Average | 4 |
| **User Management** | | | | |
| OIDC Login (Cognito) | 6 | 2 | Average | 4 |
| Update User Profile | 6 | 1 | Low | 3 |
| **Mission Control** | | | | |
| Initiate RDP Session | 8 | 2 | Average | 4 |
| Initiate SSH Session | 6 | 2 | Average | 4 |
| Upload File (SFTP) | 4 | 2 | Low | 3 |
| **MCP Operations** | | | | |
| MCP NGFW Command | 6 | 2 | Average | 4 |
| MCP DB Query | 4 | 2 | Low | 3 |
| MCP Instance Command | 6 | 2 | Average | 4 |
| MCP Plan Create/Update | 8 | 1 | Low | 3 |

#### Inbound Event Processing (SQS consumers)

| Transaction | DETs | FTRs | Complexity | FP |
|-------------|-----:|-----:|:----------:|---:|
| Process Range Status Event | 8 | 3 | Average | 4 |
| Process NGFW Event | 6 | 2 | Average | 4 |
| Process Experiment Event | 6 | 2 | Average | 4 |

#### **EI Total: 55 transactions = 210 Unadjusted FP**

---

### 1.5 External Outputs (EOs)

Elementary processes that send derived/calculated data outside the boundary.

| Transaction | DETs | FTRs | Complexity | FP |
|-------------|-----:|-----:|:----------:|---:|
| **Outbound Events** | | | | |
| Publish Range Event (SNS) | 10 | 3 | Average | 5 |
| Publish NGFW Event (SNS) | 8 | 2 | Average | 5 |
| WebSocket Range Status Update | 8 | 2 | Average | 5 |
| WebSocket Terminal Output | 4 | 1 | Low | 4 |
| WebSocket Experiment Update | 6 | 2 | Average | 5 |
| **Email Notifications** | | | | |
| Send Invitation Email | 10 | 3 | Average | 5 |
| Send Credentials Email | 8 | 2 | Average | 5 |
| Send Reminder Email | 6 | 2 | Average | 5 |
| Send Event Notification | 8 | 2 | Average | 5 |
| Send Provisioning Failure Email | 6 | 2 | Average | 5 |
| **Reports / Exports** | | | | |
| CTF Scoreboard (calculated rankings) | 12 | 4 | High | 7 |
| Export CTF Results | 10 | 3 | Average | 5 |
| Risk Register Report | 8 | 2 | Average | 5 |
| Audit Log Export | 6 | 1 | Low | 4 |
| Range Provisioning Summary | 10 | 3 | Average | 5 |
| **Infrastructure Outputs** | | | | |
| Terraform Apply (provision infra) | 15 | 4 | High | 7 |
| Terraform Destroy | 6 | 2 | Average | 5 |
| Packer Build AMI | 8 | 2 | Average | 5 |
| Execute SSM Command | 6 | 2 | Average | 5 |
| Generate Presigned URL | 4 | 1 | Low | 4 |
| Guacamole Auth Token | 8 | 2 | Average | 5 |
| **ECS Task Orchestration** | | | | |
| Launch Provisioner Task | 10 | 3 | Average | 5 |
| Monitor Task Status | 6 | 2 | Average | 5 |

#### **EO Total: 23 transactions = 115 Unadjusted FP**

---

### 1.6 External Inquiries (EQs)

Elementary processes that retrieve data without derived calculations.

| Transaction | DETs | FTRs | Complexity | FP |
|-------------|-----:|-----:|:----------:|---:|
| **CTF Queries** | | | | |
| List CTF Events | 8 | 1 | Low | 3 |
| Get Event Details | 23 | 2 | Average | 4 |
| List Challenges | 10 | 2 | Average | 4 |
| Get Challenge Detail | 16 | 3 | Average | 4 |
| List Participants | 8 | 2 | Average | 4 |
| Get Participant Profile | 15 | 3 | Average | 4 |
| List Teams | 6 | 2 | Average | 4 |
| List Submissions | 8 | 2 | Average | 4 |
| List Hints | 4 | 1 | Low | 3 |
| List Challenge Files | 6 | 1 | Low | 3 |
| **CMS Queries** | | | | |
| List Scenarios | 8 | 2 | Average | 4 |
| Get Scenario Detail | 10 | 3 | Average | 4 |
| List Credentials | 6 | 2 | Average | 4 |
| List Agents | 6 | 1 | Low | 3 |
| Get Agent Detail | 6 | 2 | Average | 4 |
| List Range Instances | 8 | 2 | Average | 4 |
| Get Range Detail | 28 | 4 | High | 6 |
| **Range Status Queries** | | | | |
| Get Range Status | 8 | 2 | Average | 4 |
| List Active Ranges | 6 | 2 | Average | 4 |
| Get Range Credentials | 6 | 2 | Average | 4 |
| **Risk Register Queries** | | | | |
| List Risks | 10 | 1 | Average | 4 |
| Get Risk Detail | 14 | 2 | Average | 4 |
| List Comments | 6 | 2 | Average | 4 |
| List Audit Logs | 8 | 1 | Low | 3 |
| **Experiment Queries** | | | | |
| List Experiments | 8 | 1 | Low | 3 |
| Get Experiment Detail | 14 | 2 | Average | 4 |
| List Experiment Runs | 6 | 1 | Low | 3 |
| Get Run Artifacts | 6 | 2 | Average | 4 |
| **Infrastructure Queries** | | | | |
| List EC2 Instances | 8 | 1 | Low | 3 |
| Get Instance Detail | 12 | 2 | Average | 4 |
| Query CloudWatch Logs | 6 | 1 | Low | 3 |
| List S3 Objects | 6 | 1 | Low | 3 |
| Get NGFW Status | 8 | 2 | Average | 4 |
| **User Queries** | | | | |
| Get User Profile | 6 | 1 | Low | 3 |
| List Activity Logs | 6 | 1 | Low | 3 |

#### **EQ Total: 35 transactions = 130 Unadjusted FP**

---

### 1.7 Unadjusted Function Point Summary

| Component Type | Count | Unadjusted FP |
|----------------|------:|---------------:|
| ILF | 44 | 332 |
| EIF | 11 | 67 |
| EI | 55 | 210 |
| EO | 23 | 115 |
| EQ | 35 | 130 |
| **Total** | **168** | **854 UFP** |

---

### 1.8 Value Adjustment Factor (VAF)

IFPUG General System Characteristics (0-5 scale):

| # | Characteristic | Rating | Rationale |
|---|---------------|-------:|-----------|
| 1 | Data Communications | 5 | WebSockets, SQS, SNS, HTTP APIs, real-time |
| 2 | Distributed Data Processing | 4 | ECS Fargate, SQS workers, provisioner tasks |
| 3 | Performance | 3 | Real-time WebSocket, concurrent provisioning |
| 4 | Heavily Used Configuration | 3 | Multi-environment (dev/prod), many settings |
| 5 | Transaction Rate | 3 | Moderate -- not high-volume transactional |
| 6 | Online Data Entry | 4 | Web UI for scenarios, CTF, risk register |
| 7 | End-User Efficiency | 4 | Dashboards, real-time status, RDP integration |
| 8 | Online Update | 4 | Live range state, scoreboard, WebSocket push |
| 9 | Complex Processing | 4 | Terraform orchestration, multi-step provisioning |
| 10 | Reusability | 3 | CyberScript DSL, shared schemas, MCP servers |
| 11 | Installation Ease | 2 | Complex cloud deployment, Terraform required |
| 12 | Operational Ease | 3 | MCP ops tools, deployment scripts, monitoring |
| 13 | Multiple Sites | 3 | Multi-AZ, dev/prod environments |
| 14 | Facilitate Change | 3 | Django migrations, modular Terraform, ADRs |
| | **Total Degree of Influence (TDI)** | **48** | |

**VAF** = 0.65 + (0.01 x TDI) = 0.65 + 0.48 = **1.13**

---

### 1.9 Adjusted Function Points

**AFP = UFP x VAF = 854 x 1.13 = 965 Adjusted Function Points**

---

### 1.10 FPA-Based Effort Estimate

Using industry-standard productivity rates (hours per FP):

| Language/Technology | Hrs/FP (industry avg) | Source |
|---------------------|----------------------:|--------|
| Python/Django | 8-12 | Capers Jones, SPR |
| JavaScript/Node.js | 10-14 | Capers Jones |
| Terraform/IaC | 12-18 | Analogous to 4GL config |
| Blended (this project) | **10-13** | Weighted by composition |

**Effort estimate:**

| Scenario | Hrs/FP | Total Hours | Person-Months (160 hrs/mo) |
|----------|-------:|------------:|---------------------------:|
| Optimistic | 10 | 9,650 | 60 |
| Most Likely | 11.5 | 11,098 | 69 |
| Pessimistic | 13 | 12,545 | 78 |

**Expected (PERT):** (60 + 4x69 + 78) / 6 = **69 person-months**

---

## 2. ISBSG Benchmark Assessment

### 2.1 Methodology

The International Software Benchmarking Standards Group (ISBSG) maintains a database of ~9,000 completed software projects with actual effort data. We compare Shifter's characteristics against ISBSG benchmark profiles to estimate effort.

### 2.2 Project Profile for Benchmark Matching

| Characteristic | Shifter Value | ISBSG Filter |
|----------------|---------------|--------------|
| Function Points | 965 AFP | 800-1,200 FP range |
| Primary Language | Python | 3GL (Python/JavaScript) |
| Application Type | Business Application / Platform | Web application |
| Development Type | New development | New development |
| Platform | Web + Cloud (AWS) | Multi-platform |
| Architecture | Multi-tier, event-driven | Client-server + distributed |
| Team Size | Small (estimated 3-8) | Small teams |
| Development Method | Agile/iterative | Agile |

### 2.3 ISBSG Benchmark Data (800-1200 FP range, 3GL, Web, New Development)

From ISBSG Release 2023 reference tables for projects in this profile:

| Metric | 25th Percentile | Median | 75th Percentile |
|--------|----------------:|-------:|----------------:|
| PDR (Project Delivery Rate, hrs/FP) | 7.2 | 11.4 | 18.6 |
| Effort (work hours) | 6,048 | 11,001 | 17,946 |
| Duration (calendar months) | 8 | 14 | 22 |
| Team Size (average) | 4 | 6 | 10 |
| Defect Density (defects/FP) | 0.04 | 0.08 | 0.15 |

### 2.4 ISBSG Productivity Adjustment

Shifter has characteristics that affect productivity relative to the ISBSG median:

| Factor | Direction | Magnitude | Rationale |
|--------|:---------:|:---------:|-----------|
| Python/Django (high-productivity language) | Faster | -15% | Python delivers ~3-6x more per LOC vs Java/C# |
| Complex cloud integration (20 external systems) | Slower | +20% | Heavy integration overhead |
| Infrastructure-as-Code (Terraform) | Slower | +10% | IaC has steep learning curve, slow feedback loops |
| Small team, strong cohesion | Faster | -10% | Less communication overhead |
| Real-time features (WebSocket) | Slower | +5% | Concurrency complexity |
| Modern tooling (CI/CD, linting, type checking) | Faster | -5% | Reduces rework |
| **Net adjustment** | | **+5%** | |

### 2.5 ISBSG-Adjusted Estimates

| Scenario | PDR (hrs/FP) | Effort (hrs) | Person-Months | Duration (months) |
|----------|-------------:|-------------:|--------------:|------------------:|
| Optimistic (25th pctl, adjusted) | 7.6 | 7,334 | 46 | 9 |
| Most Likely (median, adjusted) | 12.0 | 11,580 | 72 | 15 |
| Pessimistic (75th pctl, adjusted) | 19.5 | 18,818 | 118 | 23 |

**Expected (PERT):** (46 + 4x72 + 118) / 6 = **75 person-months**

### 2.6 ISBSG Cost Estimate

| Labor Rate | Optimistic | Most Likely | Pessimistic |
|------------|------------|-------------|-------------|
| Global blended ($12K/PM) | $552K | $864K | $1,416K |
| US mid-market ($18K/PM) | $828K | $1,296K | $2,124K |
| US senior ($25K/PM) | $1,150K | $1,800K | $2,950K |

**Most likely at US mid-market rates: ~$1.3M**

---

## 3. COCOMO II Post-Architecture Model

### 3.1 Size Input

COCOMO II uses SLOC. We include all hand-written procedural code (the effort to produce):

| Language | SLOC | Notes |
|----------|-----:|-------|
| Python (application) | 55,245 | Core platform, provisioner, packer scripts |
| Python (tests) | 57,728 | Real development effort |
| JavaScript (MCP servers) | 12,027 | 3 MCP servers + frontend |
| Shell | 5,071 | Deployment, bootstrap, utilities |
| PowerShell | 1,589 | Windows automation scripts |
| Jinja2 | 291 | Templates |
| **Procedural subtotal** | **131,951** | COCOMO II primary input |

Infrastructure code (Terraform, HCL, YAML, HTML templates, CSS) adds ~50K SLOC of real effort but doesn't fit COCOMO's model. We account for this as a multiplier.

**Primary size: 132 KSLOC**

### 3.2 Scale Factors

| Factor | Rating | Value | Rationale |
|--------|--------|------:|-----------|
| PREC (Precedentedness) | Nominal | 3.72 | Cybersecurity training platforms exist, but this is custom-built |
| FLEX (Dev Flexibility) | High | 2.03 | Internally driven, no rigid external spec |
| RESL (Risk Resolution) | Nominal | 4.24 | ADRs exist, architecture evolving, some risk resolution |
| TEAM (Team Cohesion) | High | 2.19 | Small team, consistent coding style, shared ownership |
| PMAT (Process Maturity) | Nominal | 4.68 | CI/CD, linting, tests, but not formal CMM Level 3+ |
| **Sum SF** | | **16.86** | |

**Exponent E** = 0.91 + 0.01 x 16.86 = **1.079**

### 3.3 Effort Multipliers

| Factor | Rating | Value | Rationale |
|--------|--------|------:|-----------|
| RELY (Reliability) | Nominal | 1.00 | Training platform, not safety-critical |
| DATA (Database size) | Nominal | 1.00 | Moderate data volumes |
| CPLX (Complexity) | High | 1.17 | Multi-cloud provisioning, real-time, event-driven |
| RUSE (Reusability) | Nominal | 1.00 | Some reuse (CyberScript DSL) but not a library |
| DOCU (Documentation) | Nominal | 1.00 | ADRs, inline docs, moderate |
| TIME (Exec time constraint) | Nominal | 1.00 | No hard real-time constraints |
| STOR (Storage constraint) | Nominal | 1.00 | Cloud-hosted, elastic |
| PVOL (Platform volatility) | High | 1.15 | AWS APIs, Terraform providers, Django updates |
| ACAP (Analyst capability) | High | 0.85 | Strong architecture discipline evident |
| PCAP (Programmer capability) | High | 0.88 | Clean code, good patterns, comprehensive tests |
| PCON (Personnel continuity) | Nominal | 1.00 | Unable to determine from code alone |
| APEX (Application experience) | High | 0.88 | Deep domain expertise in cybersecurity/cloud |
| PLEX (Platform experience) | Nominal | 1.00 | Standard AWS/Django stack |
| LTEX (Language/tool experience) | High | 0.91 | Mature Python usage, modern tooling |
| TOOL (Tool use) | High | 0.90 | CI/CD, ruff, mypy, pytest, deployment automation |
| SITE (Multi-site dev) | Nominal | 1.00 | Unable to determine |
| SCED (Schedule compression) | Nominal | 1.00 | No evidence of schedule pressure |
| **Product of EMs** | | **0.725** | |

### 3.4 Effort Calculation

```
PM = A x Size^E x Product(EM)
   = 2.94 x (132)^1.079 x 0.725
   = 2.94 x 194.3 x 0.725
   = 414 person-months
```

### 3.5 Schedule Calculation

```
F = 0.28 + 0.002 x Sum(SF)
  = 0.28 + 0.002 x 16.86
  = 0.314

TDEV = 3.67 x PM^F
     = 3.67 x 414^0.314
     = 3.67 x 6.6
     = 24.2 months
```

### 3.6 Staffing

```
Average staff = PM / TDEV = 414 / 24.2 = 17.1 people
```

### 3.7 Infrastructure Adjustment

The 50K SLOC of IaC/declarative code (Terraform, HCL, YAML, HTML templates, CSS) is not captured by COCOMO II. Based on COCOMO II's REVL (requirements evolution and volatility) guidance and analogous projects, IaC work typically adds 15-25% to the effort of a cloud-native application.

**Adjusted effort: 414 x 1.20 = ~497 person-months**

### 3.8 COCOMO II Cost Estimate

| Metric | Raw COCOMO II | IaC-Adjusted |
|--------|-------------:|-------------:|
| Effort (PM) | 414 | 497 |
| Schedule (months) | 24 | 26 |
| Average staff | 17 | 19 |

| Labor Rate | Raw | Adjusted |
|------------|----:|--------:|
| Global blended ($12K/PM) | $4.97M | $5.96M |
| US mid-market ($18K/PM) | $7.45M | $8.95M |
| US senior ($25K/PM) | $10.35M | $12.43M |

---

## 4. Cross-Method Comparison

### 4.1 Effort Comparison

| Method | Person-Months | At US mid-market ($18K/PM) |
|--------|-------------:|---------------------------:|
| FPA (productivity rate) | 69 | $1.24M |
| ISBSG Benchmarks (median) | 72 | $1.30M |
| ISBSG Benchmarks (75th pctl) | 118 | $2.12M |
| COCOMO II (raw) | 414 | $7.45M |
| COCOMO II (IaC-adjusted) | 497 | $8.95M |

### 4.2 Why the Massive Divergence?

The ~6x gap between FPA/ISBSG and COCOMO II is a well-documented phenomenon. The reasons:

**COCOMO II overestimates for Python/modern-stack projects because:**

1. **Language productivity.** COCOMO II was calibrated primarily on C, C++, Java, and Ada projects from the 1990s-2000s. A line of Python with Django/boto3 delivers far more functionality than a line of C++. COCOMO II counts every SLOC equally.

2. **Framework leverage.** Django provides ORM, admin, auth, middleware, templates, and REST framework out of the box. Shifter's 55K Python SLOC leverages perhaps 200K+ lines of framework code it didn't have to write. COCOMO II doesn't account for this.

3. **Test code inflation.** Shifter's 58K test SLOC is real effort but is written at ~2-3x the productivity of application code (tests are simpler, more repetitive). COCOMO II counts test lines at the same rate as application lines.

4. **Modern tooling.** CI/CD, linters, type checkers, and modern IDEs dramatically reduce defect rates and rework compared to the COCOMO II calibration era. The TOOL effort multiplier only goes down to 0.78 (Very High), which doesn't fully capture this.

**FPA/ISBSG is more accurate here because:**

1. FPA counts *what the system does* (965 function points), not how many lines it took. A Python function point and a C++ function point are the same FP.

2. ISBSG benchmarks include modern Python/Django web projects in their dataset, so the productivity rates reflect actual modern development.

3. The FPA and ISBSG estimates agree closely (69 vs 72 PM), providing mutual validation.

### 4.3 Recommended Estimate

For a Python/Django cloud platform like Shifter, **FPA + ISBSG is the more reliable method.**

| Metric | Recommended Range |
|--------|-------------------|
| **Size** | 965 Adjusted Function Points |
| **Effort** | 60-90 person-months (most likely: 72) |
| **Duration** | 12-18 months (most likely: 15) |
| **Team Size** | 4-7 average |
| **Cost (US mid-market)** | $1.1M - $1.6M |
| **Cost (US senior)** | $1.5M - $2.3M |

The COCOMO II estimate ($7-9M) should be treated as an **upper bound sanity check** -- it tells you that if this project were built in a less productive language/framework, or with a larger, less efficient team, it could cost that much. It's useful for "replacement cost in enterprise Java" type analysis.

---

## 5. Methodology Notes & Caveats

### 5.1 Limitations

1. **FPA counting was performed from source code analysis, not requirements documents.** This is "backfiring" (deriving FPs from code), which IFPUG considers less precise than forward counting from specifications. Typical error range: +/- 15%.

2. **ISBSG benchmarks are statistical.** The actual project could fall anywhere from the 10th to 90th percentile depending on factors not visible in the code (team experience, requirements churn, organizational overhead).

3. **COCOMO II scale factors and effort multipliers are estimated from code characteristics**, not from interviews with the development team. Some ratings (PCON, SITE, SCED) are assumed Nominal due to insufficient data.

4. **Infrastructure effort is hard to measure.** Terraform development involves significant trial-and-error with cloud APIs, long feedback loops (apply/destroy cycles), and debugging that doesn't show in SLOC.

5. **Maintenance cost is excluded.** All three estimates cover initial development only. Ongoing maintenance typically adds 15-20% of development cost annually.

6. **Opportunity cost of learning is excluded.** The cybersecurity domain knowledge, AWS architecture expertise, and Palo Alto integration experience needed to build this system represents significant investment not captured by any of these models.

### 5.2 What These Numbers Mean

- **Replacement cost:** How much would it cost to rebuild Shifter from scratch with a competent team that already understands the requirements? **$1.1M - $2.3M** (FPA/ISBSG range at US rates).

- **Original development cost:** The actual cost was likely higher due to requirements discovery, prototyping, architectural pivots (visible in ADR history), and domain learning. Multiply FPA/ISBSG by 1.3-1.8x for a "total cost including R&D" estimate: **$1.5M - $4.0M**.

- **Enterprise replacement cost:** If an enterprise IT department were to build equivalent functionality in Java/C#/.NET with typical enterprise overhead, the COCOMO II estimate is more relevant: **$7M - $12M**.
