/**
 * Configuration schema for mcp-shifter
 * All values are required - no defaults. Server fails to start if missing.
 */

import { z } from 'zod';

export const ConfigSchema = z.object({
  sessions: z.object({
    maxPerUser: z.number().int().positive().describe('Maximum concurrent sessions per user'),
    maxGlobal: z.number().int().positive().describe('Maximum total sessions across all users'),
    logInfoThreshold: z.number().int().positive().describe('Log INFO when global sessions exceed this'),
    logWarnThreshold: z.number().int().positive().describe('Log WARN when global sessions exceed this'),
  }),
  connections: z.object({
    idleTimeoutMs: z.number().int().positive().describe('Close connections with zero sessions after this many ms'),
  }),
});

export type Config = z.infer<typeof ConfigSchema>;

/**
 * Environment variable schema for values that come from environment
 */
export const EnvSchema = z.object({
  // Cognito
  COGNITO_USER_POOL_ID: z.string().min(1),
  COGNITO_CLIENT_ID: z.string().min(1),
  COGNITO_ISSUER: z.string().url(),

  // RDS
  RDS_HOSTNAME: z.string().min(1),
  RDS_PORT: z.string().regex(/^\d+$/).transform(Number).default('5432'),
  RDS_DATABASE: z.string().min(1),
  RDS_USERNAME: z.string().min(1),

  // AWS
  AWS_REGION: z.string().min(1),

  // Server
  PORT: z.string().regex(/^\d+$/).transform(Number).default('3001'),
  CONFIG_PATH: z.string().min(1),

  // Target mode - determines which range columns to query and tool naming
  TARGET_MODE: z.enum(['kali', 'victim']).default('kali'),
});

export type EnvConfig = z.infer<typeof EnvSchema>;
