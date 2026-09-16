# In-box environment-pack bootstrap seed

`manifest.yaml` declares the scenario packs registered into the tenant by
default (an in-box bootstrap seed, not a BigRAE-shipped distribution catalog).

Per ADR-053/ADR-034, the in-box seed is **not** loaded through a privileged
code path. The bootstrap (`cms.scenarios.inbox.register_inbox_packs`, invoked by
the `bootstrap_inbox_catalog` management command) registers each manifest entry
through the same `cms.services.register_pack` service an operator uses via the
API or the `register_pack` CLI. The seed is dogfooded through the
uniform, entitlement-blind ingestion boundary.

`manifest.yaml` declares the in-box bootstrap seed. Add one entry per
shipped pack as they land; the entry shape matches the operator registration
request (see the example in `manifest.yaml`). Packs themselves are validated as
foreign input at registration against the `raes-env-packs` contract, and
their advertised digest must match the exact associated-artifact inventory.
Bootstrap retries are service-level no-ops only for the same immutable identity;
manifest or content drift fails visibly. A missing or malformed declaration
fails the deploy bootstrap, and a failure in any entry rolls back every new
registration from that invocation rather than installing a partial batch.
