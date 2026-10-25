---
applyTo: *.*
---

Always review for secure coding best practices in addition to other code review.
Always ensure modern coding practices and patterns are used.
Honor the ADR guard in `scripts/adr_guard/adr_guard.py` and the repo-local policy in `AGENTS.md`.
If you change guardrail files or architecture rules, update the ADR docs in `docs/adr/` or `docs/technical/dev/adr-enforcement.md` in the same change.
Private scenario content and executable adapters belong in their owning repositories. Review core changes for scenario-specific branches, scripts, image recipes, and infrastructure. Public issues, PRs, review records, and documentation must use synthetic examples without private pack names, repository locations, domains, topology, or answers. Historical disclosure does not authorize repeating private details. Follow the private-scenario boundary in `AGENTS.md`.
