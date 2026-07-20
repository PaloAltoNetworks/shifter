// AWS command-execution wrappers for the shifter-ops MCP server.
//
// All aws-cli invocations go through these wrappers, which delegate to
// the argv-array helpers in lib.js (governed by ADR-010). Callers MUST
// pass `args` as an array of argv elements — never as a shell string.
// The lib helpers throw TypeError if a string slips through.
//
// `getProfile(env)` binds the env → AWS-profile map read once from the
// process environment, mirroring the module-level behaviour index.js
// had before the #690 modularization.

import { spawn } from "node:child_process";
import {
  REGION,
  getProfile as _getProfile,
  awsJson,
  awsText as awsTextLib,
  buildAwsArgv,
} from "./lib.js";
import { CMD_DESCRIBE_INSTANCES, ARG_INSTANCE_IDS } from "./schemas.js";

export const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

export function getProfile(env) {
  return _getProfile(PROFILES, env);
}

// Spawn a long-running aws-cli process (e.g. an SSM port-forward that
// must stay open). Uses the same argv-array discipline as the
// shared aws()/awsText() helpers so tunnel call sites cannot
// accidentally re-introduce shell-string interpolation.
//
// The command name is the fixed literal "aws" (never user input) and
// argv is an array (no shell), so there is no command-injection path.
// Resolving "aws" from PATH is the same reviewed-safe disposition the
// shared gh/git runners in lib.js already take (S4036): the runtime
// PATH is operator-controlled, and pinning an absolute path would break
// portability across deploy hosts. NOSONAR marks that review.
export function spawnAws(profile, args, options = {}) {
  const argv = buildAwsArgv(args, profile, REGION);
  return spawn("aws", argv, options); // NOSONAR
}

export function aws(profile, args) {
  return awsJson(profile, args);
}

export function awsText(profile, args) {
  return awsTextLib(profile, args);
}

export function getInstancePlatform(profile, instanceId) {
  // `--output text` so the scalar query result is returned as the raw
  // string (`Linux/UNIX`, `Windows`) rather than JSON-quoted
  // (`"Linux/UNIX"`). Without this getSsmDocument() never matches
  // "windows" because the value starts with a `"` instead of `w`.
  return awsText(profile, [
    "ec2",
    CMD_DESCRIBE_INSTANCES,
    ARG_INSTANCE_IDS,
    instanceId,
    "--query",
    "Reservations[0].Instances[0].PlatformDetails",
    "--output",
    "text",
  ]);
}
