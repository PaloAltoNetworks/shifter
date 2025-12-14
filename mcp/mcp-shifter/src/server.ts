/**
 * mcp-shifter HTTP Server
 *
 * Express server that provides MCP over HTTP for OpenWebUI integration.
 * Routes requests to per-user MCP sessions based on JWT authentication.
 */

import express, { type Request, type Response, type NextFunction } from 'express';
import { randomUUID } from 'crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
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
  createSession,
  getSession,
  destroySession,
  destroyAllSessions,
  getSessionCount,
} from './session-manager.js';
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
    });
  });

  // MCP session initialization endpoint
  app.post('/mcp/session', authMiddleware, async (req: Request, res: Response) => {
    const userContext = req.userContext as UserContext;

    try {
      // Check if user has an active range
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

      // Create transport for this session
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
      });

      // Create session (builds LabConfig from range + Secrets Manager)
      const session = await createSession(userContext.email, range, transport);

      // Create MCP server with session's LabConfig
      const mcpServer = createMCPServerForSession(session.labConfig);

      // Connect server to transport
      await mcpServer.connect(transport);

      logger.info(`MCP session initialized for ${userContext.email}`, {
        sessionId: session.sessionId,
        rangeId: range.id,
      });

      res.json({
        sessionId: session.sessionId,
        rangeId: range.id,
        kaliIp: range.kaliIp,
      });
    } catch (error) {
      logger.error('Failed to initialize MCP session', {
        userEmail: userContext.email,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      res.status(500).json({
        error: 'session_creation_failed',
        message: 'Failed to create MCP session',
      });
    }
  });

  // MCP message endpoint
  app.post('/mcp/:sessionId', authMiddleware, async (req: Request, res: Response) => {
    const { sessionId } = req.params;
    const userContext = req.userContext as UserContext;

    const session = getSession(sessionId);

    if (!session) {
      res.status(404).json({
        error: 'session_not_found',
        message: 'Session not found or expired',
      });
      return;
    }

    // Verify session belongs to authenticated user
    if (session.userEmail !== userContext.email) {
      logger.warn(`Unauthorized session access attempt`, {
        sessionId,
        sessionOwner: session.userEmail,
        requestUser: userContext.email,
      });
      res.status(403).json({
        error: 'forbidden',
        message: 'Session belongs to another user',
      });
      return;
    }

    try {
      // Forward request to session transport
      await session.transport.handleRequest(req, res, req.body);
    } catch (error) {
      logger.error('MCP request failed', {
        sessionId,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      res.status(500).json({
        error: 'request_failed',
        message: 'MCP request processing failed',
      });
    }
  });

  // Session deletion endpoint
  app.delete('/mcp/:sessionId', authMiddleware, async (req: Request, res: Response) => {
    const { sessionId } = req.params;
    const userContext = req.userContext as UserContext;

    const session = getSession(sessionId);

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

    await destroySession(sessionId);

    logger.info(`Session destroyed by user`, {
      sessionId,
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

  const app = createApp();

  // Start listening
  const server = app.listen(config.server.port, () => {
    logger.info(`mcp-shifter server started`, {
      port: config.server.port,
    });
  });

  // Graceful shutdown
  const shutdown = async () => {
    logger.info('Shutting down gracefully...');

    // Stop accepting new connections
    server.close();

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
