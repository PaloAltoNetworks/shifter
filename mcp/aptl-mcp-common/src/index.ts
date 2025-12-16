// Export the working SSH implementation exactly as-is
export {
  SSHConnectionManager,
  PersistentSession,
  SSHError,
  CommandResult,
  SessionType,
  SessionMode,
  SessionMetadata,
  CommandRequest
} from './ssh.js';
export { expandTilde } from './utils.js';

// Export MCP server creation and types
export { createMCPServer } from './server.js';
export type { LabConfig } from './config.js';
export { loadLabConfig, getTargetCredentials } from './config.js';
export type { ToolContext } from './tools/handlers.js';

// Export tool builders for custom server implementations
export { generateToolDefinitions } from './tools/definitions.js';
export { generateToolHandlers } from './tools/handlers.js';

// Export HTTP/API functionality
export { HTTPClient, type HTTPResponse, type HTTPError } from './http.js';
export { generateAPIToolDefinitions } from './tools/api-definitions.js';
export { generateAPIToolHandlers, type APIToolContext } from './tools/api-handlers.js';
