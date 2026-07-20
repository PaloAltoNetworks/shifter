// CloudWatch Logs tools for the shifter-ops MCP server.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { resolveLogGroup, buildFilterLogEventsArgs } from "../lib.js";
import {
  EnvSchema,
  SafePath,
  ARG_LOG_GROUP_NAME,
  DESC_COMPONENT,
} from "../schemas.js";

function describeLogStreamsTool({ getProfile, aws }) {
  return {
    name: "describe_log_streams",
    klass: "observability",
    description:
      "List recent log streams for a component or log group. Use component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or a full log group path.",
    schema: {
      env: EnvSchema,
      component: SafePath.describe(
        "Component shorthand (portal, provisioner, guacamole-client, guacd, network-firewall, rds) or full log group path"
      ),
      limit: z
        .number()
        .int()
        .min(1)
        .max(50)
        .default(5)
        .describe("Number of streams to return (default 5)"),
    },
    handler: async ({ env, component, limit }) => {
      try {
        const profile = getProfile(env);
        const logGroup = resolveLogGroup(component, env);
        const result = aws(profile, [
          "logs",
          "describe-log-streams",
          ARG_LOG_GROUP_NAME,
          logGroup,
          "--order-by",
          "LastEventTime",
          "--descending",
          "--limit",
          String(limit),
        ]);
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
    },
  };
}

function getLogEventsTool({ getProfile, aws }) {
  return {
    name: "get_log_events",
    klass: "observability",
    untrusted_source: "logs",
    description: "Get log events from a specific log stream",
    schema: {
      env: EnvSchema,
      component: SafePath.describe(DESC_COMPONENT),
      stream_name: SafePath.describe("Log stream name"),
      limit: z
        .number()
        .int()
        .min(1)
        .max(200)
        .default(50)
        .describe("Number of events (default 50)"),
    },
    handler: async ({ env, component, stream_name, limit }) => {
      try {
        const profile = getProfile(env);
        const logGroup = resolveLogGroup(component, env);
        const result = aws(profile, [
          "logs",
          "get-log-events",
          ARG_LOG_GROUP_NAME,
          logGroup,
          "--log-stream-name",
          stream_name,
          "--limit",
          String(limit),
        ]);
        const lines = result.events.map(
          (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
        );
        return ok(lines.join("\n"));
      } catch (e) {
        return err(e);
      }
    },
  };
}

function filterLogEventsTool({ getProfile, aws }) {
  return {
    name: "filter_log_events",
    klass: "observability",
    untrusted_source: "logs",
    description:
      "Search log events across streams using a CloudWatch filter pattern",
    schema: {
      env: EnvSchema,
      component: SafePath.describe(DESC_COMPONENT),
      filter_pattern: z
        .string()
        .describe(
          'CloudWatch filter pattern (e.g. \'error\', \'"stack trace"\')'
        ),
      limit: z
        .number()
        .int()
        .min(1)
        .max(200)
        .default(50)
        .describe("Max events to return (default 50)"),
    },
    handler: async ({ env, component, filter_pattern, limit }) => {
      try {
        const profile = getProfile(env);
        const logGroup = resolveLogGroup(component, env);
        const result = aws(
          profile,
          buildFilterLogEventsArgs({
            logGroup,
            filterPattern: filter_pattern,
            limit,
          })
        );
        const lines = result.events.map(
          (e) =>
            `[${new Date(e.timestamp).toISOString()}] [${e.logStreamName}] ${e.message}`
        );
        return ok(
          lines.length > 0 ? lines.join("\n") : "No matching events found."
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

function tailLogsTool({ getProfile, aws }) {
  return {
    name: "tail_logs",
    klass: "observability",
    untrusted_source: "logs",
    description:
      "Tail recent logs for a component (shortcut for describe_streams + get_log_events on the latest stream)",
    schema: {
      env: EnvSchema,
      component: SafePath.describe(DESC_COMPONENT),
      limit: z
        .number()
        .int()
        .min(1)
        .max(200)
        .default(50)
        .describe("Number of events (default 50)"),
    },
    handler: async ({ env, component, limit }) => {
      try {
        const profile = getProfile(env);
        const logGroup = resolveLogGroup(component, env);
        const streams = aws(profile, [
          "logs",
          "describe-log-streams",
          ARG_LOG_GROUP_NAME,
          logGroup,
          "--order-by",
          "LastEventTime",
          "--descending",
          "--limit",
          "1",
        ]);
        if (!streams.logStreams || streams.logStreams.length === 0) {
          return ok("No log streams found.");
        }
        const streamName = streams.logStreams[0].logStreamName;
        const result = aws(profile, [
          "logs",
          "get-log-events",
          ARG_LOG_GROUP_NAME,
          logGroup,
          "--log-stream-name",
          streamName,
          "--limit",
          String(limit),
        ]);
        const lines = result.events.map(
          (e) => `[${new Date(e.timestamp).toISOString()}] ${e.message}`
        );
        return ok(
          `Stream: ${streamName}\n\n${lines.length > 0 ? lines.join("\n") : "No events."}`
        );
      } catch (e) {
        return err(e);
      }
    },
  };
}

export function registerLogsTools(ctx, deps) {
  registerTool(ctx, describeLogStreamsTool(deps));
  registerTool(ctx, getLogEventsTool(deps));
  registerTool(ctx, filterLogEventsTool(deps));
  registerTool(ctx, tailLogsTool(deps));
}
