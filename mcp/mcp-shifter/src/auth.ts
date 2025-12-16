/**
 * Cognito JWT authentication module
 *
 * Validates JWT tokens from AWS Cognito using the aws-jwt-verify library.
 * Extracts user context (email, sub) for downstream use.
 */

import { CognitoJwtVerifier } from 'aws-jwt-verify';
import type { UserContext } from './types.js';
import { getConfig } from './config.js';

let verifier: ReturnType<typeof CognitoJwtVerifier.create> | null = null;

/**
 * Get or create the Cognito JWT verifier (singleton).
 * Lazily initialized to allow config to be loaded first.
 */
function getVerifier(): ReturnType<typeof CognitoJwtVerifier.create> {
  if (!verifier) {
    const config = getConfig();
    verifier = CognitoJwtVerifier.create({
      userPoolId: config.cognito.userPoolId,
      tokenUse: 'access',
      clientId: config.cognito.clientId,
    });
  }
  return verifier;
}

/**
 * Validate a Cognito JWT access token and extract user context.
 *
 * @param token - The JWT access token (without "Bearer " prefix)
 * @returns User context extracted from token claims
 * @throws Error if token is invalid, expired, or verification fails
 */
export async function validateToken(token: string): Promise<UserContext> {
  const jwtVerifier = getVerifier();

  // Verify the token - throws if invalid
  const payload = await jwtVerifier.verify(token);

  // Cognito access tokens have 'sub' claim (the stable user identifier)
  // We use 'sub' for user lookups as it's the canonical identifier
  // Note: access tokens don't include the email claim
  const sub = payload.sub;
  if (!sub) {
    throw new Error('Token missing sub claim');
  }

  return {
    // Note: 'email' field contains the Cognito sub (UUID), not the actual email
    // This is used for DB lookups via cognito_sub column in UserProfile
    email: sub,
    sub,
    tokenUse: payload.token_use,
    clientId: payload.client_id as string,
    iat: payload.iat,
    exp: payload.exp,
  };
}

/**
 * Extract bearer token from Authorization header.
 *
 * @param authHeader - The Authorization header value
 * @returns The token without "Bearer " prefix, or null if invalid
 */
export function extractBearerToken(authHeader: string | undefined): string | null {
  if (!authHeader) {
    return null;
  }

  const parts = authHeader.split(' ');
  if (parts.length !== 2 || parts[0].toLowerCase() !== 'bearer') {
    return null;
  }

  return parts[1];
}

/**
 * Reset the verifier (for testing).
 */
export function resetVerifier(): void {
  verifier = null;
}
