/**
 * Type definitions for mcp-shifter
 */

import type { LabConfig } from 'aptl-mcp-common';
import type { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';

/**
 * User context extracted from JWT claims
 */
export interface UserContext {
  email: string;
  sub: string;
  tokenUse: string;
  clientId: string;
  iat: number;
  exp: number;
}

/**
 * Range record from database
 * Fields are target-agnostic - actual columns queried depend on TARGET_MODE
 */
export interface RangeRecord {
  id: number;
  userId: number;
  status: string;
  targetIp: string;
  targetInstanceId: string;
  targetSshKeySecretArn: string;
  chatUrl: string | null;
  createdAt: Date;
  updatedAt: Date;
}

/**
 * MCP Session data cached per session
 */
export interface MCPSession {
  sessionId: string;
  userEmail: string;
  rangeId: number;
  targetIp: string;
  labConfig: LabConfig;
  transport: StreamableHTTPServerTransport;
  createdAt: Date;
}

/**
 * Session manager statistics
 */
export interface SessionStats {
  globalCount: number;
  perUserCounts: Map<string, number>;
}

/**
 * Error response for "no active range" case
 */
export interface NoRangeError {
  error: 'no_active_range';
  message: string;
}

/**
 * Error response for session limit reached
 */
export interface SessionLimitError {
  error: 'session_limit_reached';
  message: string;
  sessionsActive: number;
  sessionsMax: number;
}

/**
 * Express request with user context attached by auth middleware
 */
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      userContext?: UserContext;
    }
  }
}
