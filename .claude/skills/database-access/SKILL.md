---
name: database-access
description: Query the Shifter PostgreSQL database via SSM port forwarding. Use when the user asks about database contents, wants to run SQL queries, check data, inspect tables, or troubleshoot database issues.
---

# Database Access

Connect to and query the Shifter PostgreSQL database (dev or prod) via AWS SSM port forwarding.

## Prerequisites

Port forwarding must be running in a separate terminal before queries can execute.

## Workflow

### Step 1: Start Port Forwarding (if not already running)

Start port forwarding in the background:

```bash
./scripts/db-connect.sh -e dev   # For dev environment
./scripts/db-connect.sh -e prod  # For prod environment
```

This opens a tunnel on `localhost:15432` to the RDS instance.

### Step 2: Run Queries

Use the `db-query.sh` script to execute SQL:

```bash
# Single query
./scripts/db-query.sh -e dev "SELECT COUNT(*) FROM auth_user"

# Interactive psql session
./scripts/db-query.sh -e dev
```

## Common Queries

### User Information
```sql
SELECT id, email, is_staff, is_superuser, date_joined FROM auth_user ORDER BY date_joined DESC LIMIT 10;
```

### Range Status
```sql
SELECT id, user_id, status, created_at FROM mission_control_range ORDER BY created_at DESC LIMIT 10;
```

### Agent Configurations
```sql
SELECT id, name, user_id, created_at FROM mission_control_agent ORDER BY created_at DESC;
```

### Risk Register (admin only)
```sql
SELECT id, title, severity, status, created_at FROM risk_register_risk ORDER BY created_at DESC;
```

## Environment Variables

- `PANW_SHIFTER_DEV_PROFILE` - AWS profile for dev environment
- `PANW_SHIFTER_PROD_PROFILE` - AWS profile for prod environment

## Important Notes

- Always specify the environment (`-e dev` or `-e prod`)
- Port forwarding must be running before queries will work
- The tunnel uses port 15432 locally
- Credentials are fetched automatically from AWS Secrets Manager
