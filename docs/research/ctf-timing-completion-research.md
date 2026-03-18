# CTF Challenge Timing, Completion Rates, and Difficulty Calibration Research

**Date**: 2026-03-18
**Purpose**: Data-driven reference for calibrating Shifter CTF challenge difficulty, timing, and event design.

---

## 1. Time Per Challenge by Difficulty

### 1.1 Boot2Root / HackTheBox-Style Machines

Hard numbers on average solve times for HTB machines are not published by HackTheBox directly. However, converging data from multiple sources provides usable estimates.

**First Blood Times (fastest solvers, expert-level players)**:

Analysis of 423 HTB machines (March 2017 - October 2025) from a longitudinal study shows:
- Root blood times have declined approximately 16% per year in log-space (p < 1e-10)
- Post-LLM era (Nov 2022+) shows statistically significant compression across all difficulty tiers
- Hard tier machines: 27% faster post-LLM
- Insane tier machines: 67% faster post-LLM

Dataset breakdown: 124 Easy, 143 Medium, 98 Hard, 58 Insane machines analyzed.

First blood (fastest solver in the world) is typically achieved in under 1 hour for Easy machines, based on forum reports. This represents the absolute floor for timing.

**Estimated Solve Times for Competent Practitioners (not first blood, not beginners)**:

| Difficulty | Estimated Time Range | Notes |
|-----------|---------------------|-------|
| Easy | 1-3 hours | Known attack patterns, single exploit chain |
| Medium | 3-6 hours | Requires research, multiple steps |
| Hard | 6-12 hours | Complex chains, custom exploitation |
| Insane | 12-40+ hours | Novel techniques, extensive enumeration |

These estimates are synthesized from community discussion, walkthrough timing, and the general guidance that "beginners potentially take hours or days, while experienced users can finish [Easy machines] in minutes."

**Typical Boot2Root Attack Chain Timing (per phase, experienced practitioner)**:

| Phase | Typical Time | Notes |
|-------|-------------|-------|
| Port scanning (nmap default 1000 ports) | 2-10 minutes | Varies by network; full 65k scan can take 30+ min |
| Web enumeration (directory brute-force, service ID) | 15-45 minutes | Tools like gobuster/ffuf running in background |
| Vulnerability identification | 15-60 minutes | Depends on obscurity; known CVEs faster |
| Initial exploitation (user shell) | 15-120 minutes | Wide range based on exploit complexity |
| Privilege escalation enumeration | 15-30 minutes | LinPEAS/WinPEAS automated scanning |
| Privilege escalation execution | 15-60 minutes | From identified vector to root |
| **Total Easy machine** | **1-3 hours** | Known CVE, standard privesc |
| **Total Medium machine** | **3-6 hours** | Custom webapp vuln, less obvious privesc |
| **Total Hard machine** | **6-12+ hours** | Chained exploits, pivoting, custom code |

### 1.2 Jeopardy-Style CTF Challenges (non-boot2root)

Jeopardy challenges (crypto, forensics, reverse engineering, web) are typically faster than full boot2root machines:

- **Easy/Sanity check**: 5-30 minutes
- **Medium**: 30-90 minutes
- **Hard**: 1-4 hours
- **Expert/Extreme**: 4-12+ hours

SANS Holiday Hack Challenge designs "micro-challenges" solvable in approximately 15 minutes.

Recommended time limit per challenge during competition: 30-45 minutes before rotating to another challenge (competitive strategy advice, not design guidance).

### 1.3 Impact of AI Assistance on Timing

**AI-accelerated completion (AI as tool for human operator)**:
- GPT-4-Turbo reduced critical task sequences from 8-10 minutes to 4-5 minutes (approximately 50% reduction in per-task cycle time)
- One practitioner reported 40% execution speed increase using ChatGPT for code reviews during pentesting
- PentestGPT achieved 228.6% improvement in task completion vs native GPT-3.5, and 58.6% improvement vs native GPT-4

**AI-autonomous solve rates on HTB (PentestGPT with GPT-4)**:
- Easy machines: 6/7 solved (86%), subtask completion 71.43%
- Medium machines: 2/4 solved (50%), subtask completion 42.25%
- Hard machines: 0 solved (0%), subtask completion 29.41%
- On active HTB machines: 4/5 Easy solved, 1/5 Medium solved
- Total cost: $131.50 across 10 machines (~$13-22 per machine)

**Fully autonomous AI agents (no human)**:
- AutoPenBench: fully autonomous LLMs solve only 21% of real-world CTF tasks
- Semi-autonomous (human-in-the-loop): 64% solve rate
- PentestGPT v2 with Claude Opus 4.5: 91% peak task completion on XBOW (104 web security tasks)

**AI speed advantage in competitions**:
- Dragos OT CTF 2025: AI agent (CAI) scored at 1,846 pts/hour vs top-5 human average of 1,347 pts/hour (37% faster)
- Stanford CyBench: strong AI models solve professional-level CTF tasks at speeds comparable to 11-minute human solves
- Claude 3.7 Sonnet: 61% solve rate on black-box challenges, solving in minutes what humans required hours for

---

## 2. Completion Rates

### 2.1 Large Open CTF Competitions

**DownUnderCTF 2020** (3,000+ users, ~1,400 teams, 56 challenges):
- 80%+ of teams submitted at least one attempt
- 75%+ of teams solved at least one challenge
- 206 teams solved exactly one challenge
- Top team solved 44/56 challenges (79%)
- 181 teams attempted only one challenge
- Distribution: heavy long tail -- most teams solve very few challenges

**Dragos CTF 2025** (2,000 players, 1,200+ teams, 33 challenges, 48 hours):
- 3 teams completed all 33 challenges (0.25% of teams)
- 4th and 5th place teams completed 32/33
- Full completion rate: <0.3%

**Dragos CTF 2024** (819 teams, 1,249 participants, 37 challenges, 48 hours):
- 2 teams completed all challenges (0.24%)

**Dragos CTF 2023** (48 hours):
- 3 teams completed all challenges
- Hardest challenge solved by only 0.85% of registered teams

**DownUnderCTF 2022**:
- 224 teams attempted only one challenge
- 193 teams made only one submission total
- Top team attempted 63 challenges
- Top team made 614 submissions

### 2.2 Solve Rates by Difficulty (Estimated from Cross-Source Data)

| Difficulty | Estimated % of Participants Solving | Source Basis |
|-----------|-----------------------------------|-------------|
| Easy/Sanity | 60-80% | DUCTF data, general CTF patterns |
| Medium | 25-50% | Derived from score distributions |
| Hard | 5-15% | Dragos hardest challenge at 0.85% |
| Expert/Insane | 1-5% | Only top teams reach these |

### 2.3 Score Distribution Shape

CTF score distributions consistently follow a heavy long-tail pattern:
- A large cluster of teams near the bottom (1-3 challenges solved)
- A thin middle band
- Very few teams at the top
- Dynamic scoring (points decrease as more teams solve) reinforces this distribution
- Typical pattern: 75% of teams solve at least one challenge, but fewer than 5% solve more than half

### 2.4 HTB AI vs Humans CTF (2025)

In a controlled 48-hour Jeopardy-style competition with 20 challenges (crypto and reverse engineering focus), 403 human teams:
- 19 human teams (4.7%) solved all 20 challenges
- 5 of 8 AI teams solved 19/20 (95%)
- 1 AI team solved 18/20 (90%)
- No AI team achieved a perfect 20/20
- Median human team solved significantly fewer than AI teams
- On challenges they solved, AI teams performed at roughly the same speed as top human teams

---

## 3. Challenge Count Benchmarks

### 3.1 By Event Duration

| Event Duration | Recommended Challenge Count | Source |
|---------------|---------------------------|--------|
| 2 hours (internal/training) | 15-20 challenges | Community best practice |
| 4 hours (conference) | 15-25 challenges | Derived from pacing guidance |
| 8 hours (single-day) | 25-40 challenges | MetaCTF hosting guide |
| 24 hours (standard online) | 30-56 challenges | DUCTF, standard practice |
| 48 hours (major competition) | 33-45 challenges | Dragos, Neurogrid, DUCTF |

Rule of thumb from organizer guidance: "ensure all teams on the scoreboard always have at least 2-3 problems open to work on" at any given time.

### 3.2 Difficulty Distribution Ratios

**For educational/mixed-skill CTFs**:
- 35% Easy, 35% Medium, 25% Hard, 5% Extreme
- Source: Hats Off Security CTF design guide

**For conference/technical CTFs**:
- 10% Easy, 25% Medium, 40% Hard, 25% Extreme
- Source: Hats Off Security CTF design guide

**Alternative recommended ratio**:
- 25% each of "very easy," "easy," "moderate," and "hard+"
- Source: Jeopardy CTF Basics

**Concrete example (Cyber Security Base 2025)**:
- 10 Easy, 10 Medium, 3 Hard (43%/43%/13%)

### 3.3 Challenges Attempted vs Completed (Typical Participant Behavior)

From DownUnderCTF data:
- Median team solves 1-3 challenges out of 56 available
- Top 10% of teams solve 15+ challenges
- Top 1% solve 30+ challenges
- Average participant attempts far fewer challenges than are available

Recommended pacing for internal events:
- 15-20 challenges for 15-20 participants over 2 hours
- Approximately 7-10 challenges per hour of event time available to participants (they will not solve all of them)

### 3.4 Scoring Approaches

**Static scoring**: Fixed points per difficulty (e.g., Easy=100, Medium=200, Hard=300, Expert=500)
**Dynamic scoring**: All challenges start at same value; points decrease with each solve
**Blood bonuses**: Extra points for first 3 solves (first blood, second blood, third blood)
**Hint penalties**: Free hints for Easy/Medium; point deduction for Hard/Expert (Dragos model)

---

## 4. Boot2Root Specific Timing

### 4.1 User Flag vs Root Flag Timing

In a typical boot2root machine, the attack chain splits into two phases:

**Phase 1: Initial Access (User Flag)**
- Reconnaissance + enumeration: 30-90 minutes
- Vulnerability identification + exploitation: 30-120 minutes
- **Typical total to user flag**: 1-3 hours (Easy), 2-5 hours (Medium)

**Phase 2: Privilege Escalation (Root Flag)**
- Enumeration of escalation vectors: 15-30 minutes
- Exploitation of privesc: 15-90 minutes
- **Typical total from user to root**: 30 minutes - 2 hours (Easy), 1-4 hours (Medium)

**Overall timing (experienced practitioner, no hints)**:
- Easy machine total: 1.5-4 hours
- Medium machine total: 3-8 hours
- Hard machine total: 8-20 hours

### 4.2 Common Attack Technique Timing

| Technique | Time Estimate | Notes |
|-----------|--------------|-------|
| Nmap TCP SYN scan (1000 ports) | 2-5 minutes | Default scan, responsive host |
| Nmap full port scan (65535) | 15-45 minutes | -p- flag, depends on network |
| Nmap service/version detection | 5-15 minutes | -sV flag on discovered ports |
| Directory brute-force (web) | 10-30 minutes | Depends on wordlist size |
| Web application manual enumeration | 20-60 minutes | Checking pages, forms, headers |
| SQL injection identification + exploitation | 15-60 minutes | SQLmap for automation |
| Known CVE exploitation | 10-30 minutes | Searchsploit/Metasploit |
| Custom exploit development | 1-6 hours | Buffer overflow, deserialization, etc. |
| Linux privilege escalation (common vectors) | 15-60 minutes | SUID, cron, sudo misconfig |
| Windows privilege escalation | 30-120 minutes | Token impersonation, service abuse |
| Active Directory attacks | 2-8 hours | Kerberoasting, DCSync, lateral movement |
| Pivoting to internal network | 1-3 hours | SSH tunneling, chisel, ligolo |

### 4.3 Professional Pentesting Phase Timing (for context)

Full professional penetration tests typically take 2-3 weeks:
- Pre-engagement: 2-3 days
- Reconnaissance/scanning: 2-3 days
- Exploitation: 1-3 days
- Post-exploitation/cleanup: 1-2 days
- Reporting: 2-4 days
- Web app pentest (focused): 7-10 days total

---

## 5. AI-Assisted Pentesting Speed

### 5.1 Research Findings

**ARTEMIS AI Agent (real-world pentest study)**:
- Placed 2nd out of 11 participants (10 humans + 1 AI)
- Discovered 9 valid vulnerabilities with 82% valid submission rate
- Outperformed 9 of 10 human participants
- Cost: $18.21/hour (GPT-5 config) vs $125,034/year average human salary
- Key advantage: parallel exploitation (up to 8 simultaneous sub-agents)
- Key weakness: GUI-based interaction limitations (20% of critical vulns missed that 80% of humans found)

**CAI (Cybersecurity AI) Competition Results**:
- Neurogrid CTF: Won with 41/45 flags and $50,000 prize
- Dragos OT CTF 2025: Completed 32/34 challenges, 37% faster velocity than top human teams
- HTB Cyber Apocalypse: Competed against 8,129 teams
- Point accumulation rate: 1,846 pts/hour (AI) vs 1,347 pts/hour (human top-5 average)

**D-CIPHER on HackTheBox**: 44% solve rate
**xOffense**: 79.17% subtask completion rate

### 5.2 Tasks AI Accelerates Most

Based on research data:

1. **Enumeration and reconnaissance** -- Systematic, parallelizable, pattern-matching heavy. AI excels here.
2. **Known vulnerability identification** -- GPT-4 successfully exploited 87% of 15 one-day vulnerabilities using known CVEs. Metasploit alone scored 0%.
3. **Exploit selection and payload generation** -- Average time to generate a synthetic attack payload: 10.52 seconds. 54% faster time-to-first-attack than closest competing tool.
4. **Report generation** -- Natural language output is an obvious strength.

### 5.3 Tasks AI Struggles With

1. **GUI-based interaction** -- Browser-based exploitation, visual inspection
2. **Novel/zero-day exploitation** -- Multi-agent teams showed up to 4.3x improvement over single agents, but still limited
3. **Maintaining coherent testing strategy** -- LLMs lose track of the big picture in long engagements
4. **Hard and Insane difficulty** -- PentestGPT: 0% solve rate on Hard HTB machines; subtask completion drops to 29%
5. **Custom exploit development** -- Requires creativity and deep system knowledge

### 5.4 Speed Multipliers (AI-assisted human vs manual human)

| Scenario | Speed Improvement | Source |
|---------|------------------|--------|
| Per-task cycle time (command gen, summarization) | ~50% faster | LLM-augmented pentesting paper |
| Code review during pentest | ~40% faster | Practitioner report |
| Competition point velocity | ~37% faster | Dragos OT CTF 2025 |
| Task completion rate (PentestGPT vs baseline) | 228.6% improvement | PentestGPT benchmark |
| Black-box challenge solving | Minutes vs hours | CyBench/AIRTBench |
| HTB root blood time compression (post-LLM era) | 27-67% faster | Longitudinal HTB study |

### 5.5 Net Assessment for CTF Design

For a Shifter CTF with AI-assisted participants:
- **Easy challenges will be trivially fast** -- Expect AI-assisted solvers to complete Easy boot2root in 30-90 minutes instead of 1-3 hours
- **Medium challenges remain viable** -- AI helps with enumeration but still requires human judgment; expect 50-70% time reduction
- **Hard challenges retain difficulty** -- AI subtask completion drops dramatically; expect only modest speedup (20-30%)
- **Expert challenges are AI-resistant** -- Novel exploitation, complex chains, and creative problem-solving are still primarily human skills

---

## 6. Implications for Shifter CTF Design

### 6.1 For a 4-Hour Event

Recommended configuration:
- **Total challenges**: 15-20
- **Difficulty mix**: 5-7 Easy (35%), 5-7 Medium (35%), 3-4 Hard (25%), 0-1 Expert (5%)
- **Expected completion**: Top teams solve 60-70% of challenges; median team solves 20-30%
- **Boot2root machines**: 2-4 machines (Easy and Medium only for 4-hour window)
- **Jeopardy challenges**: 12-16 for variety and pacing

### 6.2 For an 8-Hour Event

Recommended configuration:
- **Total challenges**: 25-35
- **Difficulty mix**: 8-12 Easy, 8-10 Medium, 5-8 Hard, 2-3 Expert
- **Boot2root machines**: 3-6 machines across Easy/Medium/Hard
- **Expected completion**: Top teams solve 50-60%; median team solves 15-25%

### 6.3 AI-Adjusted Timing

If AI assistance is expected or allowed:
- Reduce Easy challenge count (they will be solved too quickly)
- Add more Medium and Hard challenges
- Consider dynamic scoring to devalue rapidly-solved challenges
- Design challenges requiring GUI interaction, multi-step reasoning, or custom exploitation to maintain difficulty
- Expect 30-50% faster overall completion times from top participants

---

## Sources and References

- DownUnderCTF 2020 Statistics: https://downunderctf.com/blog/2020/ctf-statistics/
- Dragos CTF 2025 Results: https://www.dragos.com/blog/2025-dragos-capture-the-flag-ctf-competition-summary-results
- Dragos CTF 2024 Results: https://www.dragos.com/blog/the-4th-annual-dragos-capture-the-flag-ctf-results-are-in
- HackTheBox AI vs Human CTF: https://www.hackthebox.com/blog/ai-vs-human-ctf-hack-the-box-results
- ARTEMIS vs Human Pentesters: https://arxiv.org/abs/2512.09882
- PentestGPT (USENIX Security 2024): https://arxiv.org/html/2308.06782v2
- LLM-Augmented Pentesting: https://arxiv.org/html/2409.09493v2
- AI Death of CTF Analysis: https://securityboulevard.com/2026/03/the-death-of-the-ctf-how-agentic-ai-is-reshaping-competitive-hacking/
- CAI Dragos OT CTF Paper: https://arxiv.org/pdf/2511.05119
- CTF Design Guide (Hats Off Security): https://hatsoffsecurity.com/2020/05/27/how-to-create-a-good-security-ctf/
- CTF Hosting Guide (MetaCTF): https://metactf.com/a-comprehensive-guide-to-hosting-a-capture-the-flag-competition/
- Jeopardy CTF Basics: https://github.com/Ratanshi/Jeopardy_CTF-Basics/blob/master/suggestions-for-running-a-ctf.markdown
- CTF Program Evaluation (Reflare): https://reflare.com/research/how-to-evaluate-your-ctf-program
- TryHackMe Difficulty Levels: https://help.tryhackme.com/en/articles/6611846-room-difficulty-levels
- Nmap Performance: https://nmap.org/book/man-performance.html
- Penetration Testing Phases: https://www.strikegraph.com/blog/pen-testing-phases-steps
- PentestGPT v2 / CheckMate: https://arxiv.org/html/2602.17622v1
