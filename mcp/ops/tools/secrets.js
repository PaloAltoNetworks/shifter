// Secrets Manager tools for the shifter-ops MCP server.

import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { EnvSchema, SecretIdSchema } from "../schemas.js";

export function registerSecretsTools(ctx, deps) {
  const { getProfile, aws } = deps;

  registerTool(ctx, {
    name: "list_secrets",
    // Codex review #1201 cycle 3 finding 1: list_secrets returns only
    // metadata (name + lastChanged), no secret material. Classifying
    // it as secret_handle would wrap the metadata JSON into an opaque
    // `shf-secret:<uuid>` handle that the agent has no way to resolve
    // back to a discoverable list of secret IDs — breaking the
    // purpose of the list operation. The data is non-sensitive
    // discovery output, so observability is the correct class.
    klass: "observability",
    description: "List secrets in Secrets Manager",
    schema: { env: EnvSchema },
    handler: async ({ env }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, ["secretsmanager", "list-secrets"]);
        const secrets = result.SecretList.map((s) => ({
          name: s.Name,
          lastChanged: s.LastChangedDate,
        }));
        return ok(JSON.stringify(secrets, null, 2));
      } catch (e) {
        return err(e);
      }
    },
  });

  registerTool(ctx, {
    name: "get_secret",
    klass: "secret_handle",
    description: "Get a secret value from Secrets Manager",
    schema: {
      env: EnvSchema,
      secret_id: SecretIdSchema.describe("Secret name or ARN"),
    },
    handler: async ({ env, secret_id }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "secretsmanager",
          "get-secret-value",
          "--secret-id",
          secret_id,
        ]);
        return ok(result.SecretString || "(binary secret)");
      } catch (e) {
        return err(e);
      }
    },
  });
}
