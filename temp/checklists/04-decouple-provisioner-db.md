# Checklist: Decouple Provisioner from Django Database

**Priority:** HIGH (Architecture P0) | **Effort:** Large (2-4 weeks) | **Risk if deferred:** Django model changes silently break provisioner, schema evolution blocked

---

## Context

The provisioner executes raw SQL directly against Django-managed tables (`mission_control_range`, `engine_instance`, `engine_subnet`, `engine_app`, `engine_request`). This creates tight coupling:

- Django model changes silently break the provisioner (no migration coordination)
- Django ORM validation is bypassed (data integrity at risk)
- The provisioner is not independently deployable
- Schema changes require coordinated deploys

**Scope of coupling** (4 files, 20+ raw SQL statements):
- `main.py` - 15+ SQL statements (UPDATE/SELECT against 5 tables)
- `range_ops.py` - 6+ SQL statements (UPDATE/SELECT for pause/resume)
- `config.py` - 2 SQL statements (SELECT for range config loading)
- `components/network.py` - PostgreSQL advisory locks for subnet allocation

**Additionally:** 3 duplicate `get_db_connection()` functions exist across main.py, config.py, and network.py.

**Current event system:** SNS-based, notification-only. State is written to DB first, then events published. Events carry no state payload - consumers query the DB.

---

## Pre-Work: Catalog All Coupling Points

### Reads (provisioner reads FROM Django tables)
- [ ] Catalog every SELECT in `main.py` with: table, columns, purpose, caller
- [ ] Catalog every SELECT in `range_ops.py` with: table, columns, purpose, caller
- [ ] Catalog every SELECT in `config.py` with: table, columns, purpose, caller
- [ ] For each read, determine: could this data be passed in via the ECS task environment/args instead?
- [ ] For each read, determine: could this data be carried in the SNS event instead?

### Writes (provisioner writes TO Django tables)
- [ ] Catalog every UPDATE/INSERT in `main.py` with: table, columns, purpose, caller
- [ ] Catalog every UPDATE/INSERT in `range_ops.py` with: table, columns, purpose, caller
- [ ] For each write, determine: could this be replaced by an event that tells the platform to update itself?
- [ ] For each write, identify whether the write is for provisioner-internal state or platform-visible state

### Advisory Locks
- [ ] Document the advisory lock pattern in `network.py` for subnet allocation
- [ ] Determine if subnet allocation can move to the platform side (allocated before ECS task launch)
- [ ] If not, document why the lock must remain in the provisioner

## Phase 1: Eliminate Provisioner DB Reads (Lowest Risk)

The principle: **pass data IN rather than letting the provisioner query for it.**

### Pass Range Data via ECS Task Environment
- [ ] Read `engine/ecs.py` to understand how ECS tasks are launched
- [ ] Identify what range data the provisioner currently fetches from DB at startup
- [ ] Determine which fields can be passed as ECS task environment variables or command args
- [ ] Add range spec JSON as an environment variable or S3 presigned URL
- [ ] Modify `get_range_data_by_request_id()` to read from env/args first, DB as fallback
- [ ] Modify `get_ngfw_data_by_request_id()` similarly
- [ ] Modify `config.py:load_config()` to accept config as parameter instead of DB query

### Pass NGFW Data via ECS Task Environment
- [ ] Identify NGFW data fetched by `get_user_ngfw_data()`
- [ ] Pass NGFW management IP, SSH key ARN, data ENI ID via environment
- [ ] Modify `get_user_ngfw_data()` to read from env first

### Eliminate `config.py` DB Reads
- [ ] `get_range_from_db()` (line 274) - replace with data passed from platform
- [ ] NGFW data ENI lookup (line 304) - replace with data passed from platform
- [ ] Remove `get_db_connection()` from config.py once no DB reads remain

## Phase 2: Convert Provisioner DB Writes to Events (Higher Risk)

The principle: **provisioner publishes events; platform handlers write to Django tables.**

### Design the Event Schema
- [ ] Define event types for each current DB write:
    - `range.status_updated` (replaces `update_range_status`)
    - `range.provisioned` (replaces `write_provisioned_state`)
    - `range.instances_destroyed` (replaces `mark_range_instances_destroyed`)
    - `instance.state_updated` (replaces `update_instance_state`)
    - `ngfw.subnets_removed` (replaces direct subnet DB cleanup)
- [ ] Define event payloads with all data the platform handler needs to write
- [ ] Add schema version field to all events
- [ ] Document in `events.py` alongside existing event definitions

### Implement Platform-Side Event Handlers
- [ ] Read existing handlers: `engine/handlers.py`, `cms/handlers.py`, `mission_control/handlers.py`
- [ ] For each new event type, add a handler that:
    - Parses the event payload
    - Performs the Django ORM operation that the provisioner currently does via raw SQL
    - Uses `transaction.atomic()` for multi-step writes
    - Is idempotent (handles duplicate SQS delivery)
- [ ] Test each handler independently with mock events

### Migrate Provisioner Writes One at a Time
- [ ] **Start with `update_range_status`** (most common, simplest):
    - Replace raw SQL UPDATE with `publish_status_update()` event carrying new status + kwargs
    - Add platform handler that receives event and does ORM update
    - Deploy handler first, then provisioner change (backward compatible)
    - Verify via logs that events flow correctly
    - Remove raw SQL code
- [ ] **Next: `write_provisioned_state`**:
    - Publish `range.provisioned` event with subnet states, instance states, provisioned_instances JSON
    - Add platform handler
    - Deploy in order
- [ ] **Next: `mark_range_instances_destroyed`**:
    - Publish `range.instances_destroyed` event with range_id
    - Add platform handler
    - Deploy in order
- [ ] **Next: `update_instance_state`**:
    - Publish `instance.state_updated` event with instance data, new status, state JSON
    - Add platform handler
    - Deploy in order
- [ ] **Next: `range_ops.py` pause/resume writes**:
    - Same pattern for instance status updates during pause/resume

## Phase 3: Handle Advisory Locks

- [ ] Evaluate whether subnet CIDR allocation can move to the platform:
    - Platform allocates CIDRs using `select_for_update()` (already exists in engine/services.py)
    - Passes allocated CIDRs to provisioner via environment
    - Provisioner never needs advisory locks
- [ ] If allocation moves to platform:
    - Remove `_get_db_connection()` from `components/network.py`
    - Modify `allocate_subnets()` to accept pre-allocated CIDRs
    - Remove advisory lock code
- [ ] If allocation must stay in provisioner:
    - Document why and keep as the last remaining DB dependency
    - Consider a dedicated microservice or API endpoint for allocation

## Phase 4: Cleanup

- [ ] Remove `get_db_connection()` from `main.py`
- [ ] Remove `get_db_connection()` from `config.py` (if Phase 1 complete)
- [ ] Remove `_get_db_connection()` from `components/network.py` (if Phase 3 complete)
- [ ] Remove `import psycopg` from files that no longer need it
- [ ] Remove `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME` from provisioner ECS task env (if fully decoupled)
- [ ] Update provisioner Dockerfile to remove psycopg dependency (if fully decoupled)
- [ ] Remove raw SQL from `range_ops.py`

## Verification

- [ ] Run provisioner tests after each phase
- [ ] Run platform tests after each handler addition
- [ ] Test in dev environment with actual ECS task launch
- [ ] Verify event flow end-to-end: provisioner -> SNS -> SQS -> platform handler -> DB
- [ ] Test idempotency: replay an event and verify no duplicate/corrupt data
- [ ] Test ordering: verify events processed in order don't cause race conditions
- [ ] Load test: verify no message backlog under normal provisioning load
- [ ] Verify Django model changes no longer require provisioner redeployment

## Rollback Plan

- [ ] Keep `get_db_connection()` and raw SQL code behind a feature flag during migration
- [ ] Provisioner checks flag: if enabled, uses events; if disabled, uses direct DB
- [ ] Remove flag and dead code only after 2 weeks of stable event-based operation

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| SQS message delay causes stale UI | Platform handler sends WebSocket update immediately on event receipt |
| Event loss (SQS failure) | Add DLQ monitoring, alert on DLQ depth > 0 |
| Event ordering (SQS FIFO vs Standard) | Use message group ID = range_id for FIFO ordering |
| Dual-write during migration | Feature flag allows instant rollback |
| Advisory lock contention during migration | Migrate locks last, after all other coupling removed |
