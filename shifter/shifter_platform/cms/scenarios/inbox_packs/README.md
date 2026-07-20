# In-box scenario-pack catalog

`manifest.yaml` declares the scenario packs Shifter ships by default.

Per ADR-033/ADR-034, the in-box catalog is **not** loaded through a privileged
code path. The bootstrap (`cms.scenarios.inbox.register_inbox_packs`, invoked by
the `bootstrap_inbox_catalog` management command) registers each manifest entry
through the same `cms.services.register_pack` service an operator uses via the
API or the `register_pack` CLI. The shipped catalog is dogfooded through the
uniform, entitlement-blind ingestion boundary.

There are no conformant default packs yet (authored under program #1584), so
`manifest.yaml` currently declares an empty `packs` list. Add one entry per
shipped pack as they land; the entry shape matches the operator registration
request (see the example in `manifest.yaml`). Packs themselves are validated as
foreign input at registration against the `aces-scenario-packs` contract, and
their advertised digest must match the exact associated-artifact inventory.
Bootstrap retries are service-level no-ops only for the same immutable identity;
manifest or content drift fails visibly. A missing or malformed declaration
fails the deploy bootstrap, and a failure in any entry rolls back every new
registration from that invocation rather than installing a partial catalog.
