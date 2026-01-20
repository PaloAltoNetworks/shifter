# Ranges

Launch and manage isolated demo environments.

## Range Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Pending: Launch
    Pending --> Provisioning: Processing
    Provisioning --> Ready: Complete
    Provisioning --> Failed: Error
    Ready --> Destroyed: Destroy
    Pending --> Destroyed: Cancel
    Provisioning --> Destroyed: Cancel
    Failed --> Destroyed: Destroy
```

## Status Reference

| Status | Meaning |
|--------|---------|
| Pending | Queued for provisioning |
| Provisioning | Infrastructure being created |
| Ready | Range is live, accessible |
| Failed | Provisioning error occurred |
| Destroyed | Range terminated |

## Launch a Range

1. Go to **Ranges page**
2. Select a scenario
3. Select an agent
4. Click **Launch Range**

Provisioning takes 2-5 minutes.

## Monitor Provisioning

The Ranges page shows real-time status updates during provisioning. You'll see progress as instances are created and configured.

## Access a Range

Once Ready:
1. Go to **Terminal**
2. Select an instance
3. Use SSH or RDP to connect

See [Terminal](terminal.md) for details.

## Cancel a Range

While in Pending or Provisioning status:
1. Go to **Ranges page**
2. Click **Cancel** on the range

## Destroy a Range

When finished:
1. Go to **Ranges page**
2. Click **Destroy** on the range

This is irreversible. All range data is deleted.

## Limits

- One active range at a time per user
