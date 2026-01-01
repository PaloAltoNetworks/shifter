# Shifter Management

Platform administration.

## Models

| Model | Purpose |
|-------|---------|
| `UserProfile` | Extended user attributes |
| `ActivityLog` | Audit trail |

## Service Interface

| Function | Purpose |
|----------|---------|
| `log_activity(action, user, **metadata)` | Audit logging |
