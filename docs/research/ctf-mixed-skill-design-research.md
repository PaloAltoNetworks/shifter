# CTF Design Research: Mixed-Skill Audiences

Research compiled 2026-03-18. Focused on CTF events designed for participants ranging from complete beginners through experts, with emphasis on 4-hour event constraints.

---

## 1. Notable Mixed-Skill CTFs

### SANS Holiday Hack Challenge

The gold standard for mixed-skill CTF design. Key structural elements:

- **Difficulty Rating**: Each challenge is ranked 1-5 snowballs (5 = most difficult)
- **Dual-Mode Solving**: Every challenge can be solved via easy mode (silver trophy) or hard mode (gold trophy). Skipping gives a bronze participation trophy.
- **Act-Based Progression**: Content is organized into a Prologue, Act 1, Act 2, Act 3 -- each progressively harder
- **Story Mode / Play-Through**: Players can advance the storyline without solving a challenge, coming back whenever ready. This is critical -- nobody gets stuck and frustrated.
- **CTF-Mode Toggle**: Players can skip the storyline, online world, and avatars to focus purely on challenges
- **Micro-Challenges**: 15+ bite-sized challenges designed for 10-15 minutes each
- **Capstone Challenges**: 3-4 large, in-depth challenges that bring everything together for seasoned players
- **Cohort Leaderboards**: Teams/organizations get private scoreboards alongside the global one

The silver/gold/bronze trophy system is particularly relevant -- it means beginners can still complete the event and feel accomplishment (silver/bronze) while experts are motivated to achieve gold on everything.

### PicoCTF (Carnegie Mellon)

Designed specifically for students with no prior security experience:

- **Point Range**: 5 points to 500 points per challenge
- **6 Categories**: Web Exploitation, Cryptography, Reverse Engineering, Forensics, General Skills, Binary Exploitation
- **Progressive Difficulty**: Challenges within each category ramp from introductory to mastery level
- **picoGym**: Always-available practice space with hundreds of challenges from prior competitions
- **Hints Included**: Most challenges include hints and learning resources
- **Research-Backed**: The "pico-Boo!" paper (CISSE conference) demonstrated that adding more introductory and intermediate problems with gradual difficulty increases statistically significantly improved the percentage of problems students completed (p < 0.046 comparing 2017 vs 2018)

Key lesson: More easy/introductory challenges = higher overall engagement, not lower quality.

### National Cyber League (NCL)

The most structured tier system of any CTF:

- **5 Divisions**: Bronze, Silver, Gold, Platinum, Diamond (ascending)
- **4 Tiers Within Each Division**: Tier 4 (lowest) to Tier 1 (highest) = 20 total skill levels
- **Challenge Difficulties**: Easy, Medium, Hard within each competition
- **Gym Environment**: Practice space aligned with competition content so players can build skills before competing
- **Scale**: 13,000+ students from 650+ colleges/high schools per year
- **Prerequisite Knowledge**: Cross-section of beginner knowledge in CS, networking, sysadmin, OS, and scripting

The NCL model of a "gym" that mirrors competition content is relevant -- it means participants can self-assess and practice before the live event.

### BSides CTFs

Typical conference CTF structure:

- **3 Difficulty Levels**: Easy, Medium, Hard
- **Jeopardy Format**: Categories include Crypto, Forensics, Web, Mobile, Pwn, Reversing, Wireless, IoT, Physical
- **Beginner Support**: "Find-a-team" channels on Discord; resources for first-time players
- **Inclusive Design**: Challenge progression explicitly designed to engage all skill levels

### CPTC (Collegiate Penetration Testing Competition)

Different model -- simulates a real pentest engagement rather than jeopardy-style:

- **Scoring Breakdown (as of 2021)**:
  - Technical Findings: 35%
  - Reporting: 35%
  - Injects/Compliance/Interactions: 30%
- **Structure**: Teams play the role of a consulting firm with deliverables, presentations, and client interactions
- **Progression**: Online registration deliverable -> top 10 per region advance to in-person engagement

Less relevant to a standard CTF but demonstrates that scoring can weight non-technical skills (reporting, communication) to level the playing field.

### Military / Government CTFs

**DoD Cyber Sentinel Skills Challenge**:
- 20+ simulations based on real DoD scenarios
- Categories: Forensics, Malware/RE, Networking & Recon, OSINT, Web Security
- Three difficulty levels: Easy, Medium, Hard
- Open to all DoD civilian and military employees

**All-Army CyberStakes** (2016-2020, now suspended):
- 10-day competition (deliberately long to accommodate Reserve/Guard schedules)
- 5 categories: Binary Exploitation, Reverse Engineering, Forensics, Cryptography, Web Exploitation
- 22 introductory challenges specifically crafted for accessibility
- 2,049 participants in final year (doubled from prior year)
- 38,663 total solves across all participants
- Key design choice: "focus on crafting the challenge progression to be more accessible to beginners"
- Write-up submission system so participants could learn from each other post-solve

**DoD Cyber Red Zone (CRZ)**:
- Annual offensive cyber operations CTF
- Explicitly designed for "limited to extensive experience" range

**DEF CON Villages**:
- Hardware Hacking Village: Jeopardy-style, beginner to advanced
- Darknet-NG: ARG + hands-on hacking, "whether you're new to security or already deep in the game"
- pwn.college Community: On-site mentorship from experienced hackers
- Lab platforms with step-by-step instructions "aimed at teaching individuals specific techniques"

---

## 2. Difficulty Tier Systems

### How Many Tiers?

Successful mixed-skill CTFs use between 3 and 6 tiers:

| Tiers | Used By | Notes |
|-------|---------|-------|
| 3 | BSides, DoD Cyber Sentinel | Easy / Medium / Hard |
| 4 | Hats Off Security recommendation | Easy / Medium / Hard / Extreme |
| 5 | NCL (divisions), SANS (snowballs) | More granularity for larger events |
| 6 | CTFd framework, OWASP Juice Shop | Level 0 through Level 5 (or 1-6 stars) |

**Recommendation from experienced organizers**: 4 tiers is the sweet spot for a mixed-audience event. 3 feels too coarse; 6 is more granularity than most events need.

### CTFd's Level Framework (Industry Standard)

| Level | Description | Prerequisites | Points | Hints |
|-------|-------------|---------------|--------|-------|
| 0 | No technical knowledge needed. Solution found by Googling or simple manipulation. | None | <100 | Generous |
| 1 | Basic tools and concepts. May need a terminal. Programming optional. | Minimal | 100-199 | Available |
| 2 | Simple knowledge of a single vulnerability. Can research solution online. | Some | 200-299 | Moderate |
| 3 | Actual knowledge of vulnerability groups. Multiple challenge layers. Programming heavily suggested. | Significant | 300-399 | Limited |
| 4 | Real-world vulnerability applications. No training wheels. Programming required. | Advanced | 400-499 | Sparse |
| 5 | Specialized domains. Potentially unknown vulnerabilities or CVEs. Advanced programming required. | Expert | 500+ | Minimal/None |

### OWASP Juice Shop Scoring (6-Star System)

| Difficulty | Points | Hint Cost |
|-----------|--------|-----------|
| 1 star | 100 | 10 |
| 2 stars | 250 | 25 |
| 3 stars | 450 | 45 |
| 4 stars | 700 | 70 |
| 5 stars | 1000 | 100 |
| 6 stars | 1350 | 135 |

Hint cost is consistently 10% of challenge value -- a clean ratio.

### Recommended Tier Names and Mapping

For a corporate/government mixed-skill event, practical naming:

| Tier | Name | Real-World Equivalent | Expected Audience % |
|------|------|-----------------------|---------------------|
| 1 | Warm-Up | Security awareness level. Anyone can solve. | Everyone |
| 2 | Foundation | Junior analyst / help desk with some security knowledge | 60-70% |
| 3 | Practitioner | Working SOC analyst / sysadmin with security tools experience | 30-40% |
| 4 | Expert | Senior pentester / threat hunter / malware analyst | 5-15% |

---

## 3. Participant Skill Distribution

### Empirical Data

**Dragos CTF 2024** (819 teams, 1,249 participants, 48-hour industrial security CTF):
- Easy + Normal challenges: ~80% of all solves
- Expert + Extreme challenges: ~6% of all solves
- Only 2 of 819 teams completed all 37 challenges
- 80.26% of all flag submissions were incorrect

This strongly suggests a power-law distribution: most participants cluster at beginner-to-intermediate, with a steep dropoff at advanced levels.

### Estimated Distribution for Corporate/Conference CTF (50-100 people)

Based on synthesis of Dragos data, NCL structure, CyberStakes participation patterns, and MetaCTF guidance:

| Skill Level | % of Participants | Description |
|-------------|-------------------|-------------|
| True Beginners | 30-40% | First CTF. May not have terminal experience. Security awareness level. |
| Guided Beginners | 20-30% | Some IT background. Can follow instructions. Will need hints. |
| Intermediate | 20-25% | Working security professionals. Comfortable with tools. |
| Advanced | 10-15% | Active CTF players or senior security practitioners. |
| Expert | 2-5% | Could write the challenges. Will complete everything quickly. |

### For a National Security / Government Audience

The distribution shifts right (more technically capable on average):

| Skill Level | % of Participants |
|-------------|-------------------|
| True Beginners | 15-20% |
| Guided Beginners | 20-25% |
| Intermediate | 30-35% |
| Advanced | 15-20% |
| Expert | 5-10% |

The CyberStakes data supports this: even in an all-Army competition, they needed 22 introductory challenges and deliberately focused on "crafting the challenge progression to be more accessible to beginners" because many participants were not technical specialists.

---

## 4. Progressive Challenge Design

### Challenge Chains

**Definition**: Sequential challenges where solving one unlocks or provides clues for the next.

**CTFd Implementation**: "The next task in chain can be opened only after some team solve previous task." This creates guided learning paths.

**Effective patterns**:
- Recon -> Initial Access -> Privilege Escalation -> Data Exfiltration (mimics real attack chain)
- Each stage reveals information needed for the next (e.g., credentials, IP addresses, file paths)
- Earlier stages should be easier, with difficulty increasing through the chain

**Risk**: If a participant gets stuck on step 2 of 5, they lose access to steps 3-5. Mitigation: make early chain links easier, or offer parallel chains at different difficulty levels.

### Walkthrough / Tutorial Challenges

**Level 0 / Warm-Up Design** (from CTFd framework):
- No technical knowledge required
- Solution findable by Googling or simple manipulation
- No prerequisite knowledge
- Generous hints
- Expectation: almost all participants solve these

**Best practices at scale**:
- Start with basic security awareness questions (password etiquette, common best practices) to give early wins
- "The biggest mistake organizers make with general audience CTFs is jumping straight into technical challenges"
- Include non-technical challenges (trivia, OSINT using only a web browser) in a Misc category
- Create an initial "gimme" challenge that awards free points, which participants can later spend on hints

**PicoCTF Research Finding**: Adding more introductory and intermediate problems with gradual difficulty increases was statistically proven to improve engagement and reduce dropout.

### Hint Systems

**Free vs Paid Hints (CTFd)**:
- Hints can be free or have a point cost
- Users who unlock paid hints lose points equal to the hint cost
- Users cannot reduce their score below zero
- Users must have sufficient points to unlock a hint

**Recommended Approach for Mixed Audiences**:
- 2-3 hints per challenge (for learning-focused events)
- First hint: Free -- gentle nudge toward the right approach
- Second hint: Low cost -- more specific guidance
- Third hint: Higher cost -- near-complete walkthrough
- OWASP Juice Shop model: Hint cost = 10% of challenge value

**Impact on Completion Rates**:
- AI-enhanced hint research showed: "dynamically adjusted difficulty kept learners both engaged and motivated" and "AI-driven hints provided real-time assistance without revealing direct answers, reducing anxiety among beginners"
- Organizer experience: "I typically don't give out a ton of hints unless there are several challenges that haven't been solved"
- Strategic approach: Embed hints in challenge titles/descriptions for easier challenges; reserve explicit hint unlocks for harder ones

---

## 5. Scoring Systems for Mixed Audiences

### Static Scoring

Simple point values per challenge. Easy to understand but requires accurate difficulty assessment by organizers.

### Dynamic Scoring (Industry Standard for Mixed Events)

**CTFd Formula**:
```
value = (((minimum - initial) / (decay ** 2)) * (solve_count ** 2)) + initial
value = math.ceil(value)
if value < minimum: value = minimum
```

**Parameters**:
- `initial`: Starting point value before any solves
- `minimum`: Floor value (challenge never worth less than this)
- `decay`: Number of solves before reaching minimum points
- Uses parabolic function (not linear/exponential) so higher-valued challenges drop slower

**Why it works for mixed audiences**:
- Easy challenges that many people solve naturally drop in value
- Hard challenges that few solve retain high value
- Eliminates the problem of organizers misjudging difficulty
- All users who previously solved a challenge see their score for that challenge decrease as more people solve it

**Key detail**: Hidden users and admin solves do not affect dynamic scoring.

### First Blood Bonuses

**Implementation examples**:
- Hack.lu 2016: First solve = +3 points, second = +2, third = +1
- Generic: One extra point for first team to solve (called "first blood")
- Hack The Box: Additional points for first-to-complete
- Ties typically broken by which team achieved the score first

**Caution for mixed audiences**: First blood heavily favors experts. Consider limiting bonus to harder challenges only, or keeping bonuses small relative to challenge value.

### Time-Based Scoring

- Ties broken by timestamp of achieving score
- Some CTFs add bonus points that decrease over time (earlier solves worth more)
- CTFd supports "Freeze Time" -- scores frozen near end to create suspense for final reveal

### Fairness Strategies for Mixed Skill Levels

1. **Dynamic scoring** inherently self-balances
2. **Category diversity**: Include non-technical categories (OSINT, trivia) where non-experts can score
3. **Separate leaderboards**: Global + per-team/cohort private leaderboards (SANS model)
4. **Division-based competition**: NCL model with Bronze through Diamond divisions
5. **Weight limit on hard challenges**: Ensure enough easy/medium points that a beginner solving all easy challenges can outscore an expert who only solves 2 hard ones

---

## 6. Four-Hour Event Design

### Existing Precedents

- Hack The Box supports "short, time-limited workshops of 4, 8, or 12 hours"
- Internal CTF recommendation: 15-20 challenges for a 2-hour event with 15-20 participants
- Extrapolating: 20-30 challenges for a 4-hour event with 50-100 participants
- CTFd Success Guide categorizes this as a "workshop" format (as opposed to 48-76 hour competitive events)

### Recommended Challenge Count for 4 Hours

Based on synthesis of all research:

| Difficulty | Count | % of Total | Time Budget Per Challenge |
|-----------|-------|------------|--------------------------|
| Warm-Up (Level 0) | 5-6 | ~20% | 5-10 min |
| Easy (Level 1) | 7-8 | ~25% | 10-20 min |
| Medium (Level 2-3) | 8-10 | ~35% | 20-40 min |
| Hard (Level 4-5) | 5-6 | ~20% | 40-90 min |
| **Total** | **25-30** | **100%** | |

### What Different Skill Levels Can Achieve in 4 Hours

| Participant Type | Expected Solves | Points Range | Experience |
|-----------------|-----------------|--------------|------------|
| True Beginner | 3-6 challenges (warm-ups + some easy) | Low-mid | Learns what a CTF is, gets early wins, may get stuck |
| Guided Beginner | 6-12 challenges (warm-ups + easy + some medium) | Mid | Productive throughout, uses hints |
| Intermediate | 12-18 challenges (most easy/medium + some hard) | Mid-high | Stays engaged, pushes into hard territory |
| Advanced | 18-24 challenges | High | Completes most, works through hard challenges |
| Expert | 24-30 challenges (most/all) | Top | May finish early -- consider bonus challenges or first-blood hunting |

### Time Management for Organizers

**Pre-Event (30 min)**:
- Brief orientation: What is a CTF, how to submit flags, where to get help
- Show the scoreboard, explain categories
- Demonstrate solving the first warm-up challenge live

**Hour 1**:
- Most activity on warm-up and easy challenges
- Expect heavy question volume -- "plan on getting a lot of questions"
- Monitor scoreboard to ensure challenges are solvable

**Hour 2**:
- Intermediate players push into medium challenges
- Consider releasing first round of hints for unsolved easy challenges
- Beginners may need encouragement -- highlight their progress

**Hour 3**:
- Advanced players hit hard challenges
- Release hints more freely for medium challenges
- This is where engagement risk is highest for beginners -- consider "office hours" or helper station

**Hour 4**:
- Freeze scoreboard 15-30 min before end for suspense
- Release generous hints on remaining unsolved challenges
- Final push mentality

### Critical Design Principles for 4-Hour Events

1. **Front-load easy wins**: First 30 minutes should feel achievable for everyone
2. **No prerequisite chains longer than 3 steps**: Risk of blocking participants is too high in a short event
3. **Have backup hints ready**: If nobody has solved a challenge by hour 2, something may be wrong with it
4. **Include at least 2 non-technical categories**: OSINT, trivia, security awareness
5. **Cap hard challenges**: Nobody should need more than 60-90 minutes on a single challenge in a 4-hour event
6. **Live help desk**: At least 1 helper per 15-20 participants
7. **Test every challenge**: "Stand up a working copy in your deployment environment and solve each challenge yourself"
8. **Monitor incorrect submissions**: Dragos data showed 80% of submissions were wrong -- high wrong-answer rates on a specific challenge may indicate unclear instructions rather than difficulty

### Recommended Difficulty Distribution

For a teaching/engagement-focused 4-hour event (the Shifter use case):

**35% Easy / 35% Medium / 25% Hard / 5% Extreme** (from Hats Off Security)

For a more technical/competitive audience:

**10% Easy / 25% Medium / 40% Hard / 25% Extreme**

For a government/national security audience (split the difference):

**25% Easy / 30% Medium / 30% Hard / 15% Extreme**

---

## Key Takeaways for Shifter CTF Design

1. **SANS Holiday Hack's dual-mode (silver/gold) is the best model for mixed audiences** -- every challenge has an easy path and a hard path, so beginners complete the event while experts are challenged.

2. **4 difficulty tiers** is the sweet spot. More granularity than 3, less complexity than 6.

3. **Dynamic scoring solves the "difficulty misjudgment" problem** -- the CTFd parabolic formula automatically adjusts point values based on solve rates.

4. **25-30 challenges for a 4-hour event**, with ~20% warm-up, ~25% easy, ~35% medium, ~20% hard.

5. **Hint system should be generous for a learning-focused event**. 2-3 hints per challenge, first hint free, subsequent hints costing 10% of challenge value.

6. **Front-load easy wins**. The PicoCTF research proves that more introductory challenges = higher engagement, not lower quality.

7. **Include non-technical challenges** (OSINT, trivia, security awareness) so non-experts can participate meaningfully.

8. **The biggest mistake is jumping straight into technical challenges** for a general audience.

9. **Expect 80% of solves to come from Easy/Normal challenges** (Dragos data). Design accordingly.

10. **First blood bonuses should be small** to avoid demoralizing beginners when experts sweep early points.
