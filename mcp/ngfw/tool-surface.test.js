import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const indexSource = readFileSync(path.join(__dirname, "index.js"), "utf-8");
const securitySource = readFileSync(
  path.join(__dirname, "SECURITY.md"),
  "utf-8",
);

// Exported tools registered on the MCP server. Update when (and only
// when) `index.js` adds or removes a `server.tool(...)` registration.
// A change here without a matching `SECURITY.md` update is rejected by
// the "doc references the live tool surface" assertion below.
const EXPECTED_TOOLS = new Set(["list_ngfws"]);

// Tools that used to live in `mcp/ngfw` (PAN-OS administration via SSH/SSM
// through the portal jump host) and were removed. The security doc must
// not describe these as active capabilities; if mentioned at all, they
// belong under an explicit "Removed administration tools" section so a
// reader cannot mistake them for the current surface.
const REMOVED_TOOLS = ["run_command", "show_system_info", "show_routes"];

// Match a `server.tool(...)` call whose first argument is a static
// string literal in any of the three JavaScript forms: double-quoted,
// single-quoted, or backtick template literal WITHOUT `${...}`
// interpolation. Interpolated template literals are intentionally
// excluded so they trigger the "non-literal registration" guard below.
const TOOL_REGISTRATION_LITERAL = new RegExp(
  // server.tool(  +  string-literal-of-any-quote-style
  String.raw`server\.tool\(\s*(?:"([^"\\]+)"|'([^'\\]+)'|` + "`" +
    String.raw`([^` + "`" + String.raw`$\\]+)` + "`" + String.raw`)`,
  "g",
);

// Match ANY `server.tool(` registration regardless of the first
// argument's shape (literal, identifier, function call, interpolated
// template literal). Used to detect non-literal forms and fail loudly
// so the surface invariant cannot be silently bypassed by a future
// registration like `server.tool(toolName, ...)` or
// `server.tool(`tool_${env}`, ...)`.
const TOOL_REGISTRATION_ANY = /server\.tool\s*\(\s*[^,)]/g;

function extractRegisteredTools(source) {
  const tools = new Set();
  for (const match of source.matchAll(TOOL_REGISTRATION_LITERAL)) {
    tools.add(match[1] ?? match[2] ?? match[3]);
  }
  return tools;
}

function countLiteralRegistrations(source) {
  return [...source.matchAll(TOOL_REGISTRATION_LITERAL)].length;
}

function countAnyRegistrations(source) {
  return [...source.matchAll(TOOL_REGISTRATION_ANY)].length;
}

function quotedFormsOf(name) {
  // Generate the three string-literal forms a tool name can appear in
  // inside `index.js`. The escapes follow JS regex rules; tool names
  // are simple identifiers so no characters in them are regex-special.
  return [`"${name}"`, `'${name}'`, "`" + name + "`"];
}

describe("ngfw MCP tool surface hardening", () => {
  it("keeps instance discovery while removing PAN-OS execution tools", () => {
    assert.ok(
      extractRegisteredTools(indexSource).has("list_ngfws"),
      "index.js must register the `list_ngfws` MCP tool.",
    );
    // Removed tools must not appear as a server.tool registration
    // string-literal in ANY of the three JS quoting forms (double,
    // single, backtick). The class fix from cycle 3 generalizes the
    // earlier double-quote-only assertion.
    for (const tool of REMOVED_TOOLS) {
      for (const quoted of quotedFormsOf(tool)) {
        assert.ok(
          !indexSource.includes(`server.tool(${quoted}`) &&
            !indexSource.includes(`server.tool( ${quoted}`),
          `index.js must not register removed tool \`${tool}\` (in ${quoted} form).`,
        );
      }
    }
  });

  it("does not fetch firewall SSH keys from Secrets Manager", () => {
    assert.doesNotMatch(indexSource, /secretsmanager/);
    assert.doesNotMatch(indexSource, /get-secret-value/);
    assert.doesNotMatch(indexSource, /list-secrets/);
  });

  it("only registers tools via static string literals", () => {
    // Every `server.tool(` invocation must use a static string literal
    // as the tool name so the surface can be enumerated statically.
    // A future registration like `server.tool(toolName, ...)` or
    // `server.tool(`tool_${env}`, ...)` would slip past the
    // EXPECTED_TOOLS set assertion below, defeating the invariant.
    const literalCount = countLiteralRegistrations(indexSource);
    const anyCount = countAnyRegistrations(indexSource);
    assert.strictEqual(
      literalCount,
      anyCount,
      `index.js has ${anyCount} \`server.tool(\` call(s) but only ` +
        `${literalCount} use a static string literal as the tool name. ` +
        "Inline the tool name as a literal or extend the regex in " +
        "`extractRegisteredTools` / the literal-form guard to recognize " +
        "the new shape.",
    );
  });

  it("exports exactly the expected tool set (no extras, no missing)", () => {
    const registered = extractRegisteredTools(indexSource);
    assert.deepStrictEqual(
      registered,
      EXPECTED_TOOLS,
      `index.js registers ${[...registered].join(", ")}; expected ${[...EXPECTED_TOOLS].join(", ")}. ` +
        "Update EXPECTED_TOOLS in this file AND mcp/ngfw/SECURITY.md when " +
        "the tool surface changes.",
    );
  });

  it("SECURITY.md references the tool-surface guard and every live tool", () => {
    assert.match(
      securitySource,
      /tool-surface\.test\.js/,
      "SECURITY.md must name `tool-surface.test.js` so future surface changes " +
        "have a discoverable enforcement seam.",
    );
    for (const tool of EXPECTED_TOOLS) {
      assert.ok(
        securitySource.includes(tool),
        `SECURITY.md must describe the currently-registered tool \`${tool}\`.`,
      );
    }
  });

  it("SECURITY.md does not describe removed tools as active capabilities", () => {
    // Removed tools may be named only inside an explicit "Removed
    // administration tools" section so a reader cannot mistake them for
    // the current surface. Everything before that heading must be silent
    // on them.
    const removedHeadingMatch = securitySource.match(
      /^##\s+Removed administration tools\s*$/m,
    );
    assert.ok(
      removedHeadingMatch,
      "SECURITY.md must include a `## Removed administration tools` " +
        "section that marks the removed PAN-OS tools as historical.",
    );
    const before = securitySource.slice(0, removedHeadingMatch.index);
    for (const tool of REMOVED_TOOLS) {
      assert.ok(
        !before.includes(tool),
        `SECURITY.md mentions removed tool \`${tool}\` before the ` +
          "`Removed administration tools` section, which presents it as " +
          "an active capability. Move the reference under that section.",
      );
    }
  });
});
