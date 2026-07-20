// Database tunnel, connection-pool, and portal-test-tunnel lifecycle
// for the shifter-ops MCP server.
//
// This module owns ALL long-lived AWS/DB transport state (RDS SSM
// tunnels, pg pools, cached credentials, and the dev portal test
// tunnel). Tool handlers never open their own pools or tunnels; they
// go through `withClient` (DB) or `startPortalTestTunnel` /
// `stopPortalTestTunnel` (dev bypass). `buildPoolConfig` keeps TLS
// verification on (ADR-014-R7); see mcp/ops/SECURITY.md.

import net from "node:net";
import pg from "pg";
import {
  LOCAL_PORTS,
  buildPoolConfig,
  awsText as awsTextLib,
} from "./lib.js";
import { spawnAws, getProfile } from "./aws.js";
import {
  CMD_DESCRIBE_INSTANCES,
  FILTER_RUNNING_INSTANCES,
  QUERY_FIRST_INSTANCE_ID,
} from "./schemas.js";

const { Pool } = pg;

const tunnels = {}; // env -> { process, rdsHost }
const credentials = {}; // env -> { username, password, dbname }
const pools = {}; // env -> pg.Pool
const portalTunnels = {}; // env -> { process, port }

export async function isPortOpen(port) {
  // Validate the port against the TCP range before it reaches the socket
  // connect sink. Callers already constrain it (the LOCAL_PORTS constants
  // and the zod-validated local_port on start_portal_test_tunnel), but
  // bounding it here means the localhost probe can never act on a
  // non-integer or out-of-range value, and it closes the tainted-value
  // path Sonar flags (jssecurity:S5144). The host is always 127.0.0.1.
  const safePort = Number(port);
  if (!Number.isInteger(safePort) || safePort < 1 || safePort > 65535) {
    throw new Error(`Invalid port: ${port}`);
  }
  return new Promise((resolve) => {
    const sock = new net.Socket();
    sock.setTimeout(1000);
    sock.on("connect", () => {
      sock.destroy();
      resolve(true);
    });
    sock.on("error", () => resolve(false));
    sock.on("timeout", () => {
      sock.destroy();
      resolve(false);
    });
    sock.connect(safePort, "127.0.0.1");
  });
}

async function fetchCredentials(env) {
  if (credentials[env]) return credentials[env];

  const profile = getProfile(env);
  const secretId = `shifter-${env}-portal-db-credentials`;

  const result = awsTextLib(
    profile,
    [
      "secretsmanager",
      "get-secret-value",
      "--secret-id",
      secretId,
      "--query",
      "SecretString",
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );

  credentials[env] = JSON.parse(result);
  return credentials[env];
}

function killTunnel(env) {
  if (tunnels[env]?.process) {
    tunnels[env].process.kill();
    delete tunnels[env];
  }
}

function discoverRdsEndpoint(env) {
  // The RDS endpoint is the verification target for TLS (#1190) and
  // the destination address for the SSM port-forward. Both code
  // paths in ensureTunnel() rely on this — the "tunnel already open"
  // shortcut needs the endpoint too, not just the start-from-scratch
  // path. Factored out so the lookup runs every invocation and we
  // never reach getPool() with `tunnels[env].rdsHost === undefined`
  // (codex review #1180 cycle 1 finding 2).
  const profile = getProfile(env);
  const jmesQuery = `DBInstances[?DBInstanceIdentifier==\`${env}-portal-db\`].Endpoint.Address`;
  const rdsHost = awsTextLib(
    profile,
    [
      "rds",
      "describe-db-instances",
      "--query",
      jmesQuery,
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );
  if (!rdsHost || rdsHost === "None") {
    throw new Error(`Could not find RDS endpoint for ${env}`);
  }
  return rdsHost;
}

async function ensureTunnel(env) {
  const port = LOCAL_PORTS[env];

  // Tunnel-already-up paths: still resolve and cache the RDS
  // endpoint so getPool()'s buildPoolConfig() has the verification
  // target. Without this, a pre-existing port-forward (started by a
  // previous server instance, an operator's manual session, etc.)
  // would short-circuit ensureTunnel() and leave rdsHost undefined,
  // which buildPoolConfig() refuses by design.
  if (tunnels[env]?.process && !tunnels[env].process.killed) {
    if (await isPortOpen(port)) {
      if (!tunnels[env].rdsHost) {
        tunnels[env].rdsHost = discoverRdsEndpoint(env);
      }
      return;
    }
    killTunnel(env);
  }

  if (await isPortOpen(port)) {
    // Port is open but we don't own the tunnel record. Cache the
    // RDS endpoint so getPool can target the right cert; record the
    // tunnel as managed-elsewhere (no `.process`) so killTunnel
    // doesn't try to kill someone else's process.
    const rdsHost = discoverRdsEndpoint(env);
    tunnels[env] = { process: null, rdsHost };
    return;
  }

  const profile = getProfile(env);

  const instanceId = awsTextLib(
    profile,
    [
      "ec2",
      CMD_DESCRIBE_INSTANCES,
      "--filters",
      `Name=tag:Name,Values=${env}-portal-ec2`,
      FILTER_RUNNING_INSTANCES,
      "--query",
      QUERY_FIRST_INSTANCE_ID,
      "--output",
      "text",
    ],
    { timeoutMs: 30000 }
  );

  if (!instanceId || instanceId === "None") {
    throw new Error(`Could not find running ${env} portal EC2 instance`);
  }

  const rdsHost = discoverRdsEndpoint(env);

  const proc = spawnAws(
    profile,
    [
      "ssm",
      "start-session",
      "--target",
      instanceId,
      "--document-name",
      "AWS-StartPortForwardingSessionToRemoteHost",
      "--parameters",
      JSON.stringify({
        host: [rdsHost],
        portNumber: ["5432"],
        localPortNumber: [String(port)],
      }),
    ],
    { stdio: ["ignore", "pipe", "pipe"] }
  );

  // Capture the discovered rdsHost so getPool() can set ssl.servername
  // for cert verification. The tunnel terminates at localhost but the
  // RDS-issued cert names the RDS endpoint; without this the previous
  // `rejectUnauthorized: false` workaround silently broke TLS trust.
  tunnels[env] = { process: proc, rdsHost };

  proc.on("exit", () => {
    delete tunnels[env];
  });

  for (let i = 0; i < 30; i++) {
    if (await isPortOpen(port)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }

  proc.kill();
  delete tunnels[env];
  throw new Error("Tunnel failed to start within 30 seconds");
}

async function getPool(env) {
  await ensureTunnel(env);
  const creds = await fetchCredentials(env);

  if (!pools[env]) {
    const rdsHost = tunnels[env]?.rdsHost;
    pools[env] = new Pool(
      buildPoolConfig({ rdsHost, creds, port: LOCAL_PORTS[env] }),
    );
    pools[env].on("error", () => {
      pools[env]?.end().catch(() => {});
      delete pools[env];
    });
  }

  return pools[env];
}

export async function withClient(env, { readOnly = true } = {}, fn) {
  const pool = await getPool(env);
  const client = await pool.connect();
  try {
    if (readOnly) {
      await client.query("SET default_transaction_read_only = ON");
    }
    return await fn(client);
  } finally {
    if (readOnly) {
      await client
        .query("SET default_transaction_read_only = OFF")
        .catch(() => {});
    }
    client.release();
  }
}

// ==========================================================================
// Portal test tunnel (dev bypass)
//
// Returns discriminated result descriptors ("already-running" /
// "started" / "not-running" / "stopped") and throws on failure; the
// `tools/ssm.js` registrar maps these to the operator-facing ok()/err()
// messages. Keeping the state and spawn mechanics here (not in the tool
// handler) is what the preflight's "no per-handler tunnels" rule
// requires.
// ==========================================================================

export async function startPortalTestTunnel(env, localPort = 8000) {
  if (portalTunnels[env]) {
    return { kind: "already-running", port: portalTunnels[env].port };
  }

  const portInUse = await isPortOpen(localPort);
  if (portInUse) {
    throw new Error(
      `Port ${localPort} already in use. Choose different port or stop existing tunnel.`
    );
  }

  const profile = getProfile(env);
  try {
    const instanceId = awsTextLib(
      profile,
      [
        "ec2",
        CMD_DESCRIBE_INSTANCES,
        "--filters",
        `Name=tag:Name,Values=${env}-portal-ec2`,
        FILTER_RUNNING_INSTANCES,
        "--query",
        QUERY_FIRST_INSTANCE_ID,
        "--output",
        "text",
      ],
      { timeoutMs: 30000 }
    );

    if (!instanceId || instanceId === "None") {
      throw new Error(`Could not find running ${env} portal EC2 instance`);
    }

    const tunnelProc = spawnAws(
      profile,
      [
        "ssm",
        "start-session",
        "--target",
        instanceId,
        "--document-name",
        "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters",
        JSON.stringify({
          host: ["localhost"],
          portNumber: ["8000"],
          localPortNumber: [localPort.toString()],
        }),
      ],
      { stdio: ["ignore", "pipe", "pipe"] }
    );

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        tunnelProc.kill();
        reject(new Error("Tunnel startup timeout"));
      }, 10000);

      let output = "";
      tunnelProc.stdout.on("data", (data) => {
        output += data.toString();
        if (output.includes("Waiting for connections")) {
          clearTimeout(timeout);
          resolve();
        }
      });

      tunnelProc.stderr.on("data", (data) => {
        const msg = data.toString();
        if (msg.includes("error") || msg.includes("failed")) {
          clearTimeout(timeout);
          reject(new Error(`Tunnel failed: ${msg}`));
        }
      });

      tunnelProc.on("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });

      tunnelProc.on("exit", (code) => {
        if (code !== 0 && code !== null) {
          clearTimeout(timeout);
          reject(new Error(`Tunnel exited with code ${code}`));
        }
      });
    });

    portalTunnels[env] = { process: tunnelProc, port: localPort };
    return { kind: "started", port: localPort };
  } catch (e) {
    if (portalTunnels[env]) {
      portalTunnels[env].process.kill();
      delete portalTunnels[env];
    }
    throw e;
  }
}

export function stopPortalTestTunnel(env) {
  if (!portalTunnels[env]) {
    return { kind: "not-running" };
  }
  portalTunnels[env].process.kill();
  const port = portalTunnels[env].port;
  delete portalTunnels[env];
  return { kind: "stopped", port };
}

// ==========================================================================
// Cleanup
// ==========================================================================

export function cleanup() {
  for (const env of Object.keys(pools)) {
    pools[env]?.end().catch(() => {});
    delete pools[env];
  }
  for (const env of Object.keys(tunnels)) {
    if (tunnels[env]?.process) {
      tunnels[env].process.kill();
    }
  }
}
