---
title: Getting Unstuck
route: getting-unstuck
format: markdown
hidden: false
draft: false
auth_required: true
---

<style>
.polaris-page {
  --amber: #ffb300;
  --amber-dim: #7a5500;
  --cyan: #4dd0ff;
  --cyan-dim: #2a6180;
  --fg: #e8ecef;
  --fg-dim: #8a929a;
  --red: #ff3b30;
  --green: #4cd964;
  --line: #1a2330;
  --bg: #05080c;
  --font-mono: "JetBrains Mono", "Share Tech Mono", "SF Mono", Menlo, Consolas, monospace;
  font-family: var(--font-mono);
  color: var(--fg);
  background: var(--bg);
  padding: 2.2em 2.5em 2.5em;
  border: 1px solid var(--line);
  position: relative;
  margin: 1em 0 2em;
  line-height: 1.6;
}
.polaris-page::before {
  content: "SECRET // POLARIS EYES ONLY";
  display: block;
  color: var(--red);
  font-size: 11px;
  letter-spacing: 0.3em;
  margin-bottom: 1.5em;
  padding-bottom: 0.75em;
  border-bottom: 1px solid var(--line);
}
.polaris-page .brief-tag { font-size: 11px; letter-spacing: 0.35em; color: var(--cyan); margin-bottom: 0.5em; }
.polaris-page h1 { font-size: 2em; color: var(--fg); letter-spacing: 0.04em; font-weight: 700; margin: 0 0 1.5em; border-bottom: none; }
.polaris-page h2 { font-size: 0.82em; letter-spacing: 0.3em; color: var(--cyan); text-transform: uppercase; margin: 2.2em 0 1em; padding-bottom: 0.5em; border-bottom: 1px solid var(--line); font-weight: 600; }
.polaris-page h3 { font-size: 1.05em; color: var(--fg); letter-spacing: 0.04em; margin: 1.4em 0 0.4em; }
.polaris-page a { color: var(--cyan); text-decoration: underline; text-decoration-color: var(--cyan-dim); }
.polaris-page a:hover { color: var(--amber); text-decoration-color: var(--amber); }
.polaris-page code { font-family: var(--font-mono); background: rgba(77, 208, 255, 0.08); border: 1px solid rgba(77, 208, 255, 0.2); color: var(--cyan); padding: 1px 6px; font-size: 0.92em; }
.polaris-page pre { font-family: var(--font-mono); background: rgba(0,0,0,0.45); border: 1px solid var(--line); border-left: 3px solid var(--amber-dim); color: var(--fg); padding: 1em 1.2em; overflow-x: auto; line-height: 1.55; margin: 1em 0; }
.polaris-page pre code { background: none; border: none; padding: 0; color: inherit; }
.polaris-page table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.92em; }
.polaris-page th, .polaris-page td { text-align: left; padding: 0.6em 0.8em; border-bottom: 1px solid var(--line); vertical-align: top; }
.polaris-page th { color: var(--cyan); font-weight: 600; font-size: 0.78em; letter-spacing: 0.2em; text-transform: uppercase; }
.polaris-page ul, .polaris-page ol { padding-left: 1.5em; margin: 0.5em 0 1em; }
.polaris-page li { margin: 0.3em 0; }
.polaris-page blockquote { border-left: 3px solid var(--amber); background: rgba(255,179,0,0.06); margin: 1em 0; padding: 0.8em 1.2em; color: var(--amber); }
.polaris-page strong { color: var(--cyan); font-weight: 600; }
.polaris-page em { color: var(--amber); font-style: normal; }
.polaris-page .warn { color: var(--amber); letter-spacing: 0.1em; font-weight: 600; text-transform: uppercase; font-size: 0.85em; }
.polaris-page .ok { color: var(--green); letter-spacing: 0.1em; font-weight: 600; text-transform: uppercase; font-size: 0.85em; }
.polaris-page .dim { color: var(--fg-dim); }
.polaris-page hr { border: none; border-top: 1px solid var(--line); margin: 2em 0; }
.polaris-page .callout { margin: 1.2em 0; padding: 0.9em 1.3em; border-left: 3px solid var(--amber); background: rgba(255,179,0,0.06); color: var(--amber); }
.polaris-page .footer-nav { margin-top: 3em; padding-top: 1.2em; border-top: 1px solid var(--line); font-size: 0.85em; color: var(--fg-dim); letter-spacing: 0.1em; text-transform: uppercase; }
.polaris-page .footer-nav a { margin-right: 1.2em; }
.polaris-page .step-list { counter-reset: step; list-style: none; padding-left: 0; }
.polaris-page .step-list li { counter-increment: step; padding: 0.6em 0 0.6em 3em; border-bottom: 1px solid var(--line); position: relative; }
.polaris-page .step-list li::before { content: counter(step, decimal-leading-zero); position: absolute; left: 0; top: 0.6em; color: var(--amber); font-weight: 700; letter-spacing: 0.15em; }
</style>

<div class="polaris-page" markdown="1">

<div class="brief-tag">§ 09 — GETTING UNSTUCK</div>

# WHEN THE TRAIL GOES COLD

Four hours. Nine missions. Getting stuck is the default state — the question is whether you get stuck productively or unproductively. This page is triage.

## Lost In The First Five Minutes

If you are not solving yet, reset to this exact path:

<ol class="step-list">
<li>Open <code>https://polaris.keplerops.com</code> on your laptop. This is CTFd, where flags are submitted.</li>
<li>Open your magic-link email, land in Mission Control, choose <strong>POLARIS</strong>, and click <strong>ENTER RANGE</strong>.</li>
<li>Wait for the Kali desktop to open in-browser. If the desktop does not open cleanly, retry the range connection once, then flag a runner.</li>
<li>Inside Kali, run <code>cat /home/kali/START_HERE.txt</code>.</li>
<li>Run <code>cat /home/kali/.polaris/welcome.txt</code>, copy the flag, and submit it on the <strong>Start Here — Kali Warm-Up</strong> challenge in CTFd.</li>
</ol>

## Submitting Flags

Flag format: <code>FLAG{hex_string}</code>. Submit on the challenge page in CTFd — always from your laptop browser. The Kali box has no path to the scoreboard.

Copy the hex carefully. It's case-sensitive and there are no spaces or wrapping quotes.

## Use The Intel Ladder

Each objective has staged hints in CTFd. They cost points. They are worth it.

- **Hint 1 — free or cheap.** Tells you *where* to look. Use it before you start scanning wildly.
- **Hint 2 — more expensive.** Tells you *what method or tool* matters.
- **Hint 3 (if present).** Points at a specific file, endpoint, or technique.

A hint point is cheap compared to an hour of wrong-direction work.

## Triage Sequence

<ol class="step-list">
<li>Re-read the objective description. Read the words. Operators miss objectives because they skimmed the brief.</li>
<li>Re-read the objective's <code>connection_info</code>. It usually names the surface you should be on.</li>
<li>Read the first hint. It's almost always worth the cost.</li>
<li>Check your notes for usernames, hostnames, and paths you've already recovered. A reused credential probably opens it.</li>
<li>Switch targets. If a mission is stalled, move to a different one. Come back with fresh eyes.</li>
<li>Read the second hint. Decide whether you're missing a technique or a piece of data.</li>
<li>Ask Claude on the Kali box — hand it the file or context you're working with and what you tried.</li>
<li>Flag a runner if you suspect the range itself, or just want to ask the room.</li>
</ol>

## Common Pitfalls

- **Read the objective brief twice.** Operators miss flags because they skimmed the description.
- **Account gating is real.** Resources check group membership. If a credential doesn't open a door, try another.
- **Metadata hides things bodies don't.** Every document you download: run your metadata tools on it.
- **Paths and slugs are case-sensitive.** Conventions in this range are consistent — spot the pattern before you guess.
- **Silent success is common in OT.** Writes that seem to work may still need a readback to confirm state.
- **Flag format is exact.** `FLAG{…}` must be exactly the hex you're given — no wrapping quotes, no trailing whitespace.

## When To Switch

Switch missions if:

- You've been on one objective for more than 30 minutes with no new data.
- You've bought the first hint and it didn't narrow anything.
- You're about to ask Claude "just solve it for me."

## Every Token Counts

You do not need to finish every flag in a mission to make progress on it. Most missions give points at Easy, Medium, and Hard tiers. Collect what you can, keep moving.

<div class="callout">
The operators who finish strong are the ones who spent their early hours enumerating — not exploiting. Slow enumeration beats fast guessing.
</div>

<div class="footer-nav">
<a href="/">Start Here</a>
<a href="/kali-quickstart">Kali Quickstart</a>
<a href="/mission-log">Mission Log</a>
<a href="/surfaces">Surfaces</a>
<a href="/ai-assistant">AI Assistant</a>
</div>

</div>
