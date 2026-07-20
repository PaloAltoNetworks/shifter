// SSM command tools, the dev portal test tunnel, and the Django
// manage.py wrapper for the shifter-ops MCP server.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import {
  getSsmDocument,
  buildSsmSendCommandArgs,
  validateManageCommand,
  buildRunManageArgs,
} from "../lib.js";
import {
  EnvSchema,
  Ec2Id,
  SsmCommandId,
  CMD_DESCRIBE_INSTANCES,
  FILTER_RUNNING_INSTANCES,
  QUERY_FIRST_INSTANCE_ID,
  DESC_EC2_INSTANCE_ID,
} from "../schemas.js";

function ssmSendCommandTool({ getProfile, aws, getInstancePlatform }) {
  return {
    name: "ssm_send_command",
    klass: "ssm_arbitrary",
    untrusted_inputs: ["command"],
    description:
      "Run a command on an EC2 instance via SSM. Auto-detects OS to use the correct shell (bash for Linux, PowerShell for Windows).",
    schema: {
      env: EnvSchema,
      instance_id: Ec2Id.describe(DESC_EC2_INSTANCE_ID),
      command: z
        .string()
        .describe("Command to execute (shell for Linux, PowerShell for Windows)"),
    },
    handler: async ({ env, instance_id, command }) => {
      try {
        const profile = getProfile(env);
        const platform = getInstancePlatform(profile, instance_id);
        const docName = getSsmDocument(platform);
        const result = aws(
          profile,
          buildSsmSendCommandArgs({
            instanceId: instance_id,
            docName,
            commands: [command],
          })
        );
        const cmdId = result.Command.CommandId;
        return ok(
          `Command sent (${docName}). ID: ${cmdId}\nUse ssm_get_command_output to check results.`
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

function ssmGetCommandOutputTool({ getProfile, aws }) {
  return {
    name: "ssm_get_command_output",
    klass: "ssm_arbitrary",
    untrusted_source: "ssm_stdout",
    description: "Get the output of a previously sent SSM command",
    schema: {
      env: EnvSchema,
      command_id: SsmCommandId.describe("SSM command ID"),
      instance_id: Ec2Id.describe("EC2 instance ID the command was sent to"),
    },
    handler: async ({ env, command_id, instance_id }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "ssm",
          "get-command-invocation",
          "--command-id",
          command_id,
          "--instance-id",
          instance_id,
        ]);
        return ok(
          `Status: ${result.Status}\n\n--- stdout ---\n${result.StandardOutputContent}\n--- stderr ---\n${result.StandardErrorContent}`
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

function startPortalTestTunnelTool({ startPortalTestTunnel }) {
  return {
    name: "start_portal_test_tunnel",
    klass: "dev_bypass_tunnel",
    description:
      "Start SSM tunnel to dev portal for testing. Enables dev_login access bypassing Cognito/MFA. Returns local URL.",
    schema: {
      env: z.literal("dev").describe("Environment (only 'dev' allowed)"),
      local_port: z
        .number()
        .int()
        .min(1024)
        .max(65535)
        .optional()
        .describe("Local port (default: 8000)"),
    },
    handler: async ({ env, local_port = 8000 }) => {
      try {
        const result = await startPortalTestTunnel(env, local_port);
        if (result.kind === "already-running") {
          return ok(
            `Tunnel already running on port ${result.port}. Access at http://localhost:${result.port}/dev-login/`
          );
        }
        return ok(
          `Portal test tunnel started!\n\n` +
          `Access at: http://localhost:${result.port}/dev-login/\n\n` +
          `NOTES:\n` +
          `- Bypasses Cognito/MFA (dev_login checks ENVIRONMENT='development')\n` +
          `- If 400 error, ensure ALLOWED_HOSTS includes 'localhost' in dev\n` +
          `- Use stop_portal_test_tunnel when done\n` +
          `- Stays active until stopped or MCP restart`
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

function stopPortalTestTunnelTool({ stopPortalTestTunnel }) {
  return {
    name: "stop_portal_test_tunnel",
    klass: "dev_bypass_tunnel",
    description: "Stop SSM tunnel to dev portal",
    schema: {
      env: z.literal("dev").describe("Environment (only 'dev' allowed)"),
    },
    handler: async ({ env }) => {
      try {
        const result = stopPortalTestTunnel(env);
        if (result.kind === "not-running") {
          return ok("No tunnel running");
        }
        return ok(`Portal test tunnel stopped (was on port ${result.port})`);
      } catch (e) {
        return err(e);
      }
    },
  };
}

function runManageCommandTool({ getProfile, aws, awsText }) {
  return {
    name: "run_manage_command",
    klass: "ssm_named",
    untrusted_inputs: ["command"],
    description:
      "Run a Django manage.py command on the portal container via SSM. Only whitelisted read-only commands are allowed: check, showmigrations, diffsettings, inspectdb, dbshell, clearsessions, collectstatic, show_urls.",
    schema: {
      env: EnvSchema,
      command: z
        .string()
        .describe("Management command and arguments (e.g. 'showmigrations', 'check --deploy')"),
      instance_id: Ec2Id.optional().describe(
        "Portal EC2 instance ID (auto-detected if omitted)",
      ),
    },
    handler: async ({ env, command, instance_id }) => {
      try {
        const commandParts = validateManageCommand(command);
        const profile = getProfile(env);

        // Auto-detect portal instance if not provided
        let targetId = instance_id;
        if (!targetId) {
          targetId = awsText(profile, [
            "ec2",
            CMD_DESCRIBE_INSTANCES,
            "--filters",
            "Name=tag:Name,Values=*portal*",
            FILTER_RUNNING_INSTANCES,
            "--query",
            QUERY_FIRST_INSTANCE_ID,
            "--output",
            "text",
          ]);
          if (!targetId || targetId === "None") {
            return err(new Error(`No running portal instance found in ${env}`));
          }
        }

        const result = aws(
          profile,
          buildRunManageArgs({ targetId, commandParts })
        );
        const cmdId = result.Command.CommandId;
        // Echo the normalized (validated) command, never the raw input.
        const normalizedCommand = commandParts.join(" ");
        return ok(
          `Command sent: manage.py ${normalizedCommand}\nInstance: ${targetId}\nCommand ID: ${cmdId}\nUse ssm_get_command_output to check results.`,
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

export function registerSsmTools(ctx, deps) {
  registerTool(ctx, ssmSendCommandTool(deps));
  registerTool(ctx, ssmGetCommandOutputTool(deps));
  registerTool(ctx, startPortalTestTunnelTool(deps));
  registerTool(ctx, stopPortalTestTunnelTool(deps));
  registerTool(ctx, runManageCommandTool(deps));
}
