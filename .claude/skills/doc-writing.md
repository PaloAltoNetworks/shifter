# Documentation Writing Style

## Voice

- Terse. No filler words.
- Declarative statements. Not "This section describes..." - just state the facts.
- Technical audience assumed. No hand-holding.
- Zero marketing language or superlatives.

## Structure

- Lead with a one-line summary (no preamble).
- Use tables for structured data (components, decisions, mappings).
- Use mermaid diagrams for relationships - keep them minimal.
- Use bullet lists for configurations or short enumerations.
- Subsections only when there's a clear category break.

## Content

- Document what exists, not what might exist.
- Separate facts from decisions. Facts go in descriptive sections; rationale goes in Design Decisions.
- Include file paths and code references where relevant.
- Note legacy names or technical debt with inline annotations (e.g., `*footnote`).
- Keep abstraction level consistent within a document.

## Formatting

- Headers create hierarchy, not emphasis.
- Bold for element names in tables.
- Backticks for paths, app names, code identifiers.
- No emojis.
- No trailing fluff paragraphs.

## Examples

shifter/documentation/docs/architecture.md