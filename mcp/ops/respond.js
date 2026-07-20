// MCP response envelopes shared by every ops tool handler.
//
// `ok`/`err` are the common success / error content shapes the whole
// server returns; keeping them in one module lets every domain
// registrar format responses identically without re-declaring the
// literal shape. `err(e)` intentionally surfaces `e.message` unchanged
// — narrowing that is a separate compatibility/security decision (see
// docs/architecture/mcp-ops-modularization-preflight-690.md), not a
// per-domain concern.

export function ok(text) {
  return { content: [{ type: "text", text }] };
}

export function err(e) {
  return {
    content: [{ type: "text", text: `Error: ${e.message}` }],
    isError: true,
  };
}
