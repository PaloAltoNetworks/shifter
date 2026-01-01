# Shifter CMS

Content and asset management.

## Service Interface

#### Agents

| Function | Purpose |
|----------|---------|
| `create_agent(user, ...)` | Create agent record |
| `delete_agent(user, agent_id)` | Soft delete agent |
| `list_agents(user)` | Get user's agents |
| `get_agent(user, agent_id)` | Get single agent |

#### Credentials

| Function | Purpose |
|----------|---------|
| `create_credential(user, type, ...)` | Create credential (scm, authcode) |
| `delete_credential(user, credential_id)` | Delete credential |
| `list_credentials(user)` | Get user's credentials (includes type) |
| `get_credential(user, credential_id)` | Get single credential |

#### Ranges

| Function | Purpose |
|----------|---------|
| `create_range(user, scenario, agent_id, ...)` | Compose scenario, trigger provisioning |
| `destroy_range(user, range_id)` | Tear down range |
| `list_ranges(user)` | Get user's ranges |
| `get_range(user, range_id)` | Get single range |
| `cancel_range(user, range_id)` | Cancel provisioning range |

#### Uploads

| Function | Purpose |
|----------|---------|
| `initiate_upload(user, name, filename, file_size)` | Validate, generate presigned URL |
| `complete_upload(user, upload_token, sha256)` | Verify and finalize upload |
| `cancel_upload(user, upload_token)` | Clean up failed upload |

#### User Quota

| Function | Purpose |
|----------|---------|
| `get_storage_used(user)` | Check storage quota |

#### Scenarios

| Function | Purpose |
|----------|---------|
| `list_scenarios(user)` | Get available scenarios |
