# Shifter: Technical Sellers Guide (SEs/SCs)

**Launch Date**: December 18, 2025 | **Your Role**: Hands-On Demo Execution

---

## What You're Getting

A **self-service cyber range platform** that lets you run live AI-driven attack demonstrations against XDR/XSIAM-protected infrastructure. Everything runs in your browser—no local setup, no infrastructure tickets, no waiting.

**Bottom line**: 10-minute setup, 30-minute demo, massive customer impact.

---

## Quick Start (First Demo in 30 Minutes)

### Step 1: Portal Access (5 minutes)
1. Log into Shifter portal: `https://[portal-url]`
2. Upload your XDR/XSIAM agent installer
   - Use customer's agent (shows their detections)
   - Or use demo tenant agent
3. Give it a name (e.g., "Acme Corp XDR")

### Step 2: Launch Range (5 minutes)
1. Click "Launch Range"
2. Select which agent to use
3. Wait for provisioning (~3-5 minutes)
4. Portal shows "Range Ready" + link to control interface

### Step 3: Run Demo (30 minutes)
1. Click "Open Range" → LibreChat interface opens
2. **Chat 1**: "Set up a vulnerable web application with command injection"
3. AI autonomously configures victim VM
4. **Chat 2**: "Exploit the vulnerability and gain root access"
5. AI runs autonomous attack
6. Show XDR detections in customer's tenant as they appear

### Step 4: Cleanup (2 minutes)
1. Return to portal
2. Click "Destroy Range"
3. Done—no cleanup needed

---

## Platform Overview

### What You Control
- **Launch**: Start/stop ranges on demand
- **Agent**: Choose which customer's XDR agent to use
- **Scenarios**: Tell the AI what to do (plain English)
- **Monitoring**: Watch XDR detections in real-time

### What Runs Automatically
- **Infrastructure**: AWS spins up isolated VPC, victim VM
- **AI Agent**: Autonomous attack execution via LibreChat
- **XDR Agent**: Installed on victim, sends telemetry to tenant
- **Cleanup**: Destroy range = everything deleted

### Architecture (Simplified)
```
You → Portal → Range Provisioning
              ↓
         LibreChat (AI + Tools)
              ↓
         Victim VM (with XDR agent)
              ↓
         Customer's XDR Tenant (detections)
```

---

## Demo Scenarios Library

### Scenario 1: Basic Web Exploitation (30 min)
**Customer**: First-time XDR demo, basic security team

**Steps**:
1. "Deploy a vulnerable web application with SQL injection"
2. AI sets up app, confirms it's running
3. "Exploit the SQL injection to dump the database"
4. AI autonomously finds and exploits vulnerability
5. Show XDR detections: process creation, file access, network activity

**Value Message**: "See how XDR detects the entire attack chain, not just individual events"

---

### Scenario 2: Privilege Escalation Chain (40 min)
**Customer**: Sophisticated security team, advanced XDR features

**Steps**:
1. "Create a Linux system with a local privilege escalation vulnerability"
2. "Start as a low-privilege user and escalate to root"
3. AI exploits kernel vulnerability or misconfiguration
4. "Install persistence mechanism"
5. Show XDR detections: anomalous behavior, privilege changes, persistence

**Value Message**: "XDR correlates multi-step attacks, not just isolated incidents"

---

### Scenario 3: Data Exfiltration (35 min)
**Customer**: Data protection concerns, compliance requirements

**Steps**:
1. "Set up a file server with sensitive data"
2. "Gain access to the server"
3. "Locate and exfiltrate sensitive files"
4. AI navigates filesystem, identifies targets, attempts exfiltration
5. Show XDR detections: file access, data movement, network connections

**Value Message**: "XDR protects your data at every stage of an attack"

---

### Scenario 4: AI vs. AI (45 min)
**Customer**: Executive audience, AI threat awareness

**Steps**:
1. Explain: "This is an autonomous AI agent—no scripts, no manual commands"
2. "Reconnaissance the target and find attack vectors"
3. AI autonomously scans, identifies vulnerabilities
4. "Exploit what you found and establish access"
5. Show XDR: "Your AI (XDR) is detecting their AI (attacker)"

**Value Message**: "AI-driven attacks are real. You need AI-powered defense."

---

## Technical Details

### Prerequisites
- **Your side**: Browser, XDR tenant access, agent installer file
- **Customer side**: XDR tenant (their own) or demo tenant
- **Network**: Customer just needs browser, everything else is in AWS

### Range Components
| Component | What It Does |
|-----------|--------------|
| Victim VM | Ubuntu 22.04 EC2 with XDR agent |
| LibreChat | Browser-based AI interface |
| MCP Tools | SSH, file ops, command execution for AI |
| Isolation | No internet egress, isolated VPC |

### Security & Compliance
- **Isolated**: No internet access from victim VMs
- **Logged**: All AI actions audited
- **Customer data**: Never leaves their XDR tenant
- **Destroy**: Complete cleanup when done

---

## Advanced Techniques

### Custom Scenarios
The AI is flexible—you can request custom attacks:
- "Set up a Windows Active Directory environment" (future)
- "Create a misconfigured Docker container"
- "Deploy a vulnerable API endpoint"
- "Simulate a supply chain attack"

### Multi-Step Attacks
Chain together complex scenarios:
1. Initial access (web exploit)
2. Lateral movement (pivot to internal host)
3. Privilege escalation (get admin)
4. Persistence (install backdoor)
5. Data access (exfiltrate files)

Each step generates XDR detections—shows correlation power.

### Customer Customization
Use customer-specific scenarios:
- Their industry (finance, healthcare, retail)
- Their tech stack (ask about their environment)
- Their concerns (ransomware, data theft, insider threats)

---

## Demo Best Practices

### Pre-Demo Checklist
- ✅ Portal access tested
- ✅ XDR agent uploaded
- ✅ Customer XDR tenant access confirmed
- ✅ Scenario planned (what you'll show)
- ✅ Backup plan (if something fails)

### During Demo
- 🎯 **Set expectations**: "You'll see real attacks, real detections"
- 🎯 **Let AI work**: Don't interrupt—autonomous is the feature
- 🎯 **Narrate**: Explain what AI is doing as it works
- 🎯 **Show XDR**: Switch to XDR console as detections appear
- 🎯 **Connect to value**: "This is what adversaries are doing today"

### Common Mistakes to Avoid
- ❌ Over-explaining technical details (focus on business value)
- ❌ Rushing the demo (let it breathe, let detections appear)
- ❌ Ignoring XDR tenant (that's where the value is)
- ❌ Not preparing for questions (know your scenarios)

---

## Troubleshooting

### Range Won't Provision
- **Wait**: Initial provision can take 5-7 minutes
- **Check status**: Portal shows provisioning progress
- **Retry**: Destroy and re-launch if stuck >10 minutes
- **Escalate**: Contact Shifter support if persistent

### AI Not Responding
- **Refresh**: Reload LibreChat interface
- **Check agent**: Ensure AI has MCP tools loaded
- **Rephrase**: Try different phrasing for instruction
- **Manual fallback**: Use recorded demo if needed

### XDR Detections Not Appearing
- **Wait**: Detections can take 1-2 minutes to show
- **Verify agent**: Check XDR console for agent status
- **Check tenant**: Ensure viewing correct tenant
- **Filter settings**: Adjust XDR filters/time range

### Customer's Network Blocks Portal
- **Hotspot**: Use phone as backup internet
- **VPN**: Customer may need to allow portal domain
- **Reschedule**: Demo from different location

---

## Objection Handling

**"This isn't a real attack"**
→ "These are real techniques attackers use. The AI uses actual exploitation tools. Your XDR detections are production-grade."

**"Our environment is different"**
→ "The attack principles are universal. We can customize scenarios to match your environment."

**"What about false positives?"**
→ "These are confirmed malicious activities. XDR tunes out noise and shows real threats."

**"Can we break out of the sandbox?"**
→ "No internet egress, isolated VPC. It's designed to be secure."

---

## After the Demo

### Immediate Follow-Up (Same Day)
- Email customer with detection summary
- Propose next steps (POC, expanded testing)
- Answer any technical questions
- Update opportunity in CRM

### Documentation
- Log demo in CRM with scenario used
- Note customer reactions and questions
- Share wins with team (weekly SE meeting)
- Contribute to scenario library

### Continuous Improvement
- What worked well?
- What customer questions surprised you?
- How could the demo be better?
- Share feedback with Shifter team

---

## Success Metrics (Your Targets)

- **Demos per week**: 3-5
- **Conversion rate**: 40%+ demo → POC
- **Customer satisfaction**: 4.5/5
- **Setup time**: <10 minutes
- **Demo duration**: 30-40 minutes

Track these in CRM to show your impact.

---

## Resources & Support

### Training
- **Initial enablement**: 2-hour session (schedule with manager)
- **Practice demos**: Run 2 internal demos before customer-facing
- **Weekly clinics**: Share tips and new scenarios with team

### Documentation
- **Scenario library**: Pre-built attack scenarios
- **Troubleshooting guide**: Common issues and fixes
- **Video tutorials**: Platform walkthrough

### Support
- **Technical issues**: Shifter support team
- **Sales questions**: Your SE manager
- **Product feedback**: Submit via portal

---

## Your Action Plan

### This Week
1. ✅ Get portal access
2. ✅ Upload demo XDR agent
3. ✅ Run practice demo (internal)
4. ✅ Schedule first customer demo

### This Month
1. ✅ Complete 5 customer demos
2. ✅ Master 2-3 scenarios
3. ✅ Document customer feedback
4. ✅ Share one win with team

### This Quarter
1. ✅ Integrate Shifter into standard demo flow
2. ✅ Build custom scenarios for your accounts
3. ✅ Mentor other SEs on best practices
4. ✅ Track impact on your deal velocity

---

**Platform Access**: https://[portal-url]
**Support**: [Support email/Slack]
**Launch Date**: December 18, 2025

**Let's show customers what XDR can really do. 🚀**
