# CTF Design Research: Best Practices for Cybersecurity Competitions

Research compiled March 2026. Sources from SANS, Hack The Box, TryHackMe, CTFd, PicoCTF,
DEFCON, Dragos, Anthropic, and CTF organizer communities.

---

## 1. CTF Structure and Format

### Three Primary Formats

**Jeopardy-Style**: Standalone challenges across categories (web, crypto, forensics, etc.) with
varying point values. Teams solve independently. Best for mixed-skill audiences and large
participant counts. Easiest to organize and scale.

**Attack-Defense**: Teams defend their own vulnerable systems while attacking opponents. Requires
real-time coordination, deeper infra, and more homogeneous skill levels. Not suitable for
beginners or short events.

**Boot2Root / Pentest-Style**: Participants attack vulnerable machines following a realistic
penetration testing methodology. The canonical attack chain is:

1. **Reconnaissance** -- Port scanning (nmap), service discovery
2. **Enumeration** -- Directory brute-forcing (gobuster), service fingerprinting, user enumeration
3. **Initial Access / Exploitation** -- Exploiting a vulnerability to get a shell (remote -> local)
4. **Privilege Escalation** -- Escalating from low-privilege user to root/admin
5. **Flag Capture** -- Reading flag file (typically `/root/flag.txt` or similar)

The key design rule for Boot2Root: **never allow remote -> root directly**. The minimum path
should be remote -> local user -> root. Multi-step chains create the learning experience.

### Best Format for a 4-Hour Mixed-Skill Event

**Jeopardy-style with embedded Boot2Root machines** is the consensus recommendation. This gives
beginners quick wins on standalone challenges while giving experienced participants full
machines to root. The Jeopardy wrapper provides structure and scoring while the machines
provide depth.

---

## 2. Difficulty Scaling

### CTFd's Six-Tier Framework (Industry Standard)

| Level | Name | Points | Description | Prerequisite Knowledge |
|-------|------|--------|-------------|----------------------|
| 0 | Trivial | < 100 | No technical knowledge needed. Google-solvable. | None |
| 1 | Easy | 100-199 | Basic tool usage. Simple research leads to solution. | Minimal |
| 2 | Beginner | 200-299 | Single vulnerability knowledge. May copy-paste from internet. | Basic |
| 3 | Intermediate | 300-399 | Multiple vulnerability layers. Cannot just copy-paste. | Moderate |
| 4 | Advanced | 400-499 | Real-world application of vulnerabilities. | Strong |
| 5 | Expert | 500+ | Deep expertise, novel CVEs, nothing auto-discoverable. | Expert |

### Hack The Box Machine Difficulty (Historic Reference)

| Difficulty | Steps | Characteristics |
|-----------|-------|-----------------|
| Easy | 2-3 | Known CVE, clear path, no rabbit holes, minimal scripting |
| Medium | ~3 | Straightforward custom exploitation, simple scripting |
| Hard | 3-5 | Custom exploitation, vulnerability chaining, complex concepts |
| Insane | 5+ (or 3 very hard) | Any exploitation approach, purposeful rabbit holes |

### VulnHub Boot2Root Difficulty

| Difficulty | Characteristics |
|-----------|----------------|
| Very Easy | No privesc needed, exploits work out-of-box |
| Easy | Single exploit for access + one for escalation |
| Medium | Multiple vulnerability chains, sysadmin knowledge required |
| Hard | Long chain of vulns, encryption, pivoting |
| Very Hard | Multiple chained vulns in novel ways, unknown techniques |

### Recommended Distribution for a Mixed-Skill Event

Based on cross-referencing multiple sources, the following distribution maximizes engagement:

| Tier | % of Total Challenges | Purpose |
|------|----------------------|---------|
| Trivial/Warm-up (L0) | 10-15% | Confidence builders, ensure everyone scores |
| Easy (L1) | 20-25% | Build momentum, teach basic tools |
| Beginner (L2) | 20-25% | Core learning, single-vuln challenges |
| Intermediate (L3) | 20-25% | Multi-step, keeps mid-tier engaged |
| Advanced (L4) | 10-15% | Separator for experienced participants |
| Expert (L5) | 5-10% | Summit challenges, may go unsolved |

**Key insight from Dragos CTF data**: Easy and Normal challenges accounted for ~80% of all
solves. Expert and Extreme challenges accounted for only ~6% of solves. Design accordingly --
the bulk of your challenges should be accessible.

---

## 3. Timing and Pacing

### Time Estimates Per Difficulty (Synthesized from Multiple Sources)

No single source publishes canonical times, but cross-referencing competition data, Hack The
Box machine data, and SANS micro-challenge design yields these working estimates:

| Difficulty | Estimated Time (Experienced) | Estimated Time (Beginner) |
|-----------|------------------------------|--------------------------|
| Trivial (L0) | 2-5 min | 5-15 min |
| Easy (L1) | 10-20 min | 20-45 min |
| Beginner (L2) | 15-30 min | 30-60 min |
| Intermediate (L3) | 30-60 min | 1-2 hours |
| Advanced (L4) | 1-2 hours | 2-4+ hours |
| Expert (L5) | 2-4+ hours | May not complete |

**SANS Holiday Hack micro-challenges**: Explicitly designed to take 10-15 minutes or less.
This is a proven model for keeping beginners engaged.

**Dragos CTF reference data**: Winning team completed 47 challenges in 31 hours 39 minutes
(~40 min average per challenge, across all difficulties).

### Pacing for a 4-Hour Event

For a 4-hour event with 20-25 total challenges:

- **Hour 1**: Participants should be able to solve 3-5 challenges (warm-ups + easy)
- **Hour 2**: Mid-tier participants hitting intermediate challenges
- **Hour 3**: Experienced participants working advanced challenges, beginners still finding
  easy/beginner challenges they missed
- **Hour 4**: Experts attempting summit challenges, mid-tier finishing intermediates

**Critical**: Release all challenges at start (do not drip-feed for a 4-hour event). Let
participants self-select difficulty. For longer events (24-48h), staged release can maintain
momentum.

### Expected Completion Rates

From the Dragos CTF (819 teams, 37 challenges, 48 hours):
- **0.24%** of teams completed all challenges
- **80%** of correct submissions were on Easy/Normal challenges
- **80.26%** of all flag submissions were incorrect

For a 4-hour event with 50-100 participants:
- Expect top 5-10% to solve 70-80% of challenges
- Expect middle 30-40% to solve 30-50% of challenges
- Expect bottom 30-40% to solve 10-25% of challenges
- Expect 5-10% to solve fewer than 3 challenges (at risk of disengagement)

---

## 4. Mixed-Skill Audiences

### How Leading Events Handle This

**PicoCTF (CMU)** -- Gold standard for accessibility:
- Provides all necessary tools to every participant (no "bring your own Kali" barrier)
- "On-ramp" challenges in almost every category
- Hints and learning resources embedded in challenges
- Progressive difficulty within each category
- 2025 competition: 10,460 teams participated

**SANS Holiday Hack Challenge** -- Best-in-class for mixed audiences:
- **Micro-challenges** (10-15 min) for quick wins and fundamentals
- **Capstone "big boss" puzzles** for multi-hour deep dives
- **Play-through mode**: Skip any challenge and advance the story, come back later
- **CTF-only mode**: Skip narrative, go straight to technical challenges
- **Holographic Santa hint system**: In-context hints without spoilers
- **Published walkthroughs**: Official solutions released before event closes

**Hack The Box CTF Platform**:
- Live scoreboards and team chats as engagement features
- Customizable difficulty based on target audience
- Scales to thousands of players

**DEFCON CTF Qualifiers** -- Expert-only reference point:
- 48-hour format, open registration
- 2024: 1,828 teams registered, 535 solved at least one challenge (29%)
- This is NOT a model for mixed audiences -- it self-selects for experts

### Best Practices for Wide Skill Ranges

1. **Start with non-technical warmups**: Security awareness questions anyone can answer.
   Biggest mistake is jumping straight into technical challenges.

2. **Provide on-ramps per category**: Each challenge category should have at least one L0-L1
   challenge so participants can taste every domain.

3. **Pair experienced with beginners**: Mentorship model where experts help newcomers.

4. **Walkthrough challenges alongside challenge challenges**: TryHackMe's model of "walkthrough
   rooms" (guided, step-by-step) alongside "challenge rooms" (unguided) works well.

5. **Multiple flag types per machine**: For Boot2Root, place a user flag AND a root flag.
   Getting user-level access is a win for beginners even if they cannot escalate.

6. **Discord/chat support channel**: The Dragos CTF fielded ~1,000 support requests via
   Discord across 48 hours. For 50-100 participants in 4 hours, expect 50-100 support
   interactions.

---

## 5. Engagement and Retention

### Preventing Beginner Frustration

1. **Graduated difficulty ramp**: "Gradually increase challenge difficulty to avoid frustration
   and burnout" -- once a participant has invested time, they are less likely to leave.

2. **Layered hints**: Progressive hint system where each hint reveals more detail. PicoCTF
   uses embedded hints that do not penalize score. Consider a point-cost hint system (e.g.,
   buying a hint costs 10-25% of the challenge value).

3. **No guessing games**: "Make sure there is no step in your challenge's intended solution
   that requires someone to purely guess from a large number of possibilities or do some
   obscure pattern recognition." This is the number one frustration source.

4. **Clear flag format**: Use a consistent format like `flag{description}` so participants
   know when they have found something valid. Ambiguous formats (raw hashes, etc.) cause
   confusion.

5. **Quick first win**: Design the event so every participant solves at least one challenge
   in the first 15 minutes. This creates psychological investment.

6. **SANS micro-challenge model**: 15+ bite-sized challenges designed to take 10-15 minutes.
   Quick wins build confidence.

### Preventing Expert Boredom

1. **Summit challenges**: Include 2-3 challenges that may go unsolved. Experts need something
   to strive for.

2. **Dynamic scoring**: Use CTFd's dynamic scoring where challenge values decrease as more
   people solve them. This rewards experts who solve hard challenges first.

3. **First blood bonuses**: Extra points for being the first to solve a challenge. Creates
   urgency for competitive players.

4. **Live scoreboard**: Real-time leaderboard creates competition dynamics. Consider freezing
   the scoreboard in the final 30-60 minutes to create suspense.

5. **Multi-flag machines**: Advanced participants can aim for full root while others aim for
   user flags.

### Engagement Mechanics

- **Live scoreboard** with team names
- **First blood announcements** (public recognition)
- **Category completion badges** (gamification)
- **Narrative/storyline wrapper** (SANS model: makes challenges feel connected)
- **Team chat** during the event
- **Post-event walkthroughs** for all challenges (critical for learning value)

---

## 6. Challenge Categories for Pentest CTFs

### Core Categories (Recommended for Boot2Root/Pentest Events)

| Category | Description | Example Challenges |
|----------|-------------|-------------------|
| **Reconnaissance/OSINT** | Information gathering, network scanning | Find open ports, identify services, DNS enumeration |
| **Web Exploitation** | Web app vulnerabilities | SQLi, XSS, command injection, file upload bypass, auth bypass |
| **Network Enumeration** | Service discovery and analysis | SMB shares, FTP anonymous access, SNMP walks |
| **Cryptography** | Cipher and encryption challenges | Weak encryption, password cracking, hash cracking |
| **Linux Privilege Escalation** | Escalating from user to root | SUID binaries, sudo misconfig, cron jobs, kernel exploits |
| **Windows Privilege Escalation** | Escalating on Windows targets | Service misconfigs, token impersonation, registry keys |
| **Forensics** | Analyzing artifacts | Memory dumps, PCAP analysis, file recovery, log analysis |
| **Reverse Engineering** | Analyzing compiled programs | Binary analysis, deobfuscation, malware analysis |
| **Miscellaneous** | Anything else | Steganography, encoding, trivia, OSINT |

### Category Distribution for a Pentest-Focused 4-Hour Event

For 20-25 challenges:

| Category | # Challenges | Rationale |
|----------|-------------|-----------|
| Web Exploitation | 4-5 | Most accessible, widest applicability |
| Linux Privilege Escalation | 3-4 | Core pentest skill |
| Reconnaissance/Enumeration | 3-4 | Foundation skill, good for beginners |
| Cryptography/Password Cracking | 2-3 | Common in real assessments |
| Forensics | 2-3 | Diversity of skills |
| Windows Exploitation/PrivEsc | 2-3 | Enterprise relevance |
| Reverse Engineering | 1-2 | Advanced category |
| Miscellaneous/Warm-up | 2-3 | Engagement and on-ramps |

### Boot2Root Machine Design Principles

From abatchy's guide and VulnHub community:

1. **Use official ISOs** -- not pre-configured VMs -- for hypervisor compatibility
2. **Patch the OS** -- you want players finding YOUR vulns, not unintended kernel exploits
3. **Layer the attack path**: remote -> local user -> root (minimum)
4. **Create dead ends and rabbit holes** (for harder machines) to add realism
5. **Place flags at each privilege level**: user.txt and root.txt
6. **Test with real players** ("test bunnies") before the event
7. **Remove GUI** to reduce VM size
8. **Export as OVA** for portability
9. **Set DHCP** for networking
10. **Document any special requirements** in VM description

---

## 7. Scaling for 50-100 Participants

### Platform Choice

**CTFd** is the dominant open-source CTF platform. Key configuration for 50-100 participants:

- **Workers**: Default Docker Compose has 1 worker -- increase to 8+ (Gunicorn)
- **Database**: MySQL/PostgreSQL. 75 simultaneous connections per MySQL instance is sufficient
  for 100 participants
- **Caching**: Redis for session management and caching
- **Load balancing**: Put behind Cloudflare or similar CDN for DDoS protection

### Infrastructure Architecture (AWS)

For a Boot2Root event with isolated machines per participant:

**Shared Challenges (Jeopardy-style)**:
- Single instance per challenge, all participants connect to the same target
- Requires careful flag design (dynamic flags per user to prevent sharing)
- Much simpler infra: one challenge server handles all participants

**Isolated Machines (Boot2Root)**:
- Each participant/team gets their own instance of each vulnerable machine
- Requires significant compute: 50 teams x 3 machines = 150 VMs minimum
- Use container-based isolation (Docker/K8s) where possible to reduce cost
- VPC isolation between participants is critical

**Recommended AWS Architecture**:
- EKS/ECS for containerized challenges
- Separate VPCs or network segmentation for isolated challenge environments
- Application Load Balancer for CTFd platform
- Container spawn time target: under 30 seconds
- Challenge load time target: under 2 seconds
- Use Spot Instances for challenge VMs (90% cost reduction)
- Pre-provision infrastructure 30 minutes before event
- Automated cleanup via Lambda after event

**Resource Estimates**:
- CTFd platform: 2-4 vCPU, 4-8 GB RAM
- Per containerized challenge: 0.5-2 vCPU, 0.5-2 GB RAM (varies by challenge type)
- Per full VM (Boot2Root): 1-2 vCPU, 2-4 GB RAM
- Web challenges: need application servers
- Crypto challenges: CPU-intensive
- Forensics: storage-heavy
- Binary exploitation: memory-heavy

### Scaling Considerations

- **Dynamic flags**: Use per-team/per-user flags to prevent answer sharing. CTFd supports this.
- **Rate limiting**: Implement submission rate limiting to prevent brute-force
- **Monitoring**: Central monitoring dashboard for all challenge infrastructure
- **Support channel**: Discord with separate channels per category
- **Backup plan**: Have static challenges ready in case infrastructure fails

### Cost Optimization

- Spot Instances for non-critical challenge infrastructure
- Scheduled scaling: spin up 30 min before, tear down after
- Reserved Instances for predictable baseline (CTFd platform)
- Cost allocation tags per event/challenge

---

## 8. Agentic/AI-Assisted CTFs

### The Current State (March 2026)

AI has fundamentally changed the CTF landscape. Key data points:

**Hack The Box AI vs Human CTF (March 2025)**:
- 5 of 8 AI teams solved 19/20 challenges (95%)
- Only 12% of human teams (19 of 150) achieved 20/20
- Best AI team placed 20th overall among 403 human teams
- AI teams matched top human team speed on solved challenges
- AI excelled at: cryptography, reverse engineering, web exploitation, binary analysis
- AI struggled with: runtime state analysis, heavily obfuscated code requiring dynamic analysis

**Anthropic's Claude in Competitions (2025)**:
- PicoCTF 2025: Top 3% globally (297th of 10,460 teams), solved 32/41 challenges
- Hack The Box AI vs Human: 4th among AI teams, solved 19/20
- PlaidCTF and DEFCON Qualifier: Solved zero challenges (expert-level competitions)
- This shows AI is highly capable at beginner-through-advanced but still struggles at elite level

**CAI (Cybersecurity AI) Performance**:
- Won Neurogrid CTF with 41/45 flags ($50K prize pool)
- AI/Human time ratios: 76x faster on web, 48x on forensics, 13x on misc, 11x on pwn, 9x on rev
- "Jeopardy-style CTFs have become a solved game for well-engineered AI agents"

**HTB Machine First Blood Trends**:
- Root blood times declined ~16% per year (log-space) from 2017-2025
- Sharpest drops after LLM emergence
- Hard tier: 27% improvement post-LLM
- Insane tier: 67% improvement post-LLM

### How AI Changes Difficulty Calibration

1. **Easy/Medium challenges become trivial**: AI can solve L0-L3 challenges in seconds to
   minutes. If participants have AI access, these challenges function as warm-ups only.

2. **Advanced challenges become medium**: AI accelerates enumeration, exploit research, and
   scripting dramatically. A challenge that takes a human 2 hours might take an AI-assisted
   human 20-30 minutes.

3. **Expert challenges remain hard**: Novel exploitation, dynamic analysis, and creative
   reasoning still challenge AI. Design summit challenges around these.

4. **Time compression**: An event calibrated for 4 hours without AI might be completed in
   1-2 hours with AI assistance by skilled operators.

### Recommendations for AI-Assisted Events

**If AI is allowed (recommended for your use case)**:

1. **Recalibrate difficulty upward**: Add 1-2 difficulty levels compared to human-only events.
   What would be L3 without AI should be your floor for interesting challenges.

2. **Increase challenge count**: AI-assisted participants solve faster. Plan for 30-40
   challenges instead of 20-25 for a 4-hour event.

3. **Include AI-resistant challenge types**:
   - Challenges requiring dynamic runtime analysis
   - Multi-step challenges requiring physical/environmental context
   - Challenges requiring interaction with live services that change state
   - Challenges with novel or unpublished vulnerability types

4. **Track AI usage**: Consider requiring participants to note which tools they used.
   The chess analogy is apt -- chess has human-only, engine-only, and "freestyle" (human +
   engine) categories. The freestyle category is the most interesting.

5. **Focus on orchestration skill**: The competition axis shifts from "who is the best hacker"
   to "who best designs, configures, and orchestrates their AI system." This is a legitimate
   and valuable skill.

**Emerging Competition Formats**:

- **CSAW Agentic Automated CTF**: Participants build autonomous AI agents to solve 50
  challenges across 6 categories. Scoring is 50% based on challenges solved. All code must
  be open-sourced.

- **AgentCTF (IEEE SaTML 2026)**: Agents deployed in CVE-inspired environments across
  red-teaming and attack-defense tracks.

- **Anthropic's recommendation**: Separate tracks for human-only vs AI-augmented, with
  voluntary AI usage instrumentation.

### The "Human + AI" Sweet Spot

The most engaging format for a mixed-skill audience with AI tools:

- Beginners use AI as a teacher/guide (AI explains what to do)
- Intermediate users use AI as a force multiplier (AI does the tedious parts)
- Experts use AI as a speed tool (AI handles enumeration while human directs strategy)

This naturally levels the playing field somewhat -- beginners with AI can perform at an
intermediate level, which keeps them engaged and learning.

---

## 9. Scoring Systems

### Static Scoring
Fixed point values per challenge. Simple but does not adapt to actual difficulty.

### Dynamic Scoring (Recommended)

CTFd's dynamic scoring model:

```
value = (((minimum - initial) / (decay^2)) * (solve_count^2)) + initial
```

**Parameters**:
- `initial`: Starting point value (e.g., 500)
- `minimum`: Floor point value (e.g., 100)
- `decay`: Number of solves before reaching minimum (e.g., 20)

**Parabolic decay**: Higher-valued challenges drop slowly at first, then faster as more people
solve them. This naturally rewards solving hard challenges early.

**Example Configuration for 50-100 Participants**:

| Challenge Tier | Initial | Minimum | Decay |
|---------------|---------|---------|-------|
| Warm-up | 100 | 50 | 40 |
| Easy | 200 | 75 | 30 |
| Beginner | 300 | 100 | 25 |
| Intermediate | 400 | 150 | 15 |
| Advanced | 500 | 200 | 10 |
| Expert | 600 | 300 | 5 |

### First Blood Bonus
Extra points for first solve. Creates excitement but can discourage slower participants.
Recommendation: Small bonus (10-15% of initial value) rather than large multipliers.

### Hint Cost
Deduct points when hints are used. PicoCTF does NOT penalize for hints (more educational).
For competitive events, 10-25% penalty per hint tier is common.

---

## 10. Summary: Recommendations for a 4-Hour, 50-100 Person, Mixed-Skill Pentest CTF

### Format
- Jeopardy-style with 3-5 embedded Boot2Root machines
- All challenges available from the start
- Dynamic scoring with first blood bonuses
- Live scoreboard (freeze last 30 min)
- Discord support channel

### Challenge Count and Distribution
- **Total**: 25-30 challenges (35-40 if AI-assisted)
- **Warm-up (L0-L1)**: 6-8 challenges (quick wins, 5-15 min each)
- **Core (L2-L3)**: 10-12 challenges (main event, 15-60 min each)
- **Advanced (L4)**: 5-6 challenges (separators, 1-2 hours each)
- **Expert (L5)**: 2-3 challenges (summit, may go unsolved)

### Boot2Root Machines
- 1 Easy machine (2-3 steps, known CVE, clear path) -- target: 60% solve rate
- 1-2 Medium machines (3 steps, some custom exploitation) -- target: 30% solve rate
- 1 Hard machine (4-5 steps, chaining vulns) -- target: 10% solve rate
- 1 Expert machine (optional, for the ambitious) -- target: <5% solve rate

### Hint System
- 3 tiers of hints per challenge (nudge, direction, near-solution)
- First hint free, subsequent hints cost 15-25% of challenge value
- For beginners: consider providing walkthrough guides for L0-L1 challenges

### Engagement
- Ensure every participant solves something in the first 15 minutes
- Narrative wrapper optional but effective (SANS model)
- Post-event: publish walkthroughs for ALL challenges
- Prizes for: 1st/2nd/3rd overall, most creative solution, best newcomer

### Infrastructure
- CTFd platform on AWS (2-4 vCPU, 4-8 GB RAM, 8 Gunicorn workers)
- Containerized challenges where possible (Docker/K8s)
- Full VMs for Boot2Root machines (isolated per team if budget allows)
- Shared instances acceptable for Jeopardy challenges with dynamic flags
- Pre-provision 30 min before event, automated teardown after

### If AI-Assisted
- Recalibrate: shift difficulty distribution up 1-2 tiers
- Add 30-50% more challenges to account for faster solve times
- Include challenges requiring dynamic analysis and live service interaction
- Consider tracking AI tool usage for post-event analysis
- Embrace it -- AI-assisted pentesting is the future skill to teach

---

## Sources

All sources used in this research are listed at the end of this document for reference.
See the companion response for full URL list.
