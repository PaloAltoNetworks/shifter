# User Stories

Post-authentication user flows for Domain Consultants.

## Core Flow

### US-1: First-Time User Setup

**As a** DC logging in for the first time
**I want to** upload my XDR/XSIAM agent installer
**So that** I can use it when launching ranges

**Acceptance Criteria:**
- User sees empty agent list after first login
- Can upload agent installer file (.msi, .sh, etc.)
- Must provide a name (e.g., "Acme Corp XSIAM")
- File stored in S3, reference saved to user's account
- Can upload multiple agents (different customers)

---

### US-2: Launch Range

**As a** DC with at least one uploaded agent
**I want to** launch a cyber range with one click
**So that** I can start demoing without infrastructure setup

**Acceptance Criteria:**
- Select which agent to install on victim
- Click "Launch Range"
- See provisioning status (spinner/progress)
- Receive browser link to chat interface when ready
- Range includes: victim EC2 with agent installed, LibreChat with MCP access

---

### US-3: Destroy Range

**As a** DC done with a demo
**I want to** destroy my range
**So that** I don't incur unnecessary costs

**Acceptance Criteria:**
- Click "Destroy Range" from portal
- Confirmation prompt
- Victim EC2 terminated
- LibreChat user removed
- Status updated to "destroyed"

---

### US-4: Pause Range

**As a** DC taking a break from a demo
**I want to** pause my range
**So that** I can reduce costs without losing my setup

**Acceptance Criteria:**
- Click "Pause Range" from portal
- Victim EC2 stopped (not terminated)
- Status updated to "paused"
- Can resume range later (EC2 starts)
- Paused ranges still count toward any limits

---

### US-5: Resume Range

**As a** DC returning to a paused demo
**I want to** resume my range
**So that** I can continue where I left off

**Acceptance Criteria:**
- Click "Resume Range" from portal (only visible for paused ranges)
- Victim EC2 started
- Status updated to "ready"
- Chat interface accessible again

---

### US-6: View Range History

**As a** DC
**I want to** see my past ranges
**So that** I can track my usage

**Acceptance Criteria:**
- List of all ranges (active and destroyed)
- Shows: date created, agent used, status, duration
- Can re-launch with same agent (creates new range)

---

### US-7: Manage Agents

**As a** DC
**I want to** manage my uploaded agents
**So that** I can add/remove agents as needed

**Acceptance Criteria:**
- View list of uploaded agents
- Delete agents no longer needed
- Rename agents
- See which ranges used which agent

---

### US-8: Logout

**As a** DC
**I want to** log out of the portal
**So that** I can secure my session when done

**Acceptance Criteria:**
- Logout button visible on all pages
- Clears session
- Redirects to landing/login page

---

### US-9: Change Password

**As a** DC
**I want to** change my password
**So that** I can maintain account security

**Acceptance Criteria:**
- Link to change password in account/settings
- Redirects to Cognito hosted UI for password change
- Returns to portal after successful change

---

### US-10: Delete Account

**As a** DC
**I want to** delete my account
**So that** my data is removed when I no longer need the service

**Acceptance Criteria:**
- Link in account/settings
- Confirmation prompt with warning
- Destroys any active ranges
- Deletes all uploaded agents from S3
- Removes user from Cognito
- Removes user record from database

---

### US-11: Get Help

**As a** DC
**I want to** access help and documentation
**So that** I can learn how to use Shifter and troubleshoot issues

**Acceptance Criteria:**
- Help link visible in navigation or header
- Quick start guide for first-time users
- Documentation on how to upload agents
- Documentation on launching/managing ranges
- FAQ for common issues
- Contact/support info for further assistance

---

### US-12: Change Language

**As a** DC
**I want to** change the interface language
**So that** I can use Shifter in my preferred language

**Acceptance Criteria:**
- Language selector in settings
- Persists language preference across sessions
- All UI text translatable
- Initially supported: English (default)
- Additional languages added based on demand

---

### US-13: Receive Notifications

**As a** DC
**I want to** receive notifications about my range status
**So that** I know when my range is ready or requires attention

**Acceptance Criteria:**
- Notification when range provisioning completes
- Notification when range is destroyed (manual or auto-timeout)
- Notification if range encounters an error
- In-app notifications visible in Mission Control
- Optional: email notifications for critical events
