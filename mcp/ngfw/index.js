#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  getProfile as _getProfile,
  awsJson,
  awsText,
  buildSsmSendCommandArgs,
  buildNgfwSshCommands,
} from "./lib.js";

const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

function getProfile(env) {
  return _getProfile(PROFILES, env);
}

const AWS_TIMEOUT_MS = 30000;

// --- AWS Helpers ---

/**
 * List all EC2 instances with "ngfw" in their Name tag.
 * Returns array of { InstanceId, Name, State, PrivateIp, KeyName }.
 */
function listNgfwInstances(env) {
  const profile = getProfile(env);
  return awsJson(
    profile,
    [
      "ec2",
      "describe-instances",
      "--filters",
      "Name=tag:Name,Values=*ngfw*",
      "--query",
      "Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,PrivateIp:PrivateIpAddress,KeyName:KeyName,Name:Tags[?Key==`Name`].Value|[0]}",
    ],
    { timeoutMs: AWS_TIMEOUT_MS }
  );
}

/**
 * Find a running portal instance to use as SSH jump host.
 */
function findPortalInstance(env) {
  const profile = getProfile(env);
  const instanceId = awsText(
    profile,
    [
      "ec2",
      "describe-instances",
      "--filters",
      "Name=tag:Name,Values=*portal*",
      "Name=instance-state-name,Values=running",
      "--query",
      "Reservations[0].Instances[0].InstanceId",
      "--output",
      "text",
    ],
    { timeoutMs: AWS_TIMEOUT_MS }
  );

  if (!instanceId || instanceId === "None") {
    throw new Error(`No running portal instance found in ${env}`);
  }
  return instanceId;
}

/**
 * Get the SSH private key for an NGFW from Secrets Manager.
 * Key name format: ngfw-{uuid}, secret name contains ngfw/{uuid}.
 */
function getNgfwSshKey(env, keyName) {
  const profile = getProfile(env);
  const uuidPrefix = keyName.replace(/^ngfw-/, "");

  const secrets = awsJson(profile, ["secretsmanager", "list-secrets"], {
    timeoutMs: AWS_TIMEOUT_MS,
  });

  const match = secrets.SecretList.find((s) =>
    s.Name.includes(`ngfw/${uuidPrefix}`)
  );
  if (!match) {
    throw new Error(
      `Could not find SSH key secret for key name: ${keyName} (uuid prefix: ${uuidPrefix})`
    );
  }

  const keyContent = awsText(
    profile,
    [
      "secretsmanager",
      "get-secret-value",
      "--secret-id",
      match.ARN,
      "--query",
      "SecretString",
      "--output",
      "text",
    ],
    { timeoutMs: AWS_TIMEOUT_MS }
  );

  if (!keyContent) {
    throw new Error("Could not retrieve SSH key content");
  }
  return keyContent;
}

/**
 * Run a PAN-OS CLI command on an NGFW by piping through SSH via the portal
 * instance using SSM send-command. The user-supplied `command` is
 * base64-encoded into the SSM payload by `buildNgfwSshCommands`, so the
 * portal shell never evaluates it (issue #759).
 */
async function runNgfwCommand(env, ngfwIp, sshKey, command) {
  const portalId = findPortalInstance(env);
  const profile = getProfile(env);

  const commands = buildNgfwSshCommands({ sshKey, ngfwIp, command });

  const sendArgs = buildSsmSendCommandArgs({
    instanceId: portalId,
    docName: "AWS-RunShellScript",
    commands,
  });
  const cmdId = awsText(
    profile,
    [...sendArgs, "--query", "Command.CommandId", "--output", "text"],
    { timeoutMs: AWS_TIMEOUT_MS }
  );

  // Poll for completion (up to ~60 seconds). Sleep is pure JS;
  // ADR-010-R1 forbids `execSync("sleep ...")`.
  let status = "Pending";
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      status = awsText(
        profile,
        [
          "ssm",
          "get-command-invocation",
          "--command-id",
          cmdId,
          "--instance-id",
          portalId,
          "--query",
          "Status",
          "--output",
          "text",
        ],
        { timeoutMs: AWS_TIMEOUT_MS }
      );
    } catch (e) {
      // SSM returns InvocationDoesNotExist while the command id is
      // still propagating to the target. Retry that one transient
      // condition; everything else (AccessDenied, throttling, expired
      // creds, timeouts) propagates so the user sees the labeled error
      // from awsExec instead of a generic 60s timeout.
      if (/InvocationDoesNotExist/.test(e.message)) {
        continue;
      }
      throw e;
    }
    if (status !== "Pending" && status !== "InProgress") break;
  }

  if (status === "Pending" || status === "InProgress") {
    throw new Error(
      `SSM command ${cmdId} did not complete within 60s (last status: ${status}). The PAN-OS command may still be running on portal ${portalId}.`
    );
  }

  const stdout = awsText(
    profile,
    [
      "ssm",
      "get-command-invocation",
      "--command-id",
      cmdId,
      "--instance-id",
      portalId,
      "--query",
      "StandardOutputContent",
      "--output",
      "text",
    ],
    { timeoutMs: AWS_TIMEOUT_MS }
  );

  let stderr = "";
  if (status !== "Success") {
    stderr = awsText(
      profile,
      [
        "ssm",
        "get-command-invocation",
        "--command-id",
        cmdId,
        "--instance-id",
        portalId,
        "--query",
        "StandardErrorContent",
        "--output",
        "text",
      ],
      { timeoutMs: AWS_TIMEOUT_MS }
    );
  }

  return { status, stdout, stderr };
}

/**
 * Resolve an NGFW target: find its IP, key, and validate it's running.
 * If instance_id is provided, use that; otherwise pick the first running NGFW.
 */
function resolveNgfw(env, instanceId) {
  const instances = listNgfwInstances(env);
  const running = instances.filter((i) => i.State === "running");

  if (running.length === 0) {
    throw new Error(`No running NGFW instances found in ${env}`);
  }

  let target;
  if (instanceId) {
    target = running.find((i) => i.InstanceId === instanceId);
    if (!target) {
      throw new Error(
        `NGFW instance ${instanceId} not found or not running in ${env}`
      );
    }
  } else {
    target = running[0];
  }

  const sshKey = getNgfwSshKey(env, target.KeyName);
  return { instance: target, sshKey };
}

// --- MCP Server ---

const server = new McpServer({
  name: "shifter-ngfw",
  version: "1.0.0",
});

const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// Tool: list_ngfws
server.tool(
  "list_ngfws",
  "List all EC2 instances with 'ngfw' in their Name tag, showing instance ID, name, state, and private IP",
  { env: EnvSchema },
  async ({ env }) => {
    try {
      const instances = listNgfwInstances(env);
      if (instances.length === 0) {
        return {
          content: [
            { type: "text", text: `No NGFW instances found in ${env}.` },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: JSON.stringify(instances, null, 2) },
        ],
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Tool: show_system_info
server.tool(
  "show_system_info",
  "Run 'show system info' on an NGFW to get its PAN-OS version, uptime, and general status",
  {
    env: EnvSchema,
    instance_id: z
      .string()
      .optional()
      .describe(
        "EC2 instance ID of the NGFW. If omitted, uses the first running NGFW."
      ),
  },
  async ({ env, instance_id }) => {
    try {
      const { instance, sshKey } = resolveNgfw(env, instance_id);
      const result = await runNgfwCommand(
        env,
        instance.PrivateIp,
        sshKey,
        "show system info"
      );
      const text = `NGFW: ${instance.Name} (${instance.InstanceId})\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`;
      return {
        content: [{ type: "text", text }],
        // Surface non-Success SSM status (Failed, Cancelled,
        // TimedOut, Incomplete) as an MCP error so callers do not
        // see a "successful" tool response for a failed PAN-OS call.
        isError: result.status !== "Success",
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Tool: show_routes
server.tool(
  "show_routes",
  "Show the routing table on an NGFW, including subnet routes added during range provisioning",
  {
    env: EnvSchema,
    instance_id: z
      .string()
      .optional()
      .describe(
        "EC2 instance ID of the NGFW. If omitted, uses the first running NGFW."
      ),
  },
  async ({ env, instance_id }) => {
    try {
      const { instance, sshKey } = resolveNgfw(env, instance_id);
      const result = await runNgfwCommand(
        env,
        instance.PrivateIp,
        sshKey,
        "show routing route"
      );
      const text = `NGFW: ${instance.Name} (${instance.InstanceId})\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`;
      return {
        content: [{ type: "text", text }],
        isError: result.status !== "Success",
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Tool: run_command
server.tool(
  "run_command",
  "Run an arbitrary PAN-OS CLI command on an NGFW via SSH through the portal instance",
  {
    env: EnvSchema,
    command: z.string().describe("The PAN-OS CLI command to execute (e.g. 'show interface all', 'show routing route')"),
    instance_id: z
      .string()
      .optional()
      .describe(
        "EC2 instance ID of the NGFW. If omitted, uses the first running NGFW."
      ),
  },
  async ({ env, command, instance_id }) => {
    try {
      const { instance, sshKey } = resolveNgfw(env, instance_id);
      const result = await runNgfwCommand(env, instance.PrivateIp, sshKey, command);
      const text = `NGFW: ${instance.Name} (${instance.InstanceId})\nCommand: ${command}\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`;
      return {
        content: [{ type: "text", text }],
        isError: result.status !== "Success",
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `Error: ${err.message}` }],
        isError: true,
      };
    }
  }
);

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
