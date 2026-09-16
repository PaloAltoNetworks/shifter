// Shared Zod request schemas and string-literal constants for the
// shifter-ops MCP tool descriptors.
//
// These moved out of index.js unchanged during the #690 modularization
// so every domain registrar imports the SAME schema objects and shared
// literals rather than re-declaring them (which would fork validation
// behaviour and re-introduce the SonarCloud S1192 duplicated-literal
// findings the constants below were extracted to avoid).

import { z } from "zod";
import { BASE_AMI_TYPES, GCE_IMAGE_TYPES } from "./lib.js";

// SonarCloud S1192: extracted duplicated string literals.
export const CMD_DESCRIBE_INSTANCES = "describe-instances";
export const ARG_INSTANCE_IDS = "--instance-ids";
export const FILTER_RUNNING_INSTANCES =
  "Name=instance-state-name,Values=running";
export const QUERY_FIRST_INSTANCE_ID =
  "Reservations[0].Instances[0].InstanceId";
export const ARG_LOG_GROUP_NAME = "--log-group-name";
export const DESC_COMPONENT = "Component shorthand or full log group path";
export const DESC_EC2_INSTANCE_ID = "EC2 instance ID";
export const DESC_ECS_CLUSTER = "ECS cluster name (defaults to {env}-portal)";
export const MSG_INVALID_CHARACTERS = "Contains invalid characters";

export const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// Input validation patterns — defense in depth on top of argv-array AWS execution
export const Ec2Id = z
  .string()
  .regex(/^i-[0-9a-f]{8,17}$/, "Must be a valid EC2 instance ID");
export const SsmCommandId = z
  .string()
  .regex(
    /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i,
    "Must be a valid SSM command ID (UUID)"
  );
export const SafePath = z
  .string()
  .regex(/^[\w/.:\-[\]#, ]+$/, MSG_INVALID_CHARACTERS);
export const SafeName = z.string().regex(/^[\w.*?-]+$/, MSG_INVALID_CHARACTERS);
export const AmiTypeSchema = z
  .enum(BASE_AMI_TYPES)
  .describe("AMI type (kali, ubuntu, windows, dc, brokenbk)");
export const GceImageTypeSchema = z
  .enum(GCE_IMAGE_TYPES)
  .describe(
    "GCE image type (ubuntu, brokenbk, kali, windows, dc, polaris-vm, dc-prebaked)"
  );
export const GceImageNameSchema = z
  .string()
  .regex(
    /^[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$/,
    "Must be an exact GCE image name",
  );
export const SecretIdSchema = z
  .string()
  .regex(/^[\w/+=.@-]+$/, MSG_INVALID_CHARACTERS);
export const ArnSchema = z
  .string()
  .regex(/^arn:aws[\w:*/.-]+$/, "Must be a valid ARN");
