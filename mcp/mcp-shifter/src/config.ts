/**
 * Configuration loader for mcp-shifter
 * Fails to start if any required value is missing - no hardcoded defaults.
 */

import { readFileSync } from 'fs';
import { ConfigSchema, EnvSchema, type Config, type EnvConfig } from './config-schema.js';

let cachedConfig: Config | null = null;
let cachedEnv: EnvConfig | null = null;

/**
 * Load and validate configuration from JSON file.
 * Throws if file is missing or validation fails.
 */
export function loadConfig(configPath: string): Config {
  if (cachedConfig) {
    return cachedConfig;
  }

  let fileContent: string;
  try {
    fileContent = readFileSync(configPath, 'utf-8');
  } catch (error) {
    throw new Error(
      `Failed to read config file at ${configPath}: ${error instanceof Error ? error.message : 'Unknown error'}. ` +
      'Config file is required - no hardcoded defaults.'
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(fileContent);
  } catch (error) {
    throw new Error(
      `Failed to parse config file at ${configPath}: ${error instanceof Error ? error.message : 'Invalid JSON'}`
    );
  }

  const result = ConfigSchema.safeParse(parsed);
  if (!result.success) {
    const issues = result.error.issues.map(i => `  - ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new Error(
      `Invalid configuration in ${configPath}:\n${issues}\n\n` +
      'All config values are required. See config.example.json for reference.'
    );
  }

  cachedConfig = result.data;
  return cachedConfig;
}

/**
 * Load and validate environment variables.
 * Throws if any required variable is missing.
 */
export function loadEnv(): EnvConfig {
  if (cachedEnv) {
    return cachedEnv;
  }

  const result = EnvSchema.safeParse(process.env);
  if (!result.success) {
    const issues = result.error.issues.map(i => `  - ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new Error(
      `Missing or invalid environment variables:\n${issues}\n\n` +
      'All environment variables are required for mcp-shifter to start.'
    );
  }

  cachedEnv = result.data;
  return cachedEnv;
}

/**
 * Reset cached config (for testing)
 */
export function resetConfigCache(): void {
  cachedConfig = null;
  cachedEnv = null;
  cachedUnifiedConfig = null;
}

/**
 * Unified configuration combining file and environment
 */
export interface UnifiedConfig {
  sessions: Config['sessions'];
  connections: Config['connections'];
  cognito: {
    userPoolId: string;
    clientId: string;
    issuer: string;
  };
  rds: {
    hostname: string;
    port: number;
    database: string;
    username: string;
  };
  aws: {
    region: string;
  };
  server: {
    port: number;
  };
}

let cachedUnifiedConfig: UnifiedConfig | null = null;

/**
 * Get unified configuration.
 * Must call initialize() first to load config file.
 */
export function getConfig(): UnifiedConfig {
  if (cachedUnifiedConfig) {
    return cachedUnifiedConfig;
  }

  if (!cachedConfig) {
    throw new Error('Configuration not initialized. Call initialize() first.');
  }

  const env = loadEnv();

  cachedUnifiedConfig = {
    sessions: cachedConfig.sessions,
    connections: cachedConfig.connections,
    cognito: {
      userPoolId: env.COGNITO_USER_POOL_ID,
      clientId: env.COGNITO_CLIENT_ID,
      issuer: env.COGNITO_ISSUER,
    },
    rds: {
      hostname: env.RDS_HOSTNAME,
      port: env.RDS_PORT,
      database: env.RDS_DATABASE,
      username: env.RDS_USERNAME,
    },
    aws: {
      region: env.AWS_REGION,
    },
    server: {
      port: env.PORT,
    },
  };

  return cachedUnifiedConfig;
}

/**
 * Initialize configuration from file and environment.
 * Must be called before getConfig().
 */
export function initialize(configPath: string): UnifiedConfig {
  loadConfig(configPath);
  return getConfig();
}
