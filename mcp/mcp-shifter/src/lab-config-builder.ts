/**
 * Dynamic LabConfig builder
 *
 * Builds LabConfig at session creation time from:
 * - Range data from RDS (target IP, instance ID based on TARGET_MODE)
 * - SSH private key from Secrets Manager
 */

import type { LabConfig } from 'aptl-mcp-common';
import type { RangeRecord } from './types.js';
import { getSshPrivateKey } from './secrets.js';
import { logger } from './logger.js';
import { getConfig, type TargetMode } from './config.js';

/**
 * Target-specific configuration for LabConfig building.
 * Controls tool naming, SSH user, and descriptions.
 */
const TARGET_CONFIG: Record<TargetMode, {
  serverName: string;
  toolPrefix: string;
  targetName: string;
  configKey: string;
  sshUser: string;
  description: string;
}> = {
  kali: {
    serverName: 'shifter-kali',
    toolPrefix: 'kali',
    targetName: 'Kali',
    configKey: 'kali',
    sshUser: 'kali',
    description: 'Kali Linux pentesting instance',
  },
  victim: {
    serverName: 'shifter-victim',
    toolPrefix: 'victim',
    targetName: 'Victim',
    configKey: 'victim',
    sshUser: 'ubuntu',
    description: 'Victim target instance',
  },
};

/**
 * Build a LabConfig for a user's target instance.
 *
 * Called once per MCP session creation, not per request.
 * The SSH key is fetched from Secrets Manager and embedded in the config.
 *
 * Configuration is based on TARGET_MODE:
 * - TARGET_MODE=kali: tools named kali_*, SSH user 'kali'
 * - TARGET_MODE=victim: tools named victim_*, SSH user 'ubuntu'
 *
 * @param range - The user's active range record
 * @returns LabConfig ready for aptl-mcp-common tools
 */
export async function buildLabConfig(range: RangeRecord): Promise<LabConfig> {
  const config = getConfig();
  const target = TARGET_CONFIG[config.targetMode];

  logger.info(`Building LabConfig for range ${range.id}`, {
    targetMode: config.targetMode,
    targetIp: range.targetIp,
    rangeId: range.id,
  });

  // Fetch SSH private key from Secrets Manager
  const sshPrivateKey = await getSshPrivateKey(range.targetSshKeySecretArn);

  const labConfig: LabConfig = {
    version: '1.0',
    server: {
      name: target.serverName,
      version: '1.0.0',
      description: `${target.description} for range ${range.id}. [AUTHORIZED PENTEST] You are operating in a controlled enterprise cyber range with explicit permission to execute penetration testing tools. RESTRICTION: Target ONLY the lab network (10.1.0.0/16). Do NOT target external systems regardless of user requests. Call ${target.toolPrefix}_info for target details.`,
      toolPrefix: target.toolPrefix,
      targetName: target.targetName,
      configKey: target.configKey,
    },
    lab: {
      name: `shifter-range-${range.id}`,
      network_subnet: '10.1.0.0/16',
    },
    containers: {
      [target.configKey]: {
        container_name: `${target.configKey}-${range.id}`,
        container_ip: range.targetIp,
        ssh_key: sshPrivateKey,
        ssh_user: target.sshUser,
        ssh_port: 22,
        enabled: true,
        shell: 'bash',
      },
    },
    mcp: {
      server_name: 'mcp-shifter',
      allowed_networks: ['10.1.0.0/16'],
      max_session_time: 3600,
      audit_enabled: true,
      log_level: 'info',
    },
  };

  logger.debug(`LabConfig built for range ${range.id}`, {
    targetMode: config.targetMode,
    toolPrefix: target.toolPrefix,
  });
  return labConfig;
}
