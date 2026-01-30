#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { execSync } from "child_process";
import {
  REGION,
  getProfile as _getProfile,
  resolveLogGroup,
  buildInstanceFilters,
} from "./lib.js";

const PROFILES = {
  dev: process.env.PANW_SHIFTER_DEV_PROFILE,
  prod: process.env.PANW_SHIFTER_PROD_PROFILE,
};

function getProfile(env) {
  return _getProfile(PROFILES, env);
}

function aws(profile, args) {
  const cmd = `aws ${args} --profile "${profile}" --region "${REGION}" --output json`;
  return JSON.parse(execSync(cmd, { encoding: "utf-8", timeout: 60000 }));
}

function awsText(profile, args) {
  const cmd = `aws ${args} --profile "${profile}" --region "${REGION}"`;
  return execSync(cmd, { encoding: "utf-8", timeout: 60000 }).trim();
}

function ok(text) {
  return { content: [{ type: "text", text }] };
}

function err(e) {
  return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
}

// --- MCP Server ---

const server = new McpServer({ name: "shifter-aws", version: "1.0.0" });

const EnvSchema = z
  .enum(["dev", "prod"])
  .default("dev")
  .describe("Environment (dev or prod). Defaults to dev.");

// ==========================================================================
// CloudWatch Logs
// ==========================================================================

server.tool(
  "describe_log_streams",
  "List recent log streams for a component or log group. Use component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or a full log group path.",
  {
    env: EnvSchema,
    component: z
      .string()
      .describe(
        "Component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or full log group path"
      ),
    limit: z.number().int().min(1).max(50).default(5).describe("Number of streams to return (default 5)"),
  },
  async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs describe-log-streams --log-group-name "${logGroup}" --order-by LastEventTime --descending --limit ${limit}`
      );
      const streams = result.logStreams.map((s) => ({
        name: s.logStreamName,
        lastEvent: s.lastEventTimestamp
          ? new Date(s.lastEventTimestamp).toISOString()
          : "never",
      }));
      return ok(JSON.stringify(streams, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "get_log_events",
  "Get log events from a specific log stream",
  {
    env: EnvSchema,
    component: z.string().describe("Component shorthand or full log group path"),
    stream_name: z.string().describe("Log stream name"),
    limit: z.number().int().min(1).max(200).default(50).describe("Number of events (default 50)"),
  },
  async ({ env, component, stream_name, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs get-log-events --log-group-name "${logGroup}" --log-stream-name "${stream_name}" --limit ${limit}`
      );
      const lines = result.events.map(
        (e) =>
          `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(lines.join("\n"));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "filter_log_events",
  "Search log events across streams using a CloudWatch filter pattern",
  {
    env: EnvSchema,
    component: z.string().describe("Component shorthand or full log group path"),
    filter_pattern: z.string().describe("CloudWatch filter pattern (e.g. 'error', '\"stack trace\"')"),
    limit: z.number().int().min(1).max(200).default(50).describe("Max events to return (default 50)"),
  },
  async ({ env, component, filter_pattern, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const result = aws(
        profile,
        `logs filter-log-events --log-group-name "${logGroup}" --filter-pattern ${JSON.stringify(filter_pattern)} --limit ${limit}`
      );
      const lines = result.events.map(
        (e) =>
          `[${new Date(e.timestamp).toISOString()}] [${e.logStreamName}] ${e.message}`
      );
      return ok(lines.length > 0 ? lines.join("\n") : "No matching events found.");
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "tail_logs",
  "Tail recent logs for a component (shortcut for describe_streams + get_log_events on the latest stream)",
  {
    env: EnvSchema,
    component: z.string().describe("Component shorthand or full log group path"),
    limit: z.number().int().min(1).max(200).default(50).describe("Number of events (default 50)"),
  },
  async ({ env, component, limit }) => {
    try {
      const profile = getProfile(env);
      const logGroup = resolveLogGroup(component, env);
      const streams = aws(
        profile,
        `logs describe-log-streams --log-group-name "${logGroup}" --order-by LastEventTime --descending --limit 1`
      );
      if (!streams.logStreams || streams.logStreams.length === 0) {
        return ok("No log streams found.");
      }
      const streamName = streams.logStreams[0].logStreamName;
      const result = aws(
        profile,
        `logs get-log-events --log-group-name "${logGroup}" --log-stream-name "${streamName}" --limit ${limit}`
      );
      const lines = result.events.map(
        (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
      );
      return ok(
        `Stream: ${streamName}\n\n${lines.length > 0 ? lines.join("\n") : "No events."}`
      );
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// EC2
// ==========================================================================

server.tool(
  "list_ec2_instances",
  "List EC2 instances, optionally filtered by Name tag pattern",
  {
    env: EnvSchema,
    name_filter: z
      .string()
      .optional()
      .describe("Name tag glob filter (e.g. '*portal*', '*ngfw*')"),
    include_terminated: z
      .boolean()
      .default(false)
      .describe("Include terminated instances (default false)"),
  },
  async ({ env, name_filter, include_terminated }) => {
    try {
      const profile = getProfile(env);
      const filters = buildInstanceFilters({ name_filter, include_terminated });
      const filtersJson = JSON.stringify(JSON.stringify(filters));
      const result = aws(
        profile,
        `ec2 describe-instances --filters ${filtersJson} --query 'Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==\`Name\`].Value|[0],PrivateIp:PrivateIpAddress,Type:InstanceType}'`
      );
      return ok(JSON.stringify(result, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "start_ec2_instance",
  "Start a stopped EC2 instance",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, `ec2 start-instances --instance-ids "${instance_id}"`);
      const state = result.StartingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "stop_ec2_instance",
  "Stop a running EC2 instance",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, `ec2 stop-instances --instance-ids "${instance_id}"`);
      const state = result.StoppingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "terminate_ec2_instance",
  "Terminate an EC2 instance (irreversible)",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
  },
  async ({ env, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ec2 terminate-instances --instance-ids "${instance_id}"`
      );
      const state = result.TerminatingInstances?.[0]?.CurrentState?.Name;
      return ok(`Instance ${instance_id}: ${state}`);
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// ECS
// ==========================================================================

server.tool(
  "list_ecs_tasks",
  "List running ECS tasks in a cluster",
  {
    env: EnvSchema,
    cluster: z
      .string()
      .optional()
      .describe("ECS cluster name (defaults to {env}-portal)"),
  },
  async ({ env, cluster }) => {
    try {
      const profile = getProfile(env);
      const clusterName = cluster || `${env}-portal`;
      const tasks = aws(profile, `ecs list-tasks --cluster "${clusterName}"`);
      if (!tasks.taskArns || tasks.taskArns.length === 0) {
        return ok(`No running tasks in cluster ${clusterName}.`);
      }
      const arns = tasks.taskArns.map((a) => `"${a}"`).join(" ");
      const details = aws(
        profile,
        `ecs describe-tasks --cluster "${clusterName}" --tasks ${arns}`
      );
      const summary = details.tasks.map((t) => ({
        taskId: t.taskArn.split("/").pop(),
        status: t.lastStatus,
        group: t.group,
        startedAt: t.startedAt,
      }));
      return ok(JSON.stringify(summary, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// Secrets Manager
// ==========================================================================

server.tool(
  "list_secrets",
  "List secrets in Secrets Manager",
  { env: EnvSchema },
  async ({ env }) => {
    try {
      const profile = getProfile(env);
      const result = aws(profile, `secretsmanager list-secrets`);
      const secrets = result.SecretList.map((s) => ({
        name: s.Name,
        lastChanged: s.LastChangedDate,
      }));
      return ok(JSON.stringify(secrets, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "get_secret",
  "Get a secret value from Secrets Manager",
  {
    env: EnvSchema,
    secret_id: z.string().describe("Secret name or ARN"),
  },
  async ({ env, secret_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `secretsmanager get-secret-value --secret-id "${secret_id}"`
      );
      return ok(result.SecretString || "(binary secret)");
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// SSM
// ==========================================================================

server.tool(
  "ssm_send_command",
  "Run a shell command on an EC2 instance via SSM",
  {
    env: EnvSchema,
    instance_id: z.string().describe("EC2 instance ID"),
    command: z.string().describe("Shell command to execute"),
  },
  async ({ env, instance_id, command }) => {
    try {
      const profile = getProfile(env);
      const params = JSON.stringify({ commands: [command] });
      const result = aws(
        profile,
        `ssm send-command --instance-ids "${instance_id}" --document-name AWS-RunShellScript --parameters '${params}'`
      );
      const cmdId = result.Command.CommandId;
      return ok(`Command sent. ID: ${cmdId}\nUse ssm_get_command_output to check results.`);
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "ssm_get_command_output",
  "Get the output of a previously sent SSM command",
  {
    env: EnvSchema,
    command_id: z.string().describe("SSM command ID"),
    instance_id: z.string().describe("EC2 instance ID the command was sent to"),
  },
  async ({ env, command_id, instance_id }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `ssm get-command-invocation --command-id "${command_id}" --instance-id "${instance_id}"`
      );
      return ok(
        `Status: ${result.Status}\n\n--- stdout ---\n${result.StandardOutputContent}\n--- stderr ---\n${result.StandardErrorContent}`
      );
    } catch (e) {
      return err(e);
    }
  }
);

// ==========================================================================
// ASG / ELB
// ==========================================================================

server.tool(
  "describe_asg",
  "Show Auto Scaling Group status and instance refreshes",
  {
    env: EnvSchema,
    asg_name: z
      .string()
      .optional()
      .describe("ASG name (defaults to {env}-portal-asg)"),
  },
  async ({ env, asg_name }) => {
    try {
      const profile = getProfile(env);
      const name = asg_name || `${env}-portal-asg`;
      const result = aws(
        profile,
        `autoscaling describe-auto-scaling-groups --auto-scaling-group-names "${name}"`
      );
      const asg = result.AutoScalingGroups[0];
      if (!asg) return ok(`ASG ${name} not found.`);
      const summary = {
        name: asg.AutoScalingGroupName,
        desired: asg.DesiredCapacity,
        min: asg.MinSize,
        max: asg.MaxSize,
        instances: asg.Instances.map((i) => ({
          id: i.InstanceId,
          state: i.LifecycleState,
          health: i.HealthStatus,
        })),
      };
      return ok(JSON.stringify(summary, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

server.tool(
  "describe_target_health",
  "Show health status of targets in a target group",
  {
    env: EnvSchema,
    target_group_arn: z.string().describe("Target group ARN"),
  },
  async ({ env, target_group_arn }) => {
    try {
      const profile = getProfile(env);
      const result = aws(
        profile,
        `elbv2 describe-target-health --target-group-arn "${target_group_arn}"`
      );
      const targets = result.TargetHealthDescriptions.map((t) => ({
        id: t.Target.Id,
        port: t.Target.Port,
        state: t.TargetHealth.State,
        reason: t.TargetHealth.Reason || "",
      }));
      return ok(JSON.stringify(targets, null, 2));
    } catch (e) {
      return err(e);
    }
  }
);

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
