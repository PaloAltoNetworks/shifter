// Cost & billing tools for the shifter-ops MCP server.
//
// Each tool descriptor is built by its own module-level factory so the
// registrar stays a thin wiring function (keeps every function well
// under the length budget). The factories receive the shared `deps`
// bundle and are pure builders — registration happens in
// `registerCostTools`.

import { z } from "zod";
import { registerTool } from "../policy.js";
import { ok, err } from "../respond.js";
import { EnvSchema } from "../schemas.js";

function costSummaryTool({ getProfile, aws }) {
  return {
    name: "cost_summary",
    klass: "observability",
    description:
      "Get AWS cost summary for a date range, broken down by service. Defaults to last 30 days.",
    schema: {
      env: EnvSchema,
      start_date: z
        .string()
        .optional()
        .describe("Start date YYYY-MM-DD (defaults to 30 days ago)"),
      end_date: z
        .string()
        .optional()
        .describe("End date YYYY-MM-DD (defaults to today)"),
    },
    handler: async ({ env, start_date, end_date }) => {
      try {
        const profile = getProfile(env);
        const end = end_date || new Date().toISOString().slice(0, 10);
        const start =
          start_date ||
          new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
        const result = aws(profile, [
          "ce",
          "get-cost-and-usage",
          "--time-period",
          `Start=${start},End=${end}`,
          "--granularity",
          "MONTHLY",
          "--metrics",
          "BlendedCost",
          "--group-by",
          "Type=DIMENSION,Key=SERVICE",
        ]);
        const periods = result.ResultsByTime || [];
        let total = 0;
        const services = {};
        for (const period of periods) {
          for (const group of period.Groups || []) {
            const svc = group.Keys[0];
            const amount = Number.parseFloat(group.Metrics.BlendedCost.Amount);
            total += amount;
            services[svc] = (services[svc] || 0) + amount;
          }
        }
        const sorted = Object.entries(services)
          .map(([name, amount]) => ({ service: name, amount: `$${amount.toFixed(2)}` }))
          .sort((a, b) => Number.parseFloat(b.amount.slice(1)) - Number.parseFloat(a.amount.slice(1)));
        return ok(
          JSON.stringify(
            { period: { start, end }, total: `$${total.toFixed(2)}`, by_service: sorted },
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

function dailySpendTool({ getProfile, aws }) {
  return {
    name: "daily_spend",
    klass: "observability",
    description: "Show daily AWS spend for the last N days. Useful for spotting spikes.",
    schema: {
      env: EnvSchema,
      days: z
        .number()
        .int()
        .min(1)
        .max(90)
        .default(7)
        .describe("Number of days to show (default 7, max 90)"),
    },
    handler: async ({ env, days }) => {
      try {
        const profile = getProfile(env);
        const end = new Date().toISOString().slice(0, 10);
        const start = new Date(Date.now() - days * 86400000)
          .toISOString()
          .slice(0, 10);
        const result = aws(profile, [
          "ce",
          "get-cost-and-usage",
          "--time-period",
          `Start=${start},End=${end}`,
          "--granularity",
          "DAILY",
          "--metrics",
          "BlendedCost",
        ]);
        const dataPoints = (result.ResultsByTime || []).map((p) => {
          const amount = Number.parseFloat(p.Total.BlendedCost.Amount);
          return {
            date: p.TimePeriod.Start,
            amount: `$${amount.toFixed(2)}`,
          };
        });
        const amounts = dataPoints.map((d) => Number.parseFloat(d.amount.slice(1)));
        const avg = amounts.length > 0 ? amounts.reduce((a, b) => a + b, 0) / amounts.length : 0;
        const total = amounts.reduce((a, b) => a + b, 0);
        return ok(
          JSON.stringify(
            {
              period: { start, end, days },
              total: `$${total.toFixed(2)}`,
              daily_average: `$${avg.toFixed(2)}`,
              daily: dataPoints,
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

export function registerCostTools(ctx, deps) {
  registerTool(ctx, costSummaryTool(deps));
  registerTool(ctx, dailySpendTool(deps));
}
