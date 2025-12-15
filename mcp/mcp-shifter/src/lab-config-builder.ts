/**
 * Dynamic LabConfig builder
 *
 * Builds LabConfig at session creation time from:
 * - Range data from RDS (Kali IP, instance ID)
 * - SSH private key from Secrets Manager
 */

import type { LabConfig } from 'aptl-mcp-common';
import type { RangeRecord } from './types.js';
import { getSshPrivateKey } from './secrets.js';
import { logger } from './logger.js';

/**
 * Build a LabConfig for a user's Kali instance.
 *
 * Called once per MCP session creation, not per request.
 * The SSH key is fetched from Secrets Manager and embedded in the config.
 *
 * @param range - The user's active range record
 * @returns LabConfig ready for aptl-mcp-common tools
 */
export async function buildLabConfig(range: RangeRecord): Promise<LabConfig> {
  logger.info(`Building LabConfig for range ${range.id}`, {
    kaliIp: range.kaliIp,
    rangeId: range.id,
  });

  // Fetch SSH private key from Secrets Manager
  const sshPrivateKey = await getSshPrivateKey(range.kaliSshKeySecretArn);

  const labConfig: LabConfig = {
    version: '1.0',
    server: {
      name: 'shifter-kali',
      version: '1.0.0',
      description: `Kali Linux instance for range ${range.id}`,
      toolPrefix: 'kali',
      targetName: 'Kali',
      configKey: 'kali',
    },
    lab: {
      name: `shifter-range-${range.id}`,
      network_subnet: '10.1.0.0/16',
    },
    containers: {
      kali: {
        container_name: `kali-${range.id}`,
        container_ip: range.kaliIp,
        ssh_key: sshPrivateKey,
        ssh_user: 'kali',
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

  logger.debug(`LabConfig built for range ${range.id}`);
  return labConfig;
}
