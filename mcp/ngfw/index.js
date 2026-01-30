#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { execSync } from "child_process";
import { REGION, getProfile as _getProfile } from "./lib.js";

const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

function getProfile(env) {
  return _getProfile(PROFILES, env);
}

// --- AWS Helpers ---

/**
 * List all EC2 instances with "ngfw" in their Name tag.
 * Returns array of { instanceId, name, state, privateIp, keyName }.
 */
function listNgfwInstances(env) {
  const profile = getProfile(env);
  const raw = execSync(
    `aws ec2 describe-instances ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--filters "Name=tag:Name,Values=*ngfw*" ` +
      `--query 'Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,PrivateIp:PrivateIpAddress,KeyName:KeyName,Name:Tags[?Key==\`Name\`].Value|[0]}' ` +
      `--output json`,
    { encoding: "utf-8", timeout: 30000 }
  );
  return JSON.parse(raw.trim());
}

/**
 * Find a running portal instance to use as SSH jump host.
 */
function findPortalInstance(env) {
  const profile = getProfile(env);
  const instanceId = execSync(
    `aws ec2 describe-instances ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" ` +
      `--query 'Reservations[0].Instances[0].InstanceId' ` +
      `--output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

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

  const secretArn = execSync(
    `aws secretsmanager list-secrets ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--output json`,
    { encoding: "utf-8", timeout: 30000 }
  );

  const secrets = JSON.parse(secretArn.trim());
  const match = secrets.SecretList.find((s) =>
    s.Name.includes(`ngfw/${uuidPrefix}`)
  );
  if (!match) {
    throw new Error(
      `Could not find SSH key secret for key name: ${keyName} (uuid prefix: ${uuidPrefix})`
    );
  }

  const keyContent = execSync(
    `aws secretsmanager get-secret-value ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--secret-id "${match.ARN}" ` +
      `--query 'SecretString' --output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  if (!keyContent) {
    throw new Error("Could not retrieve SSH key content");
  }
  return keyContent;
}

/**
 * Run a PAN-OS CLI command on an NGFW by piping through SSH via the portal
 * instance using SSM send-command.
 */
function runNgfwCommand(env, ngfwIp, sshKey, command) {
  const portalId = findPortalInstance(env);
  const profile = getProfile(env);

  // Build the shell commands to run on the portal via SSM
  const sshKeyJson = JSON.stringify(sshKey);
  const commands = [
    `cat > /tmp/ngfw.pem << 'EOFKEY'`,
    sshKey,
    `EOFKEY`,
    `chmod 600 /tmp/ngfw.pem`,
    `echo ${JSON.stringify(command)} | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 admin@${ngfwIp} 2>&1`,
    `rm -f /tmp/ngfw.pem`,
  ];

  // Send command via SSM
  const sendResult = execSync(
    `aws ssm send-command ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--instance-ids "${portalId}" ` +
      `--document-name AWS-RunShellScript ` +
      `--parameters '${JSON.stringify({ commands })}' ` +
      `--query 'Command.CommandId' --output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  const cmdId = sendResult;

  // Poll for completion (up to 60 seconds)
  let status = "Pending";
  for (let i = 0; i < 30; i++) {
    execSync("sleep 2");
    try {
      status = execSync(
        `aws ssm get-command-invocation ` +
          `--profile "${profile}" --region "${REGION}" ` +
          `--command-id "${cmdId}" ` +
          `--instance-id "${portalId}" ` +
          `--query 'Status' --output text`,
        { encoding: "utf-8", timeout: 30000 }
      ).trim();
    } catch {
      // invocation may not be ready yet
      continue;
    }
    if (status !== "Pending" && status !== "InProgress") break;
  }

  // Get output
  const stdout = execSync(
    `aws ssm get-command-invocation ` +
      `--profile "${profile}" --region "${REGION}" ` +
      `--command-id "${cmdId}" ` +
      `--instance-id "${portalId}" ` +
      `--query 'StandardOutputContent' --output text`,
    { encoding: "utf-8", timeout: 30000 }
  ).trim();

  let stderr = "";
  if (status !== "Success") {
    stderr = execSync(
      `aws ssm get-command-invocation ` +
        `--profile "${profile}" --region "${REGION}" ` +
        `--command-id "${cmdId}" ` +
        `--instance-id "${portalId}" ` +
        `--query 'StandardErrorContent' --output text`,
      { encoding: "utf-8", timeout: 30000 }
    ).trim();
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
      const result = runNgfwCommand(
        env,
        instance.PrivateIp,
        sshKey,
        "show system info"
      );
      return {
        content: [
          {
            type: "text",
            text: `NGFW: ${instance.Name} (${instance.InstanceId})\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`,
          },
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
      const result = runNgfwCommand(
        env,
        instance.PrivateIp,
        sshKey,
        "show routing route"
      );
      return {
        content: [
          {
            type: "text",
            text: `NGFW: ${instance.Name} (${instance.InstanceId})\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`,
          },
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
      const result = runNgfwCommand(env, instance.PrivateIp, sshKey, command);
      return {
        content: [
          {
            type: "text",
            text: `NGFW: ${instance.Name} (${instance.InstanceId})\nCommand: ${command}\nStatus: ${result.status}\n\n${result.stdout}${result.stderr ? `\nErrors:\n${result.stderr}` : ""}`,
          },
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

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
