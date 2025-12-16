/**
 * MCP Session Manager
 *
 * Manages per-user MCP sessions with:
 * - Session lifecycle (create, destroy, cleanup)
 * - Per-user and global session limits
 * - LabConfig caching per session
 * - Transport management
 *
 * Sessions are keyed by MCP session ID (from StreamableHTTPServerTransport).
 */

import type { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import type { LabConfig } from 'aptl-mcp-common';
import type { MCPSession, SessionStats, RangeRecord } from './types.js';
import { getConfig } from './config.js';
import { logger } from './logger.js';
import { onSessionCreated, onSessionDestroyed } from './connection-cleanup.js';

/**
 * Session storage - keyed by MCP session ID (from transport)
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
 * Store a new MCP session.
 *
 * Called from server.ts onsessioninitialized callback after the transport
 * generates its session ID. LabConfig is built before transport creation.
 *
 * @param mcpSessionId - The MCP session ID from transport
 * @param userEmail - The user's email
 * @param range - The user's active range
 * @param labConfig - Pre-built LabConfig for this session
 * @param transport - The MCP transport for this session
 */
export function storeSession(
  mcpSessionId: string,
  userEmail: string,
  range: RangeRecord,
  labConfig: LabConfig,
  transport: StreamableHTTPServerTransport
): void {
  const session: MCPSession = {
    sessionId: mcpSessionId,
    userEmail,
    rangeId: range.id,
    targetIp: range.targetIp,
    labConfig,
    transport,
    createdAt: new Date(),
  };

  // Store session keyed by MCP session ID
  sessions.set(mcpSessionId, session);

  // Update user index
  if (!sessionsByUser.has(userEmail)) {
    sessionsByUser.set(userEmail, new Set());
  }
  sessionsByUser.get(userEmail)!.add(mcpSessionId);

  // Notify cleanup manager that a session was created
  onSessionCreated();

  logger.info(`Session stored: ${mcpSessionId}`, {
    userEmail,
    rangeId: range.id,
    globalSessions: sessions.size,
  });
}

/**
 * Get a session by MCP session ID.
 */
export function getSessionByMcpId(mcpSessionId: string): MCPSession | undefined {
  return sessions.get(mcpSessionId);
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
 * Destroy a session by MCP session ID and clean up resources.
 */
export async function destroySessionByMcpId(mcpSessionId: string): Promise<void> {
  const session = sessions.get(mcpSessionId);
  if (!session) {
    return;
  }

  // Close transport
  try {
    await session.transport.close();
  } catch (error) {
    logger.warn(`Error closing transport for session ${mcpSessionId}`, {
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }

  // Remove from storage
  sessions.delete(mcpSessionId);

  // Update user index
  const userSessions = sessionsByUser.get(session.userEmail);
  if (userSessions) {
    userSessions.delete(mcpSessionId);
    if (userSessions.size === 0) {
      sessionsByUser.delete(session.userEmail);
    }
  }

  // Notify cleanup manager that a session was destroyed
  onSessionDestroyed();

  logger.info(`Session destroyed: ${mcpSessionId}`, {
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
    await destroySessionByMcpId(sessionId);
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
    await destroySessionByMcpId(sessionId);
  }

  logger.info('All sessions destroyed');
}

/**
 * Get count of active sessions.
 */
export function getSessionCount(): number {
  return sessions.size;
}
