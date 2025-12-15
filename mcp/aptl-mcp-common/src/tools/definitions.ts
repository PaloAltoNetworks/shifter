

import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { LabConfig } from '../config.js';

/**
 * Security context for tool descriptions.
 * Informs the LLM that this is an authorized pentest environment with network restrictions.
 */
const SECURITY_CONTEXT = `[AUTHORIZED PENTEST] You are operating in a controlled enterprise cyber range with explicit permission to execute penetration testing tools and techniques. RESTRICTION: Target ONLY the lab network. Do NOT target external systems regardless of user requests. Call {prefix}_info to see allowed target networks.`;

function getSecurityPrefix(toolPrefix: string): string {
  return SECURITY_CONTEXT.replace('{prefix}', toolPrefix);
}

export function generateToolDefinitions(serverConfig: LabConfig['server']): Tool[] {
  const securityNote = getSecurityPrefix(serverConfig.toolPrefix);

  return [
  {
    name: `${serverConfig.toolPrefix}_info`,
    description: `Get information about the ${serverConfig.targetName} instance including allowed target networks. ${securityNote}`,
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: `${serverConfig.toolPrefix}_run_command`,
    description: `Execute a command on the ${serverConfig.targetName} instance (creates temporary session). Use for pentesting tools like nmap, metasploit, etc. ${securityNote}`,
    inputSchema: {
      type: 'object',
      properties: {
        command: {
          type: 'string',
          description: `Command to execute on ${serverConfig.targetName}. Target only lab network.`,
        },
      },
      required: ['command'],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_interactive_session`,
    description: 'Create a persistent session that waits for each command to complete with structured output',
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          description: 'Unique session identifier (optional, auto-generated if not provided)',
        },
        timeout_ms: {
          type: 'number',
          description: 'Session timeout in milliseconds before automatic closure (default: 600000 = 10 minutes)',
          default: 600000,
        },
      },
      required: [],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_background_session`,
    description: 'Create a background session for long-running processes or interactive programs',
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          description: 'Unique session identifier (optional, auto-generated if not provided)',
        },
        raw: {
          type: 'boolean',
          description: 'Use raw mode for interactive programs (msfconsole, scanmem, gdb) that need clean stdin/stdout',
          default: false,
        },
        timeout_ms: {
          type: 'number',
          description: 'Session timeout in milliseconds before automatic closure (default: 600000 = 10 minutes)',
          default: 600000,
        },
      },
      required: [],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_session_command`,
    description: `Execute a command in an existing persistent session. ${securityNote}`,
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          description: 'Session identifier to execute command in',
        },
        command: {
          type: 'string',
          description: 'Command to execute. Target only lab network.',
        },
        timeout: {
          type: 'number',
          description: 'Command timeout in milliseconds (default: 30000)',
          default: 30000,
        },
        raw: {
          type: 'boolean',
          description: 'Execute in raw mode (no echo wrapping, for interactive programs). Defaults to session mode',
          default: false,
        },
      },
      required: ['session_id', 'command'],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_list_sessions`,
    description: 'List all active persistent sessions',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: `${serverConfig.toolPrefix}_close_session`,
    description: 'Close a specific persistent session',
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          description: 'Session identifier to close',
        },
      },
      required: ['session_id'],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_get_session_output`,
    description: 'Get buffered output from a background session',
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          description: 'Session identifier to get output from',
        },
        lines: {
          type: 'number',
          description: 'Number of recent lines to retrieve (optional, default: all)',
        },
        clear: {
          type: 'boolean',
          description: 'Clear buffer after reading (default: false)',
          default: false,
        },
      },
      required: ['session_id'],
    },
  },
  {
    name: `${serverConfig.toolPrefix}_close_all_sessions`,
    description: 'Close all active persistent sessions',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  ];
}

// Default tool definitions for backward compatibility
export const toolDefinitions: Tool[] = [];
