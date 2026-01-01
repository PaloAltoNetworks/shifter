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
| `get_user_profile(user)` | Get or create user profile |
| `mark_user_deleted(user)` | Soft delete user |
| `update_cognito_sub(user, cognito_sub)` | Update Cognito sub on profile |