# Shifter Management

Platform administration.

## Account principals introduced by ADR-066

`Principal` identifies a human or service actor independently from Django user
and provider identity records. A human principal has exactly one Django user;
a service principal has no Django user and may have a human contact. The
`ProviderBinding` table maps one exact issuer/subject pair to one principal.
The pair is immutable after creation, including through bulk SQL updates. A
provider identity collision fails rather than silently changing principal
ownership. Principal and binding changes use strict audit writes.

The `management.services` facade creates and resolves principals through its
same-domain `management.principals` implementation. The data
migration maps existing users to human principals and maps only complete,
unambiguous legacy provider tuples. S3 (#2316) introduces the
[unified credential boundary](access-credentials.md): Knox personal credentials,
native Google service admissions, and bounded human session assurance. This
source change is deployed with the coordinated S8 cutover, not as a dual-verifier
compatibility period. Isolated-account login and recovery remain supported;
retired participant magic-link authentication is not restored.

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

## Management commands

| Command | Purpose |
|---------|---------|
| `delete_user <email>` | Explicit test-posture-only hard-delete utility; refuses production posture before lookup and refuses users protected by durable principals or other retained records. Normal offboarding uses the soft-delete lifecycle. |
