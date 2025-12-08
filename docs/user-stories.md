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
- Receive browser link to Kali desktop when ready
- Range includes: Kali (Kasm), victim EC2 with agent installed

---

### US-3: Destroy Range

**As a** DC done with a demo
**I want to** destroy my range
**So that** I don't incur unnecessary costs

**Acceptance Criteria:**
- Click "Destroy Range" from portal
- Confirmation prompt
- Victim EC2 terminated
- Kasm session ended
- Status updated to "destroyed"

---

### US-4: View Range History

**As a** DC
**I want to** see my past ranges
**So that** I can track my usage

**Acceptance Criteria:**
- List of all ranges (active and destroyed)
- Shows: date created, agent used, status, duration
- Can re-launch with same agent (creates new range)

---

### US-5: Manage Agents

**As a** DC
**I want to** manage my uploaded agents
**So that** I can add/remove agents as needed

**Acceptance Criteria:**
- View list of uploaded agents
- Delete agents no longer needed
- Rename agents
- See which ranges used which agent

---

### US-6: Logout

**As a** DC
**I want to** log out of the portal
**So that** I can secure my session when done

**Acceptance Criteria:**
- Logout button visible on all pages
- Clears session
- Redirects to landing/login page

---

### US-7: Change Password

**As a** DC
**I want to** change my password
**So that** I can maintain account security

**Acceptance Criteria:**
- Link to change password in account/settings
- Redirects to Cognito hosted UI for password change
- Returns to portal after successful change

---

### US-8: Delete Account

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
