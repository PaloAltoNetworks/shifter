/**
 * AWS Secrets Manager client
 *
 * Retrieves SSH private keys stored during range provisioning.
 */

import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';
import { getConfig } from './config.js';
import { logger } from './logger.js';

let client: SecretsManagerClient | null = null;

/**
 * Get or create the Secrets Manager client (singleton).
 */
function getClient(): SecretsManagerClient {
  if (!client) {
    const config = getConfig();
    client = new SecretsManagerClient({ region: config.aws.region });
  }
  return client;
}

/**
 * Retrieve SSH private key from Secrets Manager.
 *
 * @param secretArn - The ARN of the secret containing the SSH private key
 * @returns The SSH private key in PEM format
 * @throws Error if secret not found or access denied
 */
export async function getSshPrivateKey(secretArn: string): Promise<string> {
  const secretsClient = getClient();

  logger.debug(`Retrieving SSH key from ${secretArn}`);

  const response = await secretsClient.send(
    new GetSecretValueCommand({
      SecretId: secretArn,
    })
  );

  if (!response.SecretString) {
    throw new Error(`Secret ${secretArn} has no string value`);
  }

  return response.SecretString;
}

/**
 * Reset the client (for testing).
 */
export function resetSecretsClient(): void {
  client = null;
}
