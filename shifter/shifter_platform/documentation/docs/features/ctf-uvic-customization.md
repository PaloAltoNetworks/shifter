# CTF UVIC Workshop Customization

Post-provisioning flag replacement for the March 17, 2026 UVIC workshop. Flags baked into AMIs are guessable by LLMs, so we overwrite them via SSM after ranges are provisioned.

## Custom Flags

| Box | Instance Name | User Flag | Root Flag |
|-----|--------------|-----------|-----------|
| WebShell | webdev01 | `FLAG{todo_remove_before_prod}` | `FLAG{never_trust_user_input}` |
| MailRoom | mx-internal | `FLAG{anonymous_access_granted}` | `FLAG{path_less_traveled}` |
| HelpDesk | support-win | `FLAG{password_in_the_share}` | `FLAG{scheduled_for_destruction}` |
| DevBox | ci-runner | `FLAG{dotenv_is_not_a_secret}` | `FLAG{sudo_make_me_a_sandwich}` |
| Vault | backup-dc | `FLAG{backup_operators_unite}` | `FLAG{keys_to_the_kingdom}` |

## Flag File Paths

| Instance | User Flag Path | Root Flag Path |
|----------|---------------|---------------|
| webdev01 | `/home/john/local.txt` | `/root/root.txt` |
| mx-internal | `/home/svc-mail/user.txt` | `/root/root.txt` |
| support-win | `C:\Users\helpdesk\Desktop\user.txt` | `C:\Users\Administrator\Desktop\root.txt` |
| ci-runner | `/home/devops/user.txt` | `/root/root.txt` |
| backup-dc | `C:\Users\vaultadmin\Desktop\user.txt` | `C:\Users\Administrator\Desktop\root.txt` |

## Procedure

Run after all ranges reach `ready`, before the workshop starts.

1. Get all range IDs for the event
2. For each range, get the provisioned instance IDs by name
3. SSM into each victim instance and overwrite the flag files
4. Verify the post-provision overwrite used the intended values above

### Linux boxes (webdev01, mx-internal, ci-runner)

SSM `AWS-RunShellScript` per instance, overwriting the flag file contents.

### Windows boxes (support-win, backup-dc)

SSM `AWS-RunPowerShellScript` per instance, overwriting via `Set-Content`.

## Where Flags Are Displayed

- **Walkthrough page** (`/mission-control/walkthrough/`): Flags are not shown.
- **Organizer guide** (`documentation/docs/features/ctf-organizer-guide.md`): Not shown (organizer uses the walkthrough page or this doc).

## If Flags Need to Change

1. Update the flag source for the event
2. Rebuild the affected AMIs or re-run the SSM overwrite on all victim instances
3. Re-seed CTFd with the same values
