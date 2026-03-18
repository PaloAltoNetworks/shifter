# Box Count Estimation: 4-Hour AI-Assisted CTF

Estimates for the number and difficulty range of target boxes needed per participant range, given a 4-hour event with AI assistance (Claude Code on Kali) and skill levels ranging from zero experience to experienced national security cyber operators.

---

## Constraints

| Constraint | Value |
|------------|-------|
| Event duration | 4 hours (240 minutes) |
| Participants | 50-100 |
| Deployment model | 1 range per participant (isolated) |
| AI assistance | Claude Code on every Kali box |
| Skill range | No experience through nat-sec cyber operators |
| Format | Boot2Root (user flag + root flag per box) |
| Existing reference | UVic scenario: 5 target boxes (1 walkthrough + 4 challenges) |

---

## Approach: Work Backward from Time Budget

### Available Time After Setup

| Phase | Duration | Notes |
|-------|----------|-------|
| Environment orientation | 10 min | Login, find terminal, test connectivity |
| Group walkthrough (Box 0) | 15-20 min | Guided, everyone does together |
| Independent hacking | ~200 min | The core of the event |
| Buffer / breaks | 10-15 min | Natural pauses, questions |
| **Effective hacking time** | **~200 min** | |

### Estimated Solve Times by Skill and Difficulty (AI-Assisted)

These estimates account for Claude Code assistance. Times include both user flag and root flag.

| Box Difficulty | Beginner + AI | Intermediate + AI | Advanced + AI | Expert + AI |
|---------------|--------------|-------------------|--------------|-------------|
| Walkthrough | 15-20 min | 10-15 min | 5-10 min | 5 min |
| Easy | 30-45 min | 15-25 min | 10-15 min | 8-12 min |
| Medium | 60-90 min* | 30-45 min | 20-30 min | 15-20 min |
| Hard | Stuck | 60-90 min* | 35-50 min | 25-35 min |

*May only get user flag, not root.

---

## Box Budget Per Skill Segment

### Beginners (15-20% of audience)

**Time budget**: 200 min of independent time.

| Activity | Time | Boxes |
|----------|------|-------|
| Walkthrough (Box 0) | 20 min | 1 |
| Easy boxes | 30-45 min each | 3-4 |
| Attempt 1 Medium (may not root) | 60+ min | 1 |
| **Total boxes touched** | | **5-6** |

Beginners will spend most of their time on easy boxes with AI coaching them through. They may attempt a medium box toward the end. They need enough easy content to stay busy for 4 hours.

### Intermediate (30-35% of audience -- largest segment)

**Time budget**: 200 min of independent time.

| Activity | Time | Boxes |
|----------|------|-------|
| Walkthrough (Box 0) | 10-15 min | 1 |
| Easy boxes | 15-25 min each | 2-3 |
| Medium boxes | 30-45 min each | 2-3 |
| Attempt 1 Hard (may not root) | 45+ min | 0-1 |
| **Total boxes touched** | | **6-8** |

Intermediate participants will clear easy boxes relatively quickly and spend most of their time on medium boxes. They're the critical design target -- this is the largest segment and the range where engagement is most at risk.

### Advanced (15-20% of audience)

**Time budget**: 200 min of independent time.

| Activity | Time | Boxes |
|----------|------|-------|
| Walkthrough (Box 0) | 5-10 min | 1 |
| Easy boxes (speed through) | 10-15 min each | 2-4 |
| Medium boxes | 20-30 min each | 2-3 |
| Hard boxes | 35-50 min each | 1-2 |
| **Total boxes touched** | | **8-10** |

Advanced participants will blow through easy content and spend their time on medium and hard boxes. They need hard content to stay challenged.

### Expert (5-10% of audience)

**Time budget**: 200 min of independent time.

| Activity | Time | Boxes |
|----------|------|-------|
| Walkthrough (Box 0) | 5 min | 1 |
| Easy boxes (speed through) | 8-12 min each | 3-5 |
| Medium boxes | 15-20 min each | 2-3 |
| Hard boxes | 25-35 min each | 2-3 |
| **Total boxes touched** | | **10-12** |

Experts with AI will be fast. They need enough total content that clearing everything in 4 hours is unlikely but possible. The hard boxes should require non-obvious attack chains that AI can't trivially solve.

---

## Recommended Box Count

### The Number

**10 target boxes + 1 walkthrough = 11 boxes per range.**

This is the minimum to keep all skill levels engaged for 4 hours. Here's the reasoning:

| Factor | Rationale |
|--------|-----------|
| Beginners need 5-6 boxes | 1 walkthrough + 4-5 easy/medium boxes |
| Intermediates need 6-8 boxes | Need enough medium content to fill 200 min |
| Advanced need 8-10 boxes | Must not run out of content |
| Experts need 10-12 boxes | Should have a realistic chance of clearing all, but it should be tight |
| AI acceleration | Adds ~30-50% more boxes attempted vs non-AI event |
| 4-hour limit | Caps how much even experts can complete |

### Why Not Fewer?

The UVic scenario has 5 target boxes. That worked for a 90-minute event with a narrower skill range. For 4 hours with experts:
- 5 boxes: Expert clears all in ~90 min, bored for 2.5 hours
- 7 boxes: Expert clears all in ~2-2.5 hours, bored for 1.5 hours
- 10 boxes: Expert is busy for 3-3.5 hours, tight finish

### Why Not More?

Each additional box means:
- Another AMI to build and maintain
- Another EC2 instance per participant range (50-100 instances)
- More provisioning time
- More QA/testing effort
- Diminishing engagement returns (beginners won't touch boxes 8-12)

10 boxes is the sweet spot where infrastructure cost is manageable and content covers the full skill range.

---

## Recommended Difficulty Distribution

### Distribution

| Tier | Count | Percentage | Boxes |
|------|-------|-----------|-------|
| Walkthrough | 1 | 9% | Box 0 |
| Easy | 3 | 27% | Boxes 1-3 |
| Medium | 4 | 36% | Boxes 4-7 |
| Hard | 3 | 27% | Boxes 8-10 |
| **Total** | **11** | **100%** | |

### Rationale

| Design Choice | Reason |
|---------------|--------|
| 1 walkthrough | Same as UVic -- group exercise, teaches the pattern |
| 3 easy | Enough for beginners to have a full experience (walkthrough + 3 easy = 4 boxes = ~2 hours of beginner content) |
| 4 medium | Largest tier -- serves the largest audience segment (intermediate). Also accessible to advanced participants. |
| 3 hard | Enough to challenge experts for 1.5-2 hours. Advanced participants will attempt 1-2. |

### Comparison to Industry Benchmarks

| Source | Easy | Medium | Hard | Expert |
|--------|------|--------|------|--------|
| CTFd educational recommendation | 35% | 35% | 25% | 5% |
| CTFd conference recommendation | 10% | 25% | 40% | 25% |
| Dragos CTF solve distribution | ~80% of solves | | ~6% of solves | |
| **Our distribution** | **36% (walk+easy)** | **36%** | **27%** | **--** |

We're aligned with the educational/conference hybrid, which matches our mixed-skill audience.

---

## Platform Mix

### OS and Technology Spread

The UVic scenario is 3 Linux + 2 Windows. For 10 boxes, the research suggests:

| Platform | Count | Rationale |
|----------|-------|-----------|
| Linux | 6-7 | Core pentest fundamentals, accessible at all levels |
| Windows | 3-4 | Enterprise-relevant, important for nat-sec audience |
| **of which AD** | **1** | Active Directory is the capstone for advanced/expert |

### Attack Category Spread

| Category | Boxes | Difficulty Tier |
|----------|-------|----------------|
| Web exploitation | 2-3 | Easy, Medium |
| Linux privilege escalation | 3-4 | Easy, Medium, Hard |
| Windows exploitation | 2-3 | Medium, Hard |
| Credential discovery / reuse | 2-3 | Woven through Easy-Hard |
| Active Directory | 1 | Hard |
| Container / modern infra | 0-1 | Medium-Hard (stretch goal) |

---

## Scoring Model

### Points Per Box

| Item | Base Points | Dynamic Range |
|------|-------------|--------------|
| User flag (any box) | 100 | Decreases as more solve |
| Root flag (walkthrough) | -- | Not scored |
| Root flag (easy) | 200 | |
| Root flag (medium) | 200 | |
| Root flag (hard) | 200 | |
| First blood bonus | +50 | Per flag, first solver only |

With dynamic scoring, easy flags solved by many participants decay in value while hard flags retain value. This naturally rewards tackling harder content.

### Maximum Possible Score

| Component | Count | Base | Max |
|-----------|-------|------|-----|
| User flags (boxes 1-10) | 10 | 100 | 1,000 |
| Root flags (boxes 1-10) | 10 | 200 | 2,000 |
| First blood bonuses | 20 | 50 | 1,000 |
| **Theoretical maximum** | | | **4,000** |

With dynamic scoring, actual max will be lower (easy flags decay). Expected top scorer: 2,500-3,500 points.

---

## Expected Outcomes by Skill Level

| Skill Level | Boxes Completed (user+root) | Approximate Score | % of Max |
|-------------|---------------------------|-------------------|----------|
| Beginner | 2-4 (mostly user flags) | 300-600 | 8-15% |
| Intermediate | 4-6 | 800-1,400 | 20-35% |
| Advanced | 7-9 | 1,500-2,200 | 38-55% |
| Expert | 9-11 | 2,200-3,000+ | 55-75%+ |

This score distribution creates a healthy spread where everyone has points, there's clear differentiation, and clearing everything is a genuine accomplishment.

---

## Box Chain Opportunities

Some boxes should interconnect (credentials from one box unlock another), creating natural progression:

| Dependency | Example |
|------------|---------|
| Easy box creds used on Medium box | Like UVic Box 3 (.env) -> Box 4 (Vault) |
| Medium box intel unlocks Hard box | Discovery on a medium box reveals a hidden service or credential for a hard box |

This provides guided progression for intermediate participants while experts can independently discover the same connections. Recommend 2-3 such chains across the 10 boxes, with the majority of boxes being independently solvable.

---

## Infrastructure Impact

### Per-Range Resource Estimate

| Component | Count | Instance Type (est.) |
|-----------|-------|---------------------|
| Kali (attacker) | 1 | t3.medium |
| Linux targets (easy/medium) | 5-6 | t3.micro or t3.small |
| Linux targets (hard) | 1-2 | t3.small |
| Windows targets | 2-3 | t3.medium |
| Windows AD (if included) | 1 | t3.medium or t3.large |
| **Total per range** | **11-12** | |

### Fleet Size

| Participants | Instances per Range | Total Instances |
|-------------|-------------------|----------------|
| 50 | 12 | 600 |
| 75 | 12 | 900 |
| 100 | 12 | 1,200 |

### Estimated Hourly Cost

| Participants | Est. Hourly Cost | Est. 4-Hour Cost |
|-------------|-----------------|-----------------|
| 50 | ~$15-20/hr | ~$60-80 |
| 75 | ~$22-30/hr | ~$90-120 |
| 100 | ~$30-40/hr | ~$120-160 |

These are rough estimates assuming on-demand pricing. Actual costs depend on instance types, region, and whether spot instances are viable for targets.

---

## Summary

| Parameter | Value |
|-----------|-------|
| Total boxes per range | 11 (1 walkthrough + 10 targets) |
| Difficulty distribution | 1 walkthrough, 3 easy, 4 medium, 3 hard |
| Platform mix | 6-7 Linux, 3-4 Windows (including 1 AD) |
| Flags per box | 2 (user + root) |
| Total flags | 20 scorable (+ 2 walkthrough) |
| Max theoretical score | ~4,000 (dynamic scoring reduces actual) |
| Expected expert completion | 9-11 boxes in 4 hours (tight) |
| Expected beginner completion | 2-4 boxes in 4 hours (satisfying) |
| Instances per range | ~12 |
| Fleet size (100 participants) | ~1,200 instances |
