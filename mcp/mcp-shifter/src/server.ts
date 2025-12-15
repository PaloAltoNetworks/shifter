/**
 * mcp-shifter HTTP Server
 *
 * Express server that provides MCP over HTTP for OpenWebUI integration.
 * Uses standard MCP protocol with single /mcp endpoint.
 * Sessions are created on MCP initialize request, keyed by mcp-session-id header.
 */

import express, { type Request, type Response, type NextFunction } from 'express';
import { randomUUID } from 'crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  isInitializeRequest,
  type CallToolRequest,
} from '@modelcontextprotocol/sdk/types.js';
import {
  SSHConnectionManager,
  generateToolDefinitions,
  generateToolHandlers,
  type ToolContext,
  type LabConfig,
} from 'aptl-mcp-common';
import { initialize, getConfig } from './config.js';
import { logger } from './logger.js';
import { authMiddleware } from './middleware/auth.js';
import { getActiveRangeForUser, closePool } from './db.js';
import {
  canCreateSession,
  storeSession,
  getSessionByMcpId,
  destroySessionByMcpId,
  destroyAllSessions,
  getSessionCount,
} from './session-manager.js';
import {
  initializeCleanupManager,
  stopCleanupManager,
  getIdleStatus,
} from './connection-cleanup.js';
import { buildLabConfig } from './lab-config-builder.js';
import type { UserContext, NoRangeError, SessionLimitError } from './types.js';

// Shared SSH connection manager - pools connections by user@host:port
const sshManager = new SSHConnectionManager();

/**
 * Create an MCP Server instance for a session.
 */
function createMCPServerForSession(labConfig: LabConfig): Server {
  // Generate tools and handlers for this config
  const tools = generateToolDefinitions(labConfig.server);
  const handlers = generateToolHandlers(labConfig.server);

  // Create MCP server
  const server = new Server(
    {
      name: labConfig.server.name,
      version: labConfig.server.version,
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Setup request handlers
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools,
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request: CallToolRequest) => {
    const { name, arguments: args } = request.params;

    const handler = handlers[name];
    if (!handler) {
      throw new Error(`Unknown tool: ${name}`);
    }

    const context: ToolContext = {
      sshManager,
      labConfig,
    };

    return handler(args, context);
  });

  return server;
}

/**
 * Create and configure the Express application.
 */
export function createApp(): express.Application {
  const app = express();

  // Parse JSON bodies
  app.use(express.json());

  // Health check endpoint (no auth required)
  app.get('/health', (_req, res) => {
    res.json({
      status: 'healthy',
      sessions: getSessionCount(),
      idle: getIdleStatus(),
    });
  });

  /**
   * MCP POST endpoint - handles all MCP messages
   *
   * On initialize request: JWT auth -> range lookup -> build LabConfig -> create transport/server
   * On other requests: lookup session by mcp-session-id header -> forward to transport
   */
  app.post('/mcp', authMiddleware, async (req: Request, res: Response) => {
    const userContext = req.userContext as UserContext;
    const mcpSessionId = req.headers['mcp-session-id'] as string | undefined;

    try {
      // Check if we have an existing session
      if (mcpSessionId) {
        const session = getSessionByMcpId(mcpSessionId);

        if (session) {
          // Verify session belongs to authenticated user
          if (session.userEmail !== userContext.email) {
            logger.warn('Unauthorized session access attempt', {
              mcpSessionId,
              sessionOwner: session.userEmail,
              requestUser: userContext.email,
            });
            res.status(403).json({
              error: 'forbidden',
              message: 'Session belongs to another user',
            });
            return;
          }

          // Forward request to session transport
          await session.transport.handleRequest(req, res, req.body);
          return;
        }
      }

      // No existing session - must be initialize request
      if (!isInitializeRequest(req.body)) {
        res.status(400).json({
          error: 'session_required',
          message: 'mcp-session-id header required for non-initialize requests',
        });
        return;
      }

      // New session: validate user has active range
      const range = await getActiveRangeForUser(userContext.email);

      if (!range) {
        const error: NoRangeError = {
          error: 'no_active_range',
          message: 'No active range found. Please launch a range from the portal first.',
        };
        res.status(404).json(error);
        return;
      }

      // Check session limits
      const limitError = canCreateSession(userContext.email);
      if (limitError) {
        const config = getConfig();
        const error: SessionLimitError = {
          error: 'session_limit_reached',
          message: limitError,
          sessionsActive: getSessionCount(),
          sessionsMax: config.sessions.maxGlobal,
        };
        res.status(429).json(error);
        return;
      }

      // Build LabConfig from range
      const labConfig = await buildLabConfig(range);

      // Create transport - it will generate session ID on initialize
      // enableJsonResponse forces synchronous JSON responses instead of SSE streams
      // Required for compatibility with OpenWebUI wrapper which expects JSON
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        enableJsonResponse: true,
        onsessioninitialized: (sessionId: string) => {
          // Store session keyed by MCP session ID
          storeSession(sessionId, userContext.email, range, labConfig, transport);
          logger.info(`MCP session initialized for ${userContext.email}`, {
            mcpSessionId: sessionId,
            rangeId: range.id,
          });
        },
      });

      // Cleanup handler when transport closes
      transport.onclose = () => {
        const sid = transport.sessionId;
        if (sid) {
          destroySessionByMcpId(sid);
        }
      };

      // Create MCP server with LabConfig
      const mcpServer = createMCPServerForSession(labConfig);

      // Connect server to transport
      await mcpServer.connect(transport);

      // Let transport handle the initialize request
      // This will trigger onsessioninitialized callback and set mcp-session-id header
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      logger.error('MCP request failed', {
        userEmail: userContext.email,
        mcpSessionId,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      res.status(500).json({
        error: 'request_failed',
        message: 'MCP request processing failed',
      });
    }
  });

  /**
   * MCP GET endpoint - SSE stream for server-sent events
   */
  app.get('/mcp', authMiddleware, async (req: Request, res: Response) => {
    const userContext = req.userContext as UserContext;
    const mcpSessionId = req.headers['mcp-session-id'] as string | undefined;

    if (!mcpSessionId) {
      res.status(400).json({
        error: 'session_required',
        message: 'mcp-session-id header required for SSE stream',
      });
      return;
    }

    const session = getSessionByMcpId(mcpSessionId);

    if (!session) {
      res.status(404).json({
        error: 'session_not_found',
        message: 'Session not found or expired',
      });
      return;
    }

    // Verify session belongs to authenticated user
    if (session.userEmail !== userContext.email) {
      res.status(403).json({
        error: 'forbidden',
        message: 'Session belongs to another user',
      });
      return;
    }

    try {
      // Forward to transport for SSE handling
      await session.transport.handleRequest(req, res);
    } catch (error) {
      logger.error('SSE stream failed', {
        mcpSessionId,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      res.status(500).json({
        error: 'stream_failed',
        message: 'SSE stream setup failed',
      });
    }
  });

  /**
   * MCP DELETE endpoint - terminate session
   */
  app.delete('/mcp', authMiddleware, async (req: Request, res: Response) => {
    const userContext = req.userContext as UserContext;
    const mcpSessionId = req.headers['mcp-session-id'] as string | undefined;

    if (!mcpSessionId) {
      res.status(400).json({
        error: 'session_required',
        message: 'mcp-session-id header required to terminate session',
      });
      return;
    }

    const session = getSessionByMcpId(mcpSessionId);

    if (!session) {
      res.status(404).json({
        error: 'session_not_found',
        message: 'Session not found',
      });
      return;
    }

    // Verify session belongs to authenticated user
    if (session.userEmail !== userContext.email) {
      res.status(403).json({
        error: 'forbidden',
        message: 'Session belongs to another user',
      });
      return;
    }

    await destroySessionByMcpId(mcpSessionId);

    logger.info('Session destroyed by user', {
      mcpSessionId,
      userEmail: userContext.email,
    });

    res.json({ status: 'destroyed' });
  });

  // Error handler
  app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
    logger.error('Unhandled error', { error: err.message, stack: err.stack });
    res.status(500).json({
      error: 'internal_error',
      message: 'An internal error occurred',
    });
  });

  return app;
}

/**
 * Start the server.
 */
export async function startServer(configPath: string): Promise<void> {
  // Initialize configuration
  initialize(configPath);
  const config = getConfig();

  // Initialize connection cleanup manager
  initializeCleanupManager(sshManager);

  const app = createApp();

  // Start listening
  const server = app.listen(config.server.port, () => {
    logger.info('mcp-shifter server started', {
      port: config.server.port,
      idleTimeoutMs: config.connections.idleTimeoutMs,
    });
  });

  // Graceful shutdown
  const shutdown = async () => {
    logger.info('Shutting down gracefully...');

    // Stop accepting new connections
    server.close();

    // Stop cleanup manager timers
    stopCleanupManager();

    // Destroy all MCP sessions
    await destroyAllSessions();

    // Disconnect all SSH connections
    await sshManager.disconnectAll();

    // Close database pool
    await closePool();

    logger.info('Shutdown complete');
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}
