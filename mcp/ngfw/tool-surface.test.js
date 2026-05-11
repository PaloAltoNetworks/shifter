import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const indexSource = readFileSync(path.join(__dirname, "index.js"), "utf-8");

describe("ngfw MCP tool surface hardening", () => {
  it("keeps instance discovery while removing PAN-OS execution tools", () => {
    assert.match(indexSource, /"list_ngfws"/);
    assert.doesNotMatch(indexSource, /"run_command"/);
    assert.doesNotMatch(indexSource, /"show_system_info"/);
    assert.doesNotMatch(indexSource, /"show_routes"/);
  });

  it("does not fetch firewall SSH keys from Secrets Manager", () => {
    assert.doesNotMatch(indexSource, /secretsmanager/);
    assert.doesNotMatch(indexSource, /get-secret-value/);
    assert.doesNotMatch(indexSource, /list-secrets/);
  });
});
