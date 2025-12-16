/**
 * mcp-shifter - MCP HTTP wrapper for Shifter cyber range
 *
 * Provides per-user MCP sessions routed to user-specific Kali instances.
 */

import { startServer } from './server.js';
import { loadEnv } from './config.js';

function main(): void {
  try {
    // Validate environment variables first
    const env = loadEnv();

    // Start server with config file path from environment
    startServer(env.CONFIG_PATH);
  } catch (error) {
    console.error('Failed to start mcp-shifter:', error);
    process.exit(1);
  }
}

main();
