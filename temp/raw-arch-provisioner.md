# Shifter Provisioner & Infrastructure Architecture Review

## 1. Summary - Overall Architectural Health

**Rating: Adequate** (between Adequate and Needs Work)

The Shifter Provisioner demonstrates a well-intentioned layered architecture with clear separation of concerns through Orchestrators, Plans, Executors, and Components. However, the implementation suffers from **significant architectural drift** and **pattern inconsistency** that undermines maintainability and scalability.

The core challenge is a **2,911-line monolithic main.py** that has become a dumping ground for business logic, violating the very abstractions the codebase establishes. The provisioner successfully handles complex infrastructure orchestration (VPCs, EC2, NGFWs, Domain Controllers) but does so through a mix of Pulumi, Terraform, direct boto3 calls, and imperative orchestration that lacks architectural coherence. The system works, but technical debt is accumulating rapidly.

**Key Insight**: The architecture has excellent *bones* (Orchestrator/Plan/Executor pattern, Component abstraction) but poor *discipline* in following them. About 60% of code respects the patterns; 40% bypasses them for expedience.

## 2. Strengths

### 2.1 Clear Separation of Concerns in Core Patterns
- **Orchestrator Pattern** (`orchestrators/base.py`, `setup_orchestrator.py`, `ops_orchestrator.py`): Clean protocol-based abstraction with `StepResult` returns. SetupOrchestrator handles reboot coordination intelligently.
- **Plan Pattern** (`plans/base.py`): Protocol-based design allows declarative setup definitions. Plans like `BootstrapPlan` and `DCSetupPlan` are self-contained and composable.
- **Executor Pattern** (`executors/base.py`): Consistent `CommandResult` interface across SSM, SSH, and AWS executors. Good error hierarchy.

### 2.2 Configuration Management
- **config.py** (583 lines): Well-structured dataclasses (`RangeConfig`, `SubnetConfig`, `InstanceConfig`) with clear validation.
- **Dual auth support**: Clean switching between local dev (password) and production (RDS IAM).

### 2.3 Event-Driven Architecture
- **events.py**: Clean SNS pub/sub abstraction with typed event creation. Events are notification-only; state written to DB first.
- **Shared event contracts**: `cyberscript/messages/events.py` uses Pydantic models for type safety.

### 2.4 Logging and Observability
- **ECS-compliant logging**: Structured JSON logs with trace IDs, ready for CloudWatch ingestion.
- **Context propagation**: Labels like `range_id`, `user_id` properly threaded through log statements.

### 2.5 Infrastructure as Code Integration
- **Component abstraction** (`components/network.py`, `components/instance.py`): Pulumi ComponentResource pattern properly used. NetworkComponent handles subnet allocation with PostgreSQL advisory locks for concurrency safety.

## 3. Critical Issues

### 3.1 CRITICAL: main.py Monolith (2,911 Lines)
Contains 45+ functions mixing infrastructure orchestration, DB access, Pulumi/Terraform execution, NGFW configuration, and business logic. Functions like `run_instance_setup()` (lines 1754-1847) bypass the orchestrator pattern entirely.

**Impact**: Impossible to unit test without massive mocking, violates orchestrator pattern, high cognitive load, merge conflicts inevitable.

### 3.2 CRITICAL: Mixed IaC Strategy (Pulumi + Terraform)
No clear separation of responsibilities. Same resources managed by different tools. Feature-flag detection (`has_terraform_state()`) used to decide which tool at runtime.

**Impact**: State management nightmare, no single source of truth, operational complexity, risk of resource drift.

### 3.3 CRITICAL: Provisioner/Platform Coupling via Direct DB Access
Provisioner directly queries Django database tables with raw SQL (`UPDATE mission_control_range SET...`).

**Impact**: Django schema changes break provisioner, bypasses Django ORM validation, tight coupling, no rollback capability.

### 3.4 CRITICAL: Error Handling and Recovery
No transactional boundaries or rollback mechanisms. Partial failures leave inconsistent state (DB says "ready", NGFW unconfigured). No cleanup on failure - EC2 instances left running if setup fails.

## 4. Moderate Issues

### 4.1 Component Pattern Ambiguity
"Component" means Pulumi ComponentResource, but naming implies business domain component.

### 4.2 Plan Proliferation Without Strategy
21 plan files with no clear lifecycle ownership or grouping strategy.

### 4.3 OpsOrchestrator Underutilized
Defined but barely used. Most "ops" logic lives in `range_ops.py` instead.

### 4.4 Frontend Architecture: jQuery-style Vanilla JS
No frontend framework. Long procedural JavaScript class with manual DOM manipulation. Hard to test, ad-hoc state management, no component reuse.

## 5. Minor Issues

- DynamicPlan workaround (code smell - plans should be declarative)
- AMI lookup at runtime (adds latency and failure mode)
- Magic strings for status values (duplication risk with cyberscript enums)
- Dockerfile contains both Pulumi and Terraform (bloats image)

## 6. Architectural Patterns

### Good Patterns
- Protocol-Based Abstractions (Orchestrator, Executor, SetupPlan)
- Event Sourcing (Partial) - state written to DB first, events published after
- Configuration as Data - dataclasses separate data from logic

### Bad Patterns
- God Objects (main.py 2,911 lines, dashboard.js 2,000+ lines)
- Imperative Orchestration bypassing proper abstractions
- Mixed Abstraction Levels in same module
- Implicit Dependencies (provisioner assumes Django schema)

## 7. Cross-Boundary Concerns

### 7.1 Provisioner -> Platform Communication
**Mechanism**: SNS -> SQS -> Django handlers. Decoupled, scalable, typed contracts.
**Weaknesses**: No schema versioning, no DLQ visibility, event duplication not handled.

### 7.2 Platform -> Provisioner Communication
**Mechanism**: ECS Fargate task invocation.
**Weaknesses**: Direct DB coupling, no retry mechanism, no progress tracking.

### 7.3 Frontend -> Backend Communication
**Mechanism**: WebSockets + REST. Real-time feedback via WebSocket.
**Weaknesses**: No reconnection backoff, large JS monolith, no state machine.

### 7.4 Provisioner -> AWS Services
**Mechanisms**: Multiple (Pulumi, Terraform, boto3, SSM, SSH) - lacks coherence.
**Recommendation**: Consolidate on Terraform for infrastructure, boto3 for runtime operations. Eliminate Pulumi.

## 8. Recommendations (Prioritized)

### P0 (Critical)
1. Refactor main.py (target <500 lines per file)
2. Finish Terraform migration, remove Pulumi
3. Add transactional rollback (saga pattern or lifecycle hooks)

### P1 (High)
4. Decouple provisioner from Django DB (use event-carried state transfer)
5. Add schema versioning to events
6. Implement DLQ monitoring

### P2 (Medium)
7. Reorganize plans into namespaces
8. Extend test coverage for orchestrators and plans
9. Document IaC state management

### P3 (Low)
10. Consider frontend framework (Alpine.js or Stimulus)
11. Add OpenTelemetry tracing

**Overall Rating: Adequate** - the system works and has recoverable architecture, but is on a trajectory toward "Needs Work" if main.py continues to grow.
