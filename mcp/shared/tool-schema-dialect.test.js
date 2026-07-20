import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  installToolSchemaDialectNormalizer,
  normalizeJsonSchemaDialect,
} from "./tool-schema-dialect.js";

const LEGACY_DRAFT_07 = "http://json-schema.org/draft-07/schema#";
const DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema";

describe("tool schema dialect normalization", () => {
  it("rewrites legacy draft-07 schema declarations recursively", () => {
    const schema = {
      $schema: LEGACY_DRAFT_07,
      type: "object",
      properties: {
        nested: {
          $schema: LEGACY_DRAFT_07,
          type: "string",
        },
      },
    };

    normalizeJsonSchemaDialect(schema);

    assert.equal(schema.$schema, DRAFT_2020_12);
    assert.equal(schema.properties.nested.$schema, DRAFT_2020_12);
  });

  it("normalizes only tools/list handler results", async () => {
    const protocolServer = {
      setRequestHandler(requestSchema, handler) {
        this.requestSchema = requestSchema;
        this.handler = handler;
      },
    };

    installToolSchemaDialectNormalizer({ server: protocolServer });
    protocolServer.setRequestHandler(
      { shape: { method: { value: "tools/list" } } },
      async () => ({
        tools: [
          {
            name: "example",
            inputSchema: { $schema: LEGACY_DRAFT_07, type: "object" },
            outputSchema: { $schema: LEGACY_DRAFT_07, type: "object" },
          },
        ],
      })
    );

    const result = await protocolServer.handler({}, {});
    assert.equal(result.tools[0].inputSchema.$schema, DRAFT_2020_12);
    assert.equal(result.tools[0].outputSchema.$schema, DRAFT_2020_12);

    protocolServer.setRequestHandler(
      { shape: { method: { value: "tools/call" } } },
      async () => ({ $schema: LEGACY_DRAFT_07 })
    );

    const nonListResult = await protocolServer.handler({}, {});
    assert.equal(nonListResult.$schema, LEGACY_DRAFT_07);
  });
});
