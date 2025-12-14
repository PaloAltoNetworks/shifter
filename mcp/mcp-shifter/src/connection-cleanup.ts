/**
 * Idle Connection Cleanup
 *
 * Monitors for idle SSH connections (connections with zero active MCP sessions)
 * and cleans them up after a configurable timeout.
 *
 * This prevents resource leaks when users disconnect without properly closing sessions.
 */

import type { SSHConnectionManager } from 'aptl-mcp-common';
import { getConfig } from './config.js';
import { getSessionCount } from './session-manager.js';
import { logger } from './logger.js';

let idleTimer: NodeJS.Timeout | null = null;
let idleStartTime: number | null = null;
let sshManagerRef: SSHConnectionManager | null = null;

/**
 * Initialize the connection cleanup manager.
 * @param sshManager - The shared SSH connection manager instance
 */
export function initializeCleanupManager(sshManager: SSHConnectionManager): void {
  sshManagerRef = sshManager;
  logger.info('Connection cleanup manager initialized');
}

/**
 * Called when a session is created.
 * Cancels any pending idle cleanup since we now have active sessions.
 */
export function onSessionCreated(): void {
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
    idleStartTime = null;
    logger.debug('Idle cleanup cancelled - session created');
  }
}

/**
 * Called when a session is destroyed.
 * If this was the last session, starts the idle timeout timer.
 */
export function onSessionDestroyed(): void {
  const sessionCount = getSessionCount();

  if (sessionCount === 0) {
    // All sessions are closed - start idle timeout
    startIdleTimer();
  }
}

/**
 * Start the idle timeout timer.
 * When it fires, close all SSH connections.
 */
function startIdleTimer(): void {
  if (idleTimer) {
    // Timer already running
    return;
  }

  const config = getConfig();
  const timeoutMs = config.connections.idleTimeoutMs;

  idleStartTime = Date.now();
  logger.info(`Starting idle cleanup timer (${timeoutMs}ms)`, {
    sessionCount: getSessionCount(),
  });

  idleTimer = setTimeout(async () => {
    // Double-check we still have zero sessions
    if (getSessionCount() > 0) {
      logger.debug('Idle cleanup skipped - sessions exist');
      idleTimer = null;
      idleStartTime = null;
      return;
    }

    await performCleanup();
  }, timeoutMs);
}

/**
 * Perform the actual cleanup of SSH connections.
 */
async function performCleanup(): Promise<void> {
  if (!sshManagerRef) {
    logger.warn('Cannot perform cleanup - SSH manager not initialized');
    return;
  }

  const idleDuration = idleStartTime ? Date.now() - idleStartTime : 0;

  logger.info('Performing idle connection cleanup', {
    idleDurationMs: idleDuration,
  });

  try {
    // Close all SSH connections via the manager
    await sshManagerRef.disconnectAll();
    logger.info('Idle SSH connections cleaned up successfully');
  } catch (error) {
    logger.error('Error during idle connection cleanup', {
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  } finally {
    idleTimer = null;
    idleStartTime = null;
  }
}

/**
 * Stop the cleanup manager and clear any pending timers.
 * Called during server shutdown.
 */
export function stopCleanupManager(): void {
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
    idleStartTime = null;
    logger.info('Connection cleanup manager stopped');
  }
  sshManagerRef = null;
}

/**
 * Get the current idle status for monitoring.
 */
export function getIdleStatus(): {
  isIdle: boolean;
  idleSinceMs: number | null;
  cleanupScheduledIn: number | null;
} {
  const config = getConfig();

  if (!idleStartTime) {
    return {
      isIdle: false,
      idleSinceMs: null,
      cleanupScheduledIn: null,
    };
  }

  const idleDuration = Date.now() - idleStartTime;
  const remainingMs = config.connections.idleTimeoutMs - idleDuration;

  return {
    isIdle: true,
    idleSinceMs: idleDuration,
    cleanupScheduledIn: Math.max(0, remainingMs),
  };
}
