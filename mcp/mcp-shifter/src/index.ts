/**
 * mcp-shifter - MCP HTTP wrapper for Shifter cyber range
 *
 * Provides per-user MCP sessions routed to user-specific Kali instances.
 */

import { startServer } from './server.js';
import { loadEnv } from './config.js';

async function main() {
  try {
    // Validate environment variables first
    const env = loadEnv();

    // Start server with config file path from environment
    await startServer(env.CONFIG_PATH);
  } catch (error) {
    console.error('Failed to start mcp-shifter:', error);
    process.exit(1);
  }
}

main();
