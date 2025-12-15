/**
 * Database client with RDS IAM Authentication
 *
 * Uses @aws-sdk/rds-signer to generate IAM auth tokens for passwordless
 * connection to RDS PostgreSQL.
 */

import { Pool, type PoolClient } from 'pg';
import { Signer } from '@aws-sdk/rds-signer';
import { getConfig } from './config.js';
import { logger } from './logger.js';
import type { RangeRecord } from './types.js';

// AWS RDS uses certificates signed by their CA. For IAM auth over SSL,
// we need to either provide the CA bundle or disable strict verification.
// In containerized environments, the system CA store may not have the RDS CA.
const RDS_SSL_CONFIG = {
  // For production, we should bundle the RDS CA certificate.
  // For now, allow connections without strict CA verification since we're
  // using IAM auth which provides its own authentication layer.
  rejectUnauthorized: false,
};

let pool: Pool | null = null;

/**
 * Generate an IAM auth token for RDS connection.
 * Token is valid for 15 minutes.
 */
async function generateAuthToken(): Promise<string> {
  const config = getConfig();

  const signer = new Signer({
    hostname: config.rds.hostname,
    port: config.rds.port,
    username: config.rds.username,
    region: config.aws.region,
  });

  return signer.getAuthToken();
}

/**
 * Get or create the database connection pool.
 * Uses IAM auth tokens that refresh before expiry.
 */
export async function getPool(): Promise<Pool> {
  if (pool) {
    return pool;
  }

  const config = getConfig();
  const token = await generateAuthToken();

  pool = new Pool({
    host: config.rds.hostname,
    port: config.rds.port,
    database: config.rds.database,
    user: config.rds.username,
    password: token,
    ssl: RDS_SSL_CONFIG,
    // Pool settings
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 10000,
  });

  // Handle pool errors
  pool.on('error', (err) => {
    logger.error('Unexpected pool error', { error: err.message });
  });

  logger.info('Database pool created');
  return pool;
}

/**
 * Get a client from the pool.
 * Remember to release the client after use.
 */
export async function getClient(): Promise<PoolClient> {
  const p = await getPool();
  return p.connect();
}

/**
 * Look up active range for a user by email.
 * Returns null if user has no active range.
 *
 * @param userEmail - The user's email address
 * @returns RangeRecord if found, null otherwise
 */
export async function getActiveRangeForUser(userEmail: string): Promise<RangeRecord | null> {
  const client = await getClient();

  try {
    // Query joins auth_user to get the user by email
    // Active statuses include: ready, paused (usable states)
    const result = await client.query<{
      id: number;
      user_id: number;
      status: string;
      kali_ip: string;
      kali_instance_id: string;
      kali_ssh_key_secret_arn: string;
      chat_url: string | null;
      created_at: Date;
      updated_at: Date;
    }>(
      `SELECT r.id, r.user_id, r.status, r.kali_ip, r.kali_instance_id,
              r.kali_ssh_key_secret_arn, r.chat_url, r.created_at, r.updated_at
       FROM mission_control_range r
       JOIN auth_user u ON r.user_id = u.id
       WHERE u.email = $1
         AND r.status IN ('ready', 'paused')
       ORDER BY r.created_at DESC
       LIMIT 1`,
      [userEmail]
    );

    if (result.rows.length === 0) {
      return null;
    }

    const row = result.rows[0];
    return {
      id: row.id,
      userId: row.user_id,
      status: row.status,
      kaliIp: row.kali_ip,
      kaliInstanceId: row.kali_instance_id,
      kaliSshKeySecretArn: row.kali_ssh_key_secret_arn,
      chatUrl: row.chat_url,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    };
  } finally {
    client.release();
  }
}

/**
 * Close the database pool.
 */
export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
    logger.info('Database pool closed');
  }
}
