/**
 * Tests for session-manager.ts
 *
 * Tests session storage, retrieval, and lifecycle management.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock dependencies before importing session manager
vi.mock('../config.js', () => ({
  getConfig: vi.fn(() => ({
    sessions: {
      maxGlobal: 500,
      maxPerUser: 5,
      logInfoThreshold: 400,
      logWarnThreshold: 450,
    },
  })),
}));

vi.mock('../logger.js', () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('../connection-cleanup.js', () => ({
  onSessionCreated: vi.fn(),
  onSessionDestroyed: vi.fn(),
}));

// Import after mocks are set up
import {
  canCreateSession,
  storeSession,
  getSessionByMcpId,
  getSessionsForUser,
  destroySessionByMcpId,
  destroyAllSessions,
  getSessionCount,
  getSessionStats,
} from '../session-manager.js';
import { getConfig } from '../config.js';
import { onSessionCreated, onSessionDestroyed } from '../connection-cleanup.js';

// Helper to create mock transport
const createMockTransport = () => ({
  close: vi.fn().mockResolvedValue(undefined),
  handleRequest: vi.fn(),
  sessionId: undefined,
});

// Helper to create mock range
const createMockRange = (id = 1) => ({
  id,
  userId: 100,
  status: 'ready',
  kaliIp: '10.1.1.5',
  kaliInstanceId: 'i-123',
  kaliSshKeySecretArn: 'arn:aws:secretsmanager:...',
  chatUrl: null,
  createdAt: new Date(),
  updatedAt: new Date(),
});

// Helper to create mock lab config
const createMockLabConfig = () => ({
  server: { name: 'test-server', version: '1.0.0' },
  connections: [],
  tools: [],
});

describe('session-manager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset session state between tests by destroying all
  });

  afterEach(async () => {
    // Clean up sessions after each test
    await destroyAllSessions();
  });

  describe('canCreateSession', () => {
    it('allows session when under limits', () => {
      const result = canCreateSession('user@test.com');
      expect(result).toBeNull();
    });

    it('returns error when global limit reached', () => {
      // Mock config to have low limit
      vi.mocked(getConfig).mockReturnValue({
        sessions: {
          maxGlobal: 0, // No sessions allowed
          maxPerUser: 5,
          logInfoThreshold: 0,
          logWarnThreshold: 0,
        },
      });

      const result = canCreateSession('user@test.com');
      expect(result).toContain('Global session limit');
    });
  });

  describe('storeSession', () => {
    it('stores session with correct data', () => {
      const mcpSessionId = 'mcp-session-123';
      const userEmail = 'user@test.com';
      const range = createMockRange();
      const labConfig = createMockLabConfig();
      const transport = createMockTransport();

      storeSession(mcpSessionId, userEmail, range, labConfig, transport as any);

      const session = getSessionByMcpId(mcpSessionId);
      expect(session).toBeDefined();
      expect(session?.sessionId).toBe(mcpSessionId);
      expect(session?.userEmail).toBe(userEmail);
      expect(session?.rangeId).toBe(range.id);
      expect(session?.kaliIp).toBe(range.kaliIp);
      expect(session?.labConfig).toBe(labConfig);
      expect(session?.transport).toBe(transport);
      expect(session?.createdAt).toBeInstanceOf(Date);
    });

    it('notifies cleanup manager on session created', () => {
      const mcpSessionId = 'mcp-session-456';
      const userEmail = 'user@test.com';
      const range = createMockRange();
      const labConfig = createMockLabConfig();
      const transport = createMockTransport();

      storeSession(mcpSessionId, userEmail, range, labConfig, transport as any);

      expect(onSessionCreated).toHaveBeenCalled();
    });

    it('increments session count', () => {
      const initialCount = getSessionCount();

      storeSession(
        'session-1',
        'user@test.com',
        createMockRange(1),
        createMockLabConfig(),
        createMockTransport() as any
      );

      expect(getSessionCount()).toBe(initialCount + 1);
    });
  });

  describe('getSessionByMcpId', () => {
    it('returns session when found', () => {
      const mcpSessionId = 'session-to-find';
      storeSession(
        mcpSessionId,
        'user@test.com',
        createMockRange(),
        createMockLabConfig(),
        createMockTransport() as any
      );

      const session = getSessionByMcpId(mcpSessionId);
      expect(session).toBeDefined();
      expect(session?.sessionId).toBe(mcpSessionId);
    });

    it('returns undefined when not found', () => {
      const session = getSessionByMcpId('nonexistent-session');
      expect(session).toBeUndefined();
    });
  });

  describe('getSessionsForUser', () => {
    it('returns all sessions for a user', () => {
      const userEmail = 'multi-session@test.com';

      storeSession('session-a', userEmail, createMockRange(1), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-b', userEmail, createMockRange(2), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-c', 'other@test.com', createMockRange(3), createMockLabConfig(), createMockTransport() as any);

      const sessions = getSessionsForUser(userEmail);
      expect(sessions).toHaveLength(2);
      expect(sessions.map(s => s.sessionId)).toContain('session-a');
      expect(sessions.map(s => s.sessionId)).toContain('session-b');
    });

    it('returns empty array for user with no sessions', () => {
      const sessions = getSessionsForUser('no-sessions@test.com');
      expect(sessions).toEqual([]);
    });
  });

  describe('destroySessionByMcpId', () => {
    it('removes session from storage', async () => {
      const mcpSessionId = 'session-to-destroy';
      storeSession(
        mcpSessionId,
        'user@test.com',
        createMockRange(),
        createMockLabConfig(),
        createMockTransport() as any
      );

      expect(getSessionByMcpId(mcpSessionId)).toBeDefined();

      await destroySessionByMcpId(mcpSessionId);

      expect(getSessionByMcpId(mcpSessionId)).toBeUndefined();
    });

    it('closes transport on destroy', async () => {
      const transport = createMockTransport();
      const mcpSessionId = 'session-with-transport';

      storeSession(
        mcpSessionId,
        'user@test.com',
        createMockRange(),
        createMockLabConfig(),
        transport as any
      );

      await destroySessionByMcpId(mcpSessionId);

      expect(transport.close).toHaveBeenCalled();
    });

    it('notifies cleanup manager on session destroyed', async () => {
      const mcpSessionId = 'session-notify';
      storeSession(
        mcpSessionId,
        'user@test.com',
        createMockRange(),
        createMockLabConfig(),
        createMockTransport() as any
      );

      await destroySessionByMcpId(mcpSessionId);

      expect(onSessionDestroyed).toHaveBeenCalled();
    });

    it('handles nonexistent session gracefully', async () => {
      await expect(destroySessionByMcpId('nonexistent')).resolves.toBeUndefined();
    });

    it('removes session from user index', async () => {
      const userEmail = 'indexed-user@test.com';
      const mcpSessionId = 'indexed-session';

      storeSession(
        mcpSessionId,
        userEmail,
        createMockRange(),
        createMockLabConfig(),
        createMockTransport() as any
      );

      expect(getSessionsForUser(userEmail)).toHaveLength(1);

      await destroySessionByMcpId(mcpSessionId);

      expect(getSessionsForUser(userEmail)).toHaveLength(0);
    });
  });

  describe('destroyAllSessions', () => {
    it('removes all sessions', async () => {
      storeSession('session-1', 'user1@test.com', createMockRange(1), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-2', 'user2@test.com', createMockRange(2), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-3', 'user3@test.com', createMockRange(3), createMockLabConfig(), createMockTransport() as any);

      expect(getSessionCount()).toBe(3);

      await destroyAllSessions();

      expect(getSessionCount()).toBe(0);
    });
  });

  describe('getSessionStats', () => {
    it('returns correct statistics', () => {
      storeSession('session-1', 'user1@test.com', createMockRange(1), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-2', 'user1@test.com', createMockRange(2), createMockLabConfig(), createMockTransport() as any);
      storeSession('session-3', 'user2@test.com', createMockRange(3), createMockLabConfig(), createMockTransport() as any);

      const stats = getSessionStats();

      expect(stats.globalCount).toBe(3);
      expect(stats.perUserCounts.get('user1@test.com')).toBe(2);
      expect(stats.perUserCounts.get('user2@test.com')).toBe(1);
    });
  });
});
