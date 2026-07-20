// GitHub Actions image build/promote tools for the shifter-ops MCP
// server: AMI (issue #411) and GCE guest images (issue #505,
// PLAT-001.10). The workflow-dispatch mechanics live in
// github-actions.js (injected via deps).

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { PROMOTE_AMI_REF, PROMOTE_GCE_IMAGE_REF } from "../lib.js";
import { AmiTypeSchema, GceImageTypeSchema, SafePath } from "../schemas.js";

function registerBuildAmi(ctx, { triggerAmiWorkflow }) {
  registerTool(ctx, {
    name: "build_ami",
    klass: "infra_mutation",
    description:
      "Trigger packer.yml to build an AMI in dev (equivalent to ./scripts/ami.sh -b <type>). Requires GH_TOKEN or GITHUB_TOKEN.",
    schema: {
      ami_type: AmiTypeSchema,
      ref: SafePath.optional().describe(
        "Protected branch to build from (dev or main; default dev). Non-protected refs are rejected (#1656).",
      ),
    },
    handler: async ({ ami_type, ref }) => {
      try {
        return ok(
          triggerAmiWorkflow({
            workflow: "packer.yml",
            ami_type,
            ref,
            actionsPath: "packer.yml",
          }),
        );
      } catch (e) {
        return err(e);
      }
    },
  });
}

function registerPromoteAmi(ctx, { triggerAmiWorkflow }) {
  registerTool(ctx, {
    name: "promote_ami",
    klass: "infra_mutation",
    description:
      "Trigger packer-promote.yml to promote an AMI to prod (equivalent to ./scripts/ami.sh -p <type>). Requires GH_TOKEN or GITHUB_TOKEN.",
    schema: {
      env: z
        .literal("prod")
        .describe("Must be prod — promotion updates production AMIs."),
      ami_type: AmiTypeSchema,
    },
    handler: async ({ ami_type }) => {
      try {
        return ok(
          triggerAmiWorkflow({
            workflow: "packer-promote.yml",
            ami_type,
            ref: PROMOTE_AMI_REF,
            actionsPath: "packer-promote.yml",
          }),
        );
      } catch (e) {
        return err(e);
      }
    },
  });
}

function registerBuildGceImage(ctx, { triggerGceImageWorkflow }) {
  registerTool(ctx, {
    name: "build_gce_image",
    klass: "infra_mutation",
    description:
      "Trigger packer-gcp.yml to build a GCE guest image in dev (the GCP analog of build_ami). Requires GH_TOKEN or GITHUB_TOKEN.",
    schema: {
      image_type: GceImageTypeSchema,
      ref: SafePath.optional().describe(
        "Branch to build from (default: current git branch, else dev)",
      ),
    },
    handler: async ({ image_type, ref }) => {
      try {
        return ok(
          triggerGceImageWorkflow({
            workflow: "packer-gcp.yml",
            image_type,
            ref,
            actionsPath: "packer-gcp.yml",
          }),
        );
      } catch (e) {
        return err(e);
      }
    },
  });
}

function registerPromoteGceImage(ctx, { triggerGceImageWorkflow }) {
  registerTool(ctx, {
    name: "promote_gce_image",
    klass: "infra_mutation",
    description:
      "Trigger packer-gcp-promote.yml to promote a GCE image to prod (the GCP analog of promote_ami). Requires GH_TOKEN or GITHUB_TOKEN.",
    schema: {
      env: z
        .literal("prod")
        .describe("Must be prod — promotion updates production GCE images."),
      image_type: GceImageTypeSchema,
    },
    handler: async ({ image_type }) => {
      try {
        return ok(
          triggerGceImageWorkflow({
            workflow: "packer-gcp-promote.yml",
            image_type,
            ref: PROMOTE_GCE_IMAGE_REF,
            actionsPath: "packer-gcp-promote.yml",
          }),
        );
      } catch (e) {
        return err(e);
      }
    },
  });
}

export function registerImagesTools(ctx, deps) {
  registerBuildAmi(ctx, deps);
  registerPromoteAmi(ctx, deps);
  registerBuildGceImage(ctx, deps);
  registerPromoteGceImage(ctx, deps);
}
