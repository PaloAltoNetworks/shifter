/**
 * MCP Session Manager
 *
 * Manages per-user MCP sessions with:
 * - Session lifecycle (create, destroy, cleanup)
 * - Per-user and global session limits
 * - LabConfig caching per session
 * - Transport management
 */

import { randomUUID } from 'crypto';
import type { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import type { LabConfig } from 'aptl-mcp-common';
import type { MCPSession, SessionStats, RangeRecord } from './types.js';
import { getConfig } from './config.js';
import { logger } from './logger.js';
import { buildLabConfig } from './lab-config-builder.js';

/**
 * Session storage - keyed by sessionId
 */
const sessions = new Map<string, MCPSession>();

/**
 * Index of sessions per user email - for enforcing per-user limits
 */
const sessionsByUser = new Map<string, Set<string>>();

/**
 * Check if a user can create a new session.
 * Returns error message if not allowed, null if allowed.
 */
export function canCreateSession(userEmail: string): string | null {
  const config = getConfig();

  // Check global limit
  if (sessions.size >= config.sessions.maxGlobal) {
    logger.warn('Global session limit reached', {
      current: sessions.size,
      max: config.sessions.maxGlobal,
    });
    return `Global session limit reached (${config.sessions.maxGlobal})`;
  }

  // Check per-user limit
  const userSessions = sessionsByUser.get(userEmail);
  const userSessionCount = userSessions?.size ?? 0;

  if (userSessionCount >= config.sessions.maxPerUser) {
    logger.warn(`Per-user session limit reached for ${userEmail}`, {
      current: userSessionCount,
      max: config.sessions.maxPerUser,
    });
    return `Session limit reached for user (${config.sessions.maxPerUser})`;
  }

  // Log threshold warnings
  if (sessions.size >= config.sessions.logWarnThreshold) {
    logger.warn('Approaching global session limit', {
      current: sessions.size,
      warnThreshold: config.sessions.logWarnThreshold,
      max: config.sessions.maxGlobal,
    });
  } else if (sessions.size >= config.sessions.logInfoThreshold) {
    logger.info('Global session count elevated', {
      current: sessions.size,
      infoThreshold: config.sessions.logInfoThreshold,
    });
  }

  return null;
}

/**
 * Create a new MCP session for a user.
 *
 * Builds LabConfig from range data (DB + Secrets Manager hit happens here).
 * Subsequent requests for this session use cached config.
 *
 * @param userEmail - The user's email
 * @param range - The user's active range
 * @param transport - The MCP transport for this session
 * @returns The created session
 */
export async function createSession(
  userEmail: string,
  range: RangeRecord,
  transport: StreamableHTTPServerTransport
): Promise<MCPSession> {
  // Check limits (should be called by caller, but double-check)
  const limitError = canCreateSession(userEmail);
  if (limitError) {
    throw new Error(limitError);
  }

  const sessionId = randomUUID();

  // Build LabConfig - this is the DB/Secrets Manager hit
  const labConfig = await buildLabConfig(range);

  const session: MCPSession = {
    sessionId,
    userEmail,
    rangeId: range.id,
    kaliIp: range.kaliIp,
    labConfig,
    transport,
    createdAt: new Date(),
  };

  // Store session
  sessions.set(sessionId, session);

  // Update user index
  if (!sessionsByUser.has(userEmail)) {
    sessionsByUser.set(userEmail, new Set());
  }
  sessionsByUser.get(userEmail)!.add(sessionId);

  logger.info(`Session created: ${sessionId}`, {
    userEmail,
    rangeId: range.id,
    globalSessions: sessions.size,
  });

  return session;
}

/**
 * Get a session by ID.
 */
export function getSession(sessionId: string): MCPSession | undefined {
  return sessions.get(sessionId);
}

/**
 * Get all sessions for a user.
 */
export function getSessionsForUser(userEmail: string): MCPSession[] {
  const sessionIds = sessionsByUser.get(userEmail);
  if (!sessionIds) {
    return [];
  }
  return Array.from(sessionIds)
    .map(id => sessions.get(id))
    .filter((s): s is MCPSession => s !== undefined);
}

/**
 * Destroy a session and clean up resources.
 */
export async function destroySession(sessionId: string): Promise<void> {
  const session = sessions.get(sessionId);
  if (!session) {
    return;
  }

  // Close transport
  try {
    await session.transport.close();
  } catch (error) {
    logger.warn(`Error closing transport for session ${sessionId}`, {
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }

  // Remove from storage
  sessions.delete(sessionId);

  // Update user index
  const userSessions = sessionsByUser.get(session.userEmail);
  if (userSessions) {
    userSessions.delete(sessionId);
    if (userSessions.size === 0) {
      sessionsByUser.delete(session.userEmail);
    }
  }

  logger.info(`Session destroyed: ${sessionId}`, {
    userEmail: session.userEmail,
    globalSessions: sessions.size,
  });
}

/**
 * Get session statistics.
 */
export function getSessionStats(): SessionStats {
  const perUserCounts = new Map<string, number>();

  for (const [email, sessionIds] of sessionsByUser.entries()) {
    perUserCounts.set(email, sessionIds.size);
  }

  return {
    globalCount: sessions.size,
    perUserCounts,
  };
}

/**
 * Destroy all sessions for a user.
 * Used when user's range is destroyed.
 */
export async function destroySessionsForUser(userEmail: string): Promise<number> {
  const userSessionIds = sessionsByUser.get(userEmail);
  if (!userSessionIds) {
    return 0;
  }

  const sessionIds = Array.from(userSessionIds);
  for (const sessionId of sessionIds) {
    await destroySession(sessionId);
  }

  return sessionIds.length;
}

/**
 * Destroy all sessions.
 * Used for graceful shutdown.
 */
export async function destroyAllSessions(): Promise<void> {
  const sessionIds = Array.from(sessions.keys());

  for (const sessionId of sessionIds) {
    await destroySession(sessionId);
  }

  logger.info('All sessions destroyed');
}

/**
 * Get count of active sessions.
 */
export function getSessionCount(): number {
  return sessions.size;
}
