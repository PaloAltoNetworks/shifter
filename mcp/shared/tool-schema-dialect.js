const TOOLS_LIST_METHOD = "tools/list";
const JSON_SCHEMA_DRAFT_2020_12 =
  "https://json-schema.org/draft/2020-12/schema";

const LEGACY_JSON_SCHEMA_DIALECTS = new Set([
  "http://json-schema.org/draft-07/schema#",
  "https://json-schema.org/draft-07/schema#",
]);

function schemaShape(schema) {
  const shape = schema?.shape ?? schema?._def?.shape ?? schema?._zod?.def?.shape;
  return typeof shape === "function" ? shape() : shape;
}

function literalValue(schema) {
  return (
    schema?.value ??
    schema?._def?.value ??
    schema?._def?.values?.[0] ??
    schema?._zod?.def?.value ??
    schema?._zod?.def?.values?.[0]
  );
}

function requestMethod(requestSchema) {
  return literalValue(schemaShape(requestSchema)?.method);
}

export function normalizeJsonSchemaDialect(schema) {
  if (!schema || typeof schema !== "object") {
    return schema;
  }

  if (Array.isArray(schema)) {
    for (const item of schema) {
      normalizeJsonSchemaDialect(item);
    }
    return schema;
  }

  if (LEGACY_JSON_SCHEMA_DIALECTS.has(schema.$schema)) {
    schema.$schema = JSON_SCHEMA_DRAFT_2020_12;
  }

  for (const value of Object.values(schema)) {
    normalizeJsonSchemaDialect(value);
  }
  return schema;
}

export function normalizeToolSchemaDialects(listToolsResult) {
  for (const tool of listToolsResult?.tools ?? []) {
    normalizeJsonSchemaDialect(tool.inputSchema);
    normalizeJsonSchemaDialect(tool.outputSchema);
  }
  return listToolsResult;
}

export function installToolSchemaDialectNormalizer(mcpServer) {
  const protocolServer = mcpServer?.server;
  if (
    !protocolServer ||
    protocolServer.__shifterToolSchemaDialectNormalizerInstalled
  ) {
    return;
  }

  const setRequestHandler = protocolServer.setRequestHandler.bind(protocolServer);
  protocolServer.setRequestHandler = (requestSchema, handler) => {
    if (requestMethod(requestSchema) !== TOOLS_LIST_METHOD) {
      return setRequestHandler(requestSchema, handler);
    }
    return setRequestHandler(requestSchema, async (request, extra) =>
      normalizeToolSchemaDialects(await handler(request, extra))
    );
  };

  Object.defineProperty(
    protocolServer,
    "__shifterToolSchemaDialectNormalizerInstalled",
    {
      value: true,
    }
  );
}
