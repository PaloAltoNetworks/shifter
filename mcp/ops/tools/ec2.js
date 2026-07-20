// EC2 instance tools plus Auto Scaling Group / ELB target-health
// observability for the shifter-ops MCP server.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { buildInstanceFilters } from "../lib.js";
import {
  EnvSchema,
  Ec2Id,
  SafeName,
  ArnSchema,
  CMD_DESCRIBE_INSTANCES,
  ARG_INSTANCE_IDS,
  DESC_EC2_INSTANCE_ID,
} from "../schemas.js";

function listEc2InstancesTool({ getProfile, aws }) {
  return {
    name: "list_ec2_instances",
    klass: "observability",
    description: "List EC2 instances, optionally filtered by Name tag pattern",
    schema: {
      env: EnvSchema,
      name_filter: SafeName.optional().describe(
        "Name tag glob filter (e.g. '*portal*', '*ngfw*')"
      ),
      include_terminated: z
        .boolean()
        .default(false)
        .describe("Include terminated instances (default false)"),
    },
    handler: async ({ env, name_filter, include_terminated }) => {
      try {
        const profile = getProfile(env);
        const filters = buildInstanceFilters({ name_filter, include_terminated });
        const result = aws(profile, [
          "ec2",
          CMD_DESCRIBE_INSTANCES,
          "--filters",
          JSON.stringify(filters),
          "--query",
          "Reservations[].Instances[].{InstanceId:InstanceId,State:State.Name,Name:Tags[?Key==`Name`].Value|[0],PrivateIp:PrivateIpAddress,Type:InstanceType}",
        ]);
        return ok(JSON.stringify(result, null, 2));
      } catch (e) {
        return err(e);
      }
    },
  };
}

function startEc2InstanceTool({ getProfile, aws }) {
  return {
    name: "start_ec2_instance",
    klass: "infra_mutation",
    description: "Start a stopped EC2 instance",
    schema: {
      env: EnvSchema,
      instance_id: Ec2Id.describe(DESC_EC2_INSTANCE_ID),
    },
    handler: async ({ env, instance_id }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "ec2",
          "start-instances",
          ARG_INSTANCE_IDS,
          instance_id,
        ]);
        const state = result.StartingInstances?.[0]?.CurrentState?.Name;
        return ok(`Instance ${instance_id}: ${state}`);
      } catch (e) {
        return err(e);
      }
    },
  };
}

function stopEc2InstanceTool({ getProfile, aws }) {
  return {
    name: "stop_ec2_instance",
    klass: "infra_mutation",
    description: "Stop a running EC2 instance",
    schema: {
      env: EnvSchema,
      instance_id: Ec2Id.describe(DESC_EC2_INSTANCE_ID),
    },
    handler: async ({ env, instance_id }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "ec2",
          "stop-instances",
          ARG_INSTANCE_IDS,
          instance_id,
        ]);
        const state = result.StoppingInstances?.[0]?.CurrentState?.Name;
        return ok(`Instance ${instance_id}: ${state}`);
      } catch (e) {
        return err(e);
      }
    },
  };
}

function terminateEc2InstanceTool({ getProfile, aws }) {
  return {
    name: "terminate_ec2_instance",
    klass: "infra_mutation",
    description: "Terminate an EC2 instance (irreversible)",
    schema: {
      env: EnvSchema,
      instance_id: Ec2Id.describe(DESC_EC2_INSTANCE_ID),
    },
    handler: async ({ env, instance_id }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "ec2",
          "terminate-instances",
          ARG_INSTANCE_IDS,
          instance_id,
        ]);
        const state =
          result.TerminatingInstances?.[0]?.CurrentState?.Name;
        return ok(`Instance ${instance_id}: ${state}`);
      } catch (e) {
        return err(e);
      }
    },
  };
}

function describeAsgTool({ getProfile, aws }) {
  return {
    name: "describe_asg",
    klass: "observability",
    description: "Show Auto Scaling Group status and instance refreshes",
    schema: {
      env: EnvSchema,
      asg_name: SafeName.optional().describe(
        "ASG name (defaults to {env}-portal-asg)"
      ),
    },
    handler: async ({ env, asg_name }) => {
      try {
        const profile = getProfile(env);
        const name = asg_name || `${env}-portal-asg`;
        const result = aws(profile, [
          "autoscaling",
          "describe-auto-scaling-groups",
          "--auto-scaling-group-names",
          name,
        ]);
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
    },
  };
}

function describeTargetHealthTool({ getProfile, aws }) {
  return {
    name: "describe_target_health",
    klass: "observability",
    description: "Show health status of targets in a target group",
    schema: {
      env: EnvSchema,
      target_group_arn: ArnSchema.describe("Target group ARN"),
    },
    handler: async ({ env, target_group_arn }) => {
      try {
        const profile = getProfile(env);
        const result = aws(profile, [
          "elbv2",
          "describe-target-health",
          "--target-group-arn",
          target_group_arn,
        ]);
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
    },
  };
}

export function registerEc2Tools(ctx, deps) {
  registerTool(ctx, listEc2InstancesTool(deps));
  registerTool(ctx, startEc2InstanceTool(deps));
  registerTool(ctx, stopEc2InstanceTool(deps));
  registerTool(ctx, terminateEc2InstanceTool(deps));
  registerTool(ctx, describeAsgTool(deps));
  registerTool(ctx, describeTargetHealthTool(deps));
}
