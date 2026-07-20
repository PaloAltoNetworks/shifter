// S3 object tools and Terraform-state inspection for the shifter-ops
// MCP server.
//
// NOTE: `terraform_state` embeds the operational state-bucket map
// (UUID-suffixed infra/state buckets read at runtime). Those literals
// are covered by the scoped ADR-004-R14 exception in
// docs/adr/exceptions.yaml (paths: mcp/ops/tools/s3.js). Moving that
// map to runtime config is a separate change, out of scope for #690.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { MAX_S3_READ_SIZE, isBinaryContentType } from "../lib.js";
import { EnvSchema } from "../schemas.js";

function listS3BucketsTool({ getProfile, aws }) {
  return {
    name: "list_s3_buckets",
    klass: "observability",
    description:
      "List S3 buckets in the account, optionally filtered by name pattern.",
    schema: {
      env: EnvSchema,
      name_filter: z
        .string()
        .optional()
        .describe("Substring filter for bucket names"),
    },
    handler: async ({ env, name_filter }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, ["s3api", "list-buckets"]);
        let buckets = (result.Buckets || []).map((b) => ({
          name: b.Name,
          created: b.CreationDate,
        }));
        if (name_filter) {
          const lower = name_filter.toLowerCase();
          buckets = buckets.filter((b) => b.name.toLowerCase().includes(lower));
        }
        if (buckets.length === 0) return ok("No buckets found.");
        return ok(JSON.stringify(buckets, null, 2));
      } catch (e) {
        return err(e);
      }
    },
  };
}

function listS3ObjectsTool({ getProfile, aws }) {
  return {
    name: "list_s3_objects",
    klass: "observability",
    // Codex review #1201 cycle 2: an authenticated principal with
    // write access to a bucket the operator inspects can name objects
    // with prompt-injection payloads, so the returned keys are
    // attacker-controlled. Fence the response.
    untrusted_source: "s3",
    description:
      "List objects in an S3 bucket with optional prefix filter. Returns key, size, and last modified.",
    schema: {
      env: EnvSchema,
      bucket: z.string().describe("S3 bucket name"),
      prefix: z.string().optional().describe("Key prefix filter"),
      max_keys: z
        .number()
        .int()
        .min(1)
        .max(1000)
        .default(100)
        .describe("Maximum number of objects to return (default 100, max 1000)"),
    },
    handler: async ({ env, bucket, prefix, max_keys }) => {
      try {
        const profile = getProfile(env);
        const args = [
          "s3api",
          "list-objects-v2",
          "--bucket",
          bucket,
          "--max-items",
          String(max_keys),
        ];
        if (prefix) args.push("--prefix", prefix);
        const result = aws(profile, args);
        const objects = (result.Contents || []).map((o) => ({
          key: o.Key,
          size: o.Size,
          last_modified: o.LastModified,
        }));
        if (objects.length === 0) return ok("No objects found.");
        return ok(JSON.stringify(objects, null, 2));
      } catch (e) {
        return err(e);
      }
    },
  };
}

function getS3ObjectTool({ getProfile, aws, awsText }) {
  return {
    name: "get_s3_object",
    klass: "observability",
    untrusted_source: "s3",
    description:
      "Read the contents of an S3 object. Returns text content for text files, metadata only for binary files. 1MB size limit.",
    schema: {
      env: EnvSchema,
      bucket: z.string().describe("S3 bucket name"),
      key: z.string().describe("S3 object key"),
    },
    handler: async ({ env, bucket, key }) => {
      try {
        const profile = getProfile(env);
        // Check size first
        const head = aws(profile, [
          "s3api",
          "head-object",
          "--bucket",
          bucket,
          "--key",
          key,
        ]);
        const size = head.ContentLength;
        const contentType = head.ContentType || "";

        if (size > MAX_S3_READ_SIZE) {
          return ok(
            JSON.stringify(
              {
                error: "Object too large to read inline",
                size,
                max_size: MAX_S3_READ_SIZE,
                content_type: contentType,
                last_modified: head.LastModified,
              },
              null,
              2,
            ),
          );
        }

        if (isBinaryContentType(contentType)) {
          return ok(
            JSON.stringify(
              {
                message: "Binary file — metadata only",
                size,
                content_type: contentType,
                last_modified: head.LastModified,
              },
              null,
              2,
            ),
          );
        }

        const content = awsText(profile, [
          "s3",
          "cp",
          `s3://${bucket}/${key}`,
          "-",
        ]);
        return ok(content);
      } catch (e) {
        return err(e);
      }
    },
  };
}

function terraformStateTool({ getProfile, awsText }) {
  return {
    name: "terraform_state",
    klass: "observability",
    // Codex review #1201 cycle 2: tfstate is read from caller-selected
    // S3 objects, so resource/module/name strings can be attacker-
    // controlled (e.g. a Range ID that originated as user input flows
    // through to a tag value). Fence the response.
    untrusted_source: "s3",
    description:
      "List resources from a Terraform state file stored in S3. Shows resource types, names, and modules.",
    schema: {
      env: EnvSchema,
      bucket: z.string().optional().describe(
        "S3 bucket containing TF state (auto-detected from env if omitted)",
      ),
      key: z.string().optional().describe(
        "S3 key for the state file (auto-detected from env if omitted)",
      ),
    },
    handler: async ({ env, bucket, key }) => {
      try {
        const profile = getProfile(env);
        const stateBuckets = {
          dev: {
            bucket: "shifter-dev-infra-2080ea59-c141-4021-9ddd-11c77cd0574d",
            key: "global/github-runner/terraform.tfstate",
          },
          prod: {
            bucket: "shifter-infra-9f7d1dc4-7f0c-495b-9c03-624dfd5a8795",
            key: "shifter/prod/terraform.tfstate",
          },
        };
        const defaults = stateBuckets[env] || {};
        const b = bucket || defaults.bucket;
        const k = key || defaults.key;
        if (!b || !k) {
          return err(new Error("Could not determine state bucket/key. Provide bucket and key explicitly."));
        }
        const content = awsText(profile, [
          "s3",
          "cp",
          `s3://${b}/${k}`,
          "-",
        ]);
        const state = JSON.parse(content);
        const resources = (state.resources || []).map((r) => ({
          module: r.module || "(root)",
          type: r.type,
          name: r.name,
          provider: r.provider,
          instances: r.instances?.length || 0,
        }));
        return ok(
          JSON.stringify(
            {
              terraform_version: state.terraform_version,
              serial: state.serial,
              total_resources: resources.length,
              resources,
            },
            null,
            2,
          ),
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

export function registerS3Tools(ctx, deps) {
  registerTool(ctx, listS3BucketsTool(deps));
  registerTool(ctx, listS3ObjectsTool(deps));
  registerTool(ctx, getS3ObjectTool(deps));
  registerTool(ctx, terraformStateTool(deps));
}
