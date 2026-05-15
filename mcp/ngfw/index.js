#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  getProfile as _getProfile,
  awsJson,
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

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
