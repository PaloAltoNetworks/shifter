# Upcoming Features

Design documents for planned capabilities. These describe potential approaches, not committed implementations.

## Attack Execution

Two complementary approaches for different use cases:

| Approach | Use Case | Complexity | Status |
|----------|----------|------------|--------|
| [Atomic Red Team](atomic-red-team.md) | Case as Outcome | Low | Design |
| [OpenBAS Integration](openbas-integration.md) | Range as Outcome | Medium | Design |

### Case as Outcome

User wants XDR/XSIAM alerts without operating a range.

- Ephemeral range lifecycle
- Automated attack execution
- No user interaction with range
- Range destroys after attacks complete

**Implementation:** Extend SetupPlan pattern with AttackPlan. Use Atomic Red Team as content library. Execute via existing SSMExecutor.

See [Atomic Red Team Integration](atomic-red-team.md) for full design.

### Range as Outcome

User wants an interactive range with rich attack capabilities.

- Long-lived range lifecycle
- User-driven attack execution
- Scenario library and management
- Multi-tenant central infrastructure

**Implementation:** Deploy OpenBAS as shared infrastructure. Integrate via REST API. Deploy agents during range provisioning.

See [OpenBAS Integration](openbas-integration.md) for full design.

## Comparison

| Aspect | Atomic Red Team | OpenBAS |
|--------|-----------------|---------|
| Infrastructure | None (scripts only) | Central server |
| Execution | SSM Run Command | OpenBAS agents |
| UI | None (automated) | OpenBAS web UI |
| Scenarios | Python classes | OpenBAS platform |
| Multi-tenant | N/A | Native |
| Content | 1,225+ atomic tests | Imports ART + custom |

## Reading These Documents

Each document follows this structure:

1. **Use case** - What problem it solves
2. **Design principles** - Guiding constraints
3. **Architecture** - Component diagrams and interactions
4. **Component design** - Data structures and protocols
5. **Execution flow** - Sequence diagrams
6. **Migration path** - Phased implementation plan
7. **Open questions** - Decisions needed before implementation

Documents are written for implementation by another agent. They prioritize:

- Consistency with existing codebase patterns
- Sound architectural decisions
- Maintainable abstractions
- Explicit trade-offs

Code snippets are illustrative, not prescriptive. Implementers should follow existing conventions.
