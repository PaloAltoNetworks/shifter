# File Headers (ADR-015)

Source files in this repository carry an SPDX-formatted file header
identifying copyright and license. The format is the
[SPDX REUSE specification](https://reuse.software/spec-3.3/), which is
machine-parsable and language-neutral.

## Canonical header text

Two lines, in order:

```
SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
SPDX-License-Identifier: MIT
```

Year on the `SPDX-FileCopyrightText` line is the calendar year of the
first publication of the work. It does not advance every year; the
license itself in `LICENSE` is the authoritative legal artifact.

## Per-language comment syntax

Each language uses its own comment form so the header is inert at
runtime / render time.

| Language / format | Comment shape |
|---|---|
| Python | `# ` line prefix |
| JavaScript / TypeScript / CSS | `// ` line prefix (or `/* ... */` block) |
| Shell (`.sh`) | `# ` line prefix, AFTER the `#!/usr/bin/env bash` shebang |
| PowerShell (`.ps1`) | `# ` line prefix |
| Django HTML templates | `{# ... #}` server-side comment (NOT `<!-- -->`, which leaks to the client) |
| YAML / TOML | `# ` line prefix |
| Terraform (`.tf`) | `# ` line prefix |
| Dockerfile | `# ` line prefix |
| Markdown | Not required (prose, not source) |

## Examples

Python:
```python
# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT

from foo import bar
```

Django template:
```
{# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc. #}
{# SPDX-License-Identifier: MIT #}
{% extends "base.html" %}
...
```

Shell script with shebang:
```bash
#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT

set -euo pipefail
```

## Enforcement

| Surface | Mechanism |
|---|---|
| Django HTML templates (`shifter/shifter_platform/templates/**/*.html`) | `sonar.html.fileHeader` in `sonar-project.properties` drives SonarCloud's `Web:HeaderCheck` rule. The configured value is the literal two-line header. |
| Other languages | Adopted incrementally per language as the repository's tooling catches up. New files MUST carry the header; legacy files are updated in batched cleanups. |

The literal header text lives in exactly two places:

- `LICENSE` (the legal artifact)
- `sonar-project.properties` (`sonar.html.fileHeader`)

Changes to the header — copyright year roll-forward, organization
rename, license switch — are made in those two places and then
mechanically applied across affected source files in a single change.

## Why SPDX

- Machine-readable. Tools like REUSE, ScanCode, and ClearlyDefined
  consume SPDX headers directly without per-project rules.
- Single source of license truth. The `SPDX-License-Identifier` line
  matches a [SPDX license identifier](https://spdx.org/licenses/);
  legal review can verify with one comparison.
- Stable across decades of OSS practice; not specific to any one
  ecosystem.

## Why Django `{# #}` for HTML

`<!-- -->` HTML comments render to the client in the response body.
Django's `{# ... #}` is stripped at template-compile time and never
reaches the user-agent. Server-side templates therefore use Django
comments so the copyright statement remains a development-time
artifact and does not bloat every HTML response.
