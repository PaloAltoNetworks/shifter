# CTF Design Research Notes

Research compiled March 2026 to inform the design of a 4-hour, mixed-skill, AI-assisted CTF for 50-100 participants. Sources include CTFd documentation, SANS, Hack The Box, PicoCTF, Dragos CTF, DEFCON, academic research on AI-assisted pentesting, and CTF organizer guides.

---

## 1. CTF Format Selection

### Format Options

| Format | Description | Best For |
|--------|-------------|----------|
| Jeopardy | Independent challenges across categories, solve in any order | Mixed-skill audiences, flexibility |
| Attack-Defense | Teams attack others while defending their own infrastructure | Homogeneous skill, long events |
| Boot2Root | Vulnerable machines to fully compromise (user + root) | Pentest training, realistic scenarios |
| Hybrid | Boot2Root machines + Jeopardy-style standalone challenges | Best of both worlds |

### Recommendation for This Event

**Hybrid Boot2Root** -- the same format as the UVic scenario but scaled up. Each participant gets an isolated range with multiple vulnerable machines. The Boot2Root format maps directly to real-world pentesting (enumerate, exploit, escalate, capture flag) and works naturally with AI assistants like Claude Code.

Key design rule from the CTF community: **never allow direct remote-to-root** -- always force at least one escalation step. This creates a two-flag-per-box pattern (user flag + root flag) that doubles engagement and scoring granularity.

---

## 2. Difficulty Tier Design

### Industry Standard: CTFd 6-Level Framework

| Level | Name | Description | Skills Required |
|-------|------|-------------|-----------------|
| L0 | Beginner | Solvable with Google, no prior security knowledge | Basic computer literacy |
| L1 | Easy | Requires some security knowledge or tool usage | Run nmap, read output, follow instructions |
| L2 | Medium | Requires combining multiple techniques | Chain exploits, enumerate services, basic privesc |
| L3 | Hard | Requires deep technical knowledge | Custom exploitation, non-obvious attack chains |
| L4 | Expert | Requires specialized expertise | Advanced Windows, AD, binary exploitation |
| L5 | Insane | May require novel research or tooling | Zero-day style, custom tooling |

### Hack The Box Machine Difficulty (Boot2Root Specific)

| Difficulty | Attack Chain Steps | Typical Techniques |
|------------|-------------------|-------------------|
| Easy | 2-3 steps | Known CVE, default creds, basic privesc (sudo, SUID) |
| Medium | ~3 steps | Chained vulns, moderate enumeration, service-specific exploits |
| Hard | 3-5 steps | Custom exploitation, pivoting, multi-service chains |
| Insane | 5+ steps | Novel techniques, heavy enumeration, rabbit holes |

### Practical Tier Mapping for This Event

Four tiers is the consensus sweet spot for a mixed-audience event:

| Tier | Label | Maps To | Audience Segment |
|------|-------|---------|-----------------|
| 1 | Walkthrough | CTFd L0-L1 | No experience, follows guided prompts |
| 2 | Easy | CTFd L1-L2 | Some tech background, guided by AI |
| 3 | Medium | CTFd L2-L3 | Security practitioners, IT professionals |
| 4 | Hard | CTFd L3-L4 | Experienced pentesters, nat-sec cyber operators |

**Note**: We intentionally cap at L4 (Hard), not L5 (Insane). Insane-level challenges in a 4-hour event with AI assistance would still likely go unsolved and waste AMI build effort. Hard challenges with non-obvious attack chains will challenge even experienced operators using AI.

---

## 3. Timing and Completion Data

### Time Per Challenge (Human, No AI)

**Boot2Root machines (experienced practitioner)**:

| Difficulty | Time to User Flag | Time to Root Flag | Total |
|------------|------------------|------------------|-------|
| Easy | 15-30 min | 15-30 min | 30-60 min |
| Medium | 30-60 min | 30-60 min | 60-120 min |
| Hard | 60-120 min | 60-120 min | 2-4 hours |
| Insane | 2-4 hours | 2-8 hours | 4-12+ hours |

**Per-phase breakdown (experienced practitioner)**:

| Phase | Time Range |
|-------|-----------|
| Port scanning (fast scan) | 2-10 min |
| Web/service enumeration | 15-45 min |
| Vulnerability identification | 15-60 min |
| Initial exploitation to user flag | 15-120 min |
| Privilege escalation enumeration | 15-30 min |
| Privesc execution to root | 15-60 min |

### AI Impact on Timing

This is the most critical factor for our event design. Key research findings:

| Source | Finding |
|--------|---------|
| HTB longitudinal study (423 machines, 2017-2025) | Root blood times declined 16%/year; post-LLM (Nov 2022): 27% compression at Hard, 67% at Insane |
| PentestGPT (GPT-4) | Solved 86% Easy, 50% Medium, 0% Hard HTB machines |
| CAI at Dragos OT CTF | 37% faster point velocity than top-5 human teams |
| HTB AI vs Humans CTF | AI teams solved 95% of challenges, matched top human speed |
| Anthropic research | Claude placed top 3% at PicoCTF (32/41 challenges) |
| General estimate | AI assistance reduces solve time 30-50% on Easy/Medium, diminishing returns on Hard |

**Practical implication**: With AI assistance, treat our Easy boxes as ~15-25 min, Medium as ~30-50 min, and Hard as ~60-90 min for an experienced user. Beginners with AI will be slower but still faster than beginners without AI.

### Estimated Time Per Box (AI-Assisted, This Event)

| Tier | Beginner w/ AI | Intermediate w/ AI | Expert w/ AI |
|------|---------------|-------------------|-------------|
| Walkthrough | 15-25 min (guided) | 10-15 min | 5-10 min |
| Easy | 30-45 min | 15-25 min | 10-15 min |
| Medium | 45-75 min (may not root) | 25-40 min | 15-25 min |
| Hard | Likely stuck | 45-75 min | 25-45 min |

### Completion Rates (Mixed-Skill Events)

| Difficulty | Expected Completion Rate |
|------------|------------------------|
| Walkthrough | 90-95% (guided) |
| Easy | 60-80% |
| Medium | 25-50% |
| Hard | 5-15% |

From Dragos CTF 2024 (819 teams): Easy+Normal challenges accounted for ~80% of all solves. Expert+Extreme accounted for only ~6%.

Score distributions consistently follow a heavy long-tail: most participants solve the walkthrough + 1-3 easy challenges, a thin middle band completes medium challenges, and fewer than 5% clear hard content.

---

## 4. Mixed-Skill Audience Design

### Expected Skill Distribution

For a government/national security audience of 50-100:

| Segment | Percentage | Description |
|---------|-----------|-------------|
| True beginners | 15-20% | No security background, first CTF |
| Guided beginners | 20-25% | Some IT/dev background, can follow instructions |
| Intermediate | 30-35% | Security practitioners, some pentest exposure |
| Advanced | 15-20% | Active pentesters, CTF veterans |
| Expert | 5-10% | Nat-sec cyber operators, red teamers |

**Key insight from All-Army CyberStakes** (2,049 military participants): Even in a military audience, they deliberately created 22 introductory challenges because accessibility matters. 38,663 total solves, meaning heavy participation at lower tiers.

### Design Principles for Mixed Audiences

**From PicoCTF research (statistically proven, p < 0.046)**: Adding more introductory/intermediate challenges increases engagement and reduces dropout.

**From SANS Holiday Hack Challenge**: Every challenge has an easy mode (silver) and hard mode (gold), organized into progressive acts. Participants can play through or skip. Micro-challenges (10-15 min each) provide quick wins; capstones provide depth.

**Critical rule**: "The biggest mistake organizers make with general audience CTFs is jumping straight into technical challenges." -- MetaCTF Guide

### Engagement Strategy by Skill Level

| Skill Level | Strategy |
|-------------|----------|
| Beginners | Walkthrough box first (group), then easy boxes with AI assistance. Goal: solve 2-4 boxes. |
| Intermediate | Walkthrough (quick), then work through easy and medium boxes. Goal: solve 4-6 boxes. |
| Advanced | Skip or speed through walkthrough/easy, focus on medium and hard. Goal: solve 6-10 boxes. |
| Expert | Speed through everything, compete for first blood on hard boxes. Goal: clear all or nearly all. |

### The "First 15 Minutes" Rule

Every participant must solve something in the first 15 minutes. This is the single most important engagement factor. The walkthrough box serves this purpose -- it's a guided, guaranteed success experience that teaches the basic pattern.

---

## 5. Scoring for Mixed Audiences

### Recommended: Dynamic Scoring

CTFd's parabolic dynamic scoring is industry standard. Points start high and decrease as more people solve a challenge. This self-balances difficulty: easy challenges that everyone solves become worth less, while hard challenges that few solve retain high value.

| Feature | Recommendation |
|---------|---------------|
| Base scoring | Dynamic (CTFd parabolic formula) |
| User flag | 100 base points |
| Root flag | 200 base points |
| First blood bonus | Small (+25-50 points) -- keep small for mixed audiences |
| Hints | Available, cost 10% of challenge value (OWASP Juice Shop model) |
| Walkthrough scoring | Does not count toward leaderboard (same as UVic) |

### Two-Flag Pattern

Maintaining the UVic pattern of user flag + root flag per box is correct. It:
- Doubles scoring granularity
- Gives partial credit for getting user access without root
- Creates natural milestones within each box
- Allows beginners to score points even if they can't escalate to root

---

## 6. Challenge Categories for Pentest CTF

The research consensus for a pentest-focused Boot2Root CTF:

| Category | Description | Relevance |
|----------|-------------|-----------|
| Web exploitation | SQL injection, command injection, file inclusion, web shells | Core -- every CTF should include |
| Linux privilege escalation | SUID, sudo misconfig, cron jobs, PATH hijack, kernel exploits | Core |
| Windows exploitation | SMB, RDP, scheduled tasks, service misconfig, registry | Core -- especially for enterprise audience |
| Network enumeration | Port scanning, service identification, banner grabbing | Foundational |
| Credential discovery | Password files, config files, hardcoded creds, password reuse | Realistic |
| Active Directory | Kerberoasting, AS-REP roasting, delegation abuse | Advanced -- very relevant for nat-sec |
| Container/cloud | Docker escape, AWS metadata, SSRF to cloud | Modern/relevant |
| Binary exploitation | Buffer overflow, format string, ROP | Traditional CTF but less relevant for this audience |

### Category Distribution for This Event

Given the audience (nat-sec, PANW customers, mixed skill):
- **Web + Linux privesc**: The bulk of easy/medium boxes (accessible, well-understood)
- **Windows + credential reuse**: Medium boxes (enterprise-relevant)
- **Active Directory**: Hard tier (the crown jewel for advanced operators)
- **Container/cloud**: Optional medium-hard (modern, relevant)

---

## 7. Infrastructure Considerations (50-100 Participants)

### Per-Participant Resource Model

The UVic scenario uses 5 target boxes + 1 Kali per participant range. Scaling up:

| Boxes Per Range | 50 Participants | 100 Participants |
|-----------------|----------------|-----------------|
| 5 (UVic model) | 300 instances | 600 instances |
| 8 | 450 instances | 900 instances |
| 10 | 550 instances | 1100 instances |
| 12 | 650 instances | 1300 instances |

### Provisioning Time

From the UVic scenario: ~5-10 min per range, throttled. At 100 ranges this means significant pre-provisioning time. Ranges must be provisioned well before the event.

### Cost Considerations

More boxes per range = more EC2 cost per hour. For a 4-hour event:
- Small Linux instances (t3.micro/small): ~$0.01-0.02/hr each
- Windows instances (t3.medium+): ~$0.04-0.08/hr each
- Kali instances (t3.medium): ~$0.04/hr each

Budget will be a factor in determining the final box count.

### Support Staffing

Research recommends 1 helper per 15-20 participants. For 100 participants: 5-7 support staff. The AI assistant (Claude Code on each Kali box) significantly reduces the support burden for technical questions.

---

## 8. AI-Assisted CTF Design Implications

### How AI Changes the Game

| Aspect | Without AI | With AI |
|--------|-----------|---------|
| Enumeration | Manual nmap, gobuster, etc. | AI runs tools, interprets output |
| Vulnerability ID | Requires knowledge | AI suggests based on findings |
| Exploit selection | Research + experience | AI recommends exploits |
| Privilege escalation | GTFOBins lookup, manual enum | AI automates linpeas/winpeas analysis |
| Beginners | Stuck without knowledge | AI acts as teacher/guide |
| Experts | Limited by typing speed | AI acts as force multiplier |

### Design Adjustments for AI-Assisted CTF

1. **Increase challenge count by 30-50%** vs a non-AI event (participants solve faster)
2. **Upshift difficulty by ~1 tier** (AI makes Easy trivial, so provide more Medium/Hard)
3. **Include AI-resistant elements**: Custom binaries, non-standard configurations, multi-step logic chains where context matters
4. **Embrace the human+AI model**: Beginners use AI as teacher, intermediate as tool, experts as speed multiplier
5. **Don't fight the AI**: Design challenges that are interesting *with* AI, not ones that try to trick it

### What AI Struggles With (Design Hard Boxes Around These)

- GUI-dependent interactions (RDP-only exploitation)
- Novel/unpublished vulnerability patterns
- Long attack chains requiring maintained context
- Social engineering / phishing (not applicable here)
- Non-standard service configurations that don't match training data
- Active Directory attacks with multiple domain trust relationships

---

## Sources

### CTF Design and Organization
- CTFd Documentation: Challenge Levels, Categories, Dynamic Scoring, Success Guide
- ENISA: Capture-The-Flag Competitions guide
- MetaCTF: Comprehensive Guide to Hosting a CTF
- Hats Off Security: How to Create a Good Security CTF
- abatchy: Tips on Creating Boot2Root Vulnerable VMs
- hackrocks: Tips and Tactics for Creating Your Own CTF

### Competition Data and Statistics
- Dragos CTF 2024 Results (819 teams, 37 challenges)
- Dragos CTF 2025 Results (1,200+ teams, 33 challenges)
- DownUnderCTF 2020 Statistics (1,400 teams, 56 challenges)
- HackTheBox AI vs Human CTF Results (403 human teams)
- All-Army CyberStakes (2,049 participants)
- National Cyber League (13,000+ participants/year)

### AI-Assisted Pentesting Research
- HackTheBox: AI vs Human CTF Results (2025)
- Security Boulevard: The Death of the CTF -- How Agentic AI Is Reshaping Competitive Hacking (2026)
- Anthropic: Building AI for Cyber Defenders; Cyber Competitions
- PentestGPT: LLM-empowered Penetration Testing (USENIX Security 2024)
- CAI: Insights from an AI Top-10 Ranker in Dragos OT CTF
- ARTEMIS: Comparing AI Agents to Cybersecurity Professionals
- NYU CTF Bench; CSAW Agentic Automated CTF
- HTB longitudinal study (423 machines, 2017-2025)

### Mixed-Skill Event Design
- SANS Holiday Hack Challenge structure and design
- PicoCTF and pico-Boo! CISSE research paper (statistical evidence)
- National Cyber League Competition Manual (5 divisions, 4 tiers)
- DoD Cyber Sentinel Skills Challenge; DoD Cyber Red Zone paper
- OWASP Juice Shop CTF Hosting Guide (hint cost model)

### Infrastructure
- Deploying Secure and Scalable CTF Environments on AWS
- Scalable CTF Infrastructure on GCP
- How to Run a CTF That Survives the First 5 Minutes
