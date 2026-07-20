// ECS task/service tools for the shifter-ops MCP server.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { EnvSchema, SafeName, DESC_ECS_CLUSTER } from "../schemas.js";

function listEcsTasksTool({ getProfile, aws }) {
  return {
    name: "list_ecs_tasks",
    klass: "observability",
    description: "List running ECS tasks in a cluster",
    schema: {
      env: EnvSchema,
      cluster: SafeName.optional().describe(DESC_ECS_CLUSTER),
    },
    handler: async ({ env, cluster }) => {
      try {
        const profile = getProfile(env);
        const clusterName = cluster || `${env}-portal`;
        const tasks = aws(profile, [
          "ecs",
          "list-tasks",
          "--cluster",
          clusterName,
        ]);
        if (!tasks.taskArns || tasks.taskArns.length === 0) {
          return ok(`No running tasks in cluster ${clusterName}.`);
        }
        const details = aws(profile, [
          "ecs",
          "describe-tasks",
          "--cluster",
          clusterName,
          "--tasks",
          ...tasks.taskArns,
        ]);
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
    },
  };
}

function describeEcsServiceTool({ getProfile, aws }) {
  return {
    name: "describe_ecs_service",
    klass: "observability",
    description:
      "Describe an ECS service: task counts, deployment status, load balancers, and recent events.",
    schema: {
      env: EnvSchema,
      service: SafeName.describe("ECS service name"),
      cluster: SafeName.optional().describe(DESC_ECS_CLUSTER),
    },
    handler: async ({ env, service, cluster }) => {
      try {
        const profile = getProfile(env);
        const clusterName = cluster || `${env}-portal`;
        const result = aws(profile, [
          "ecs",
          "describe-services",
          "--cluster",
          clusterName,
          "--services",
          service,
        ]);
        const svc = result.services?.[0];
        if (!svc) return ok(`Service "${service}" not found in cluster ${clusterName}.`);
        const summary = {
          name: svc.serviceName,
          status: svc.status,
          desired: svc.desiredCount,
          running: svc.runningCount,
          pending: svc.pendingCount,
          launch_type: svc.launchType,
          deployments: (svc.deployments || []).map((d) => ({
            id: d.id,
            status: d.status,
            desired: d.desiredCount,
            running: d.runningCount,
            pending: d.pendingCount,
            rollout_state: d.rolloutState,
            created: d.createdAt,
            updated: d.updatedAt,
          })),
          load_balancers: svc.loadBalancers || [],
          events: (svc.events || []).slice(0, 10).map((e) => ({
            at: e.createdAt,
            message: e.message,
          })),
        };
        return ok(JSON.stringify(summary, null, 2));
      } catch (e) {
        return err(e);
      }
    },
  };
}

function restartEcsServiceTool({ getProfile, aws }) {
  return {
    name: "restart_ecs_service",
    klass: "infra_mutation",
    description: "Force a new deployment of an ECS service (rolls all tasks).",
    schema: {
      env: EnvSchema,
      service: SafeName.describe("ECS service name"),
      cluster: SafeName.optional().describe(DESC_ECS_CLUSTER),
    },
    handler: async ({ env, service, cluster }) => {
      try {
        const profile = getProfile(env);
        const clusterName = cluster || `${env}-portal`;
        const result = aws(profile, [
          "ecs",
          "update-service",
          "--cluster",
          clusterName,
          "--service",
          service,
          "--force-new-deployment",
        ]);
        const svc = result.service;
        const deployment = svc.deployments?.find((d) => d.status === "PRIMARY");
        return ok(
          JSON.stringify(
            {
              service: svc.serviceName,
              status: svc.status,
              deployment_id: deployment?.id,
              rollout_state: deployment?.rolloutState,
              desired: svc.desiredCount,
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

export function registerEcsTools(ctx, deps) {
  registerTool(ctx, listEcsTasksTool(deps));
  registerTool(ctx, describeEcsServiceTool(deps));
  registerTool(ctx, restartEcsServiceTool(deps));
}
