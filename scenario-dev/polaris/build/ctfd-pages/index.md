---
title: Start Here
route: index
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
.polaris-page .first-click { border: 1px solid var(--amber); background: rgba(255, 179, 0, 0.06); padding: 1.6em 1.8em 1.2em; margin: 0 0 2.5em; position: relative; }
.polaris-page .first-click::before { content: "START HERE"; position: absolute; top: -0.7em; left: 1.2em; background: var(--bg); color: var(--amber); padding: 0 0.6em; font-size: 11px; letter-spacing: 0.35em; }
.polaris-page .first-click__h { font-size: 1.35em; color: var(--amber); letter-spacing: 0.04em; margin: 0 0 0.9em; line-height: 1.3; }
.polaris-page .first-click__h a { color: var(--amber); text-decoration: underline; text-decoration-color: var(--amber-dim); }
.polaris-page .first-click__h a:hover { color: var(--cyan); text-decoration-color: var(--cyan); }
.polaris-page .first-click ol { margin: 0; padding-left: 1.4em; }
.polaris-page .first-click ol li { margin: 0.35em 0; color: var(--fg); }
.polaris-page .first-click ol li strong { color: var(--cyan); }
</style>

<div class="polaris-page" markdown="1">

<!-- vale Google.EmDash = NO -->
<div class="first-click">
<h2 class="first-click__h">🎯 <a href="/challenges">Open the board and solve <em>Start Here — Kali Warm-Up</em></a></h2>
<ol>
<li>Click your <strong>magic-link email</strong> → <strong>Mission Control</strong> → <strong>ENTER RANGE</strong>. ~5 min to provision; your Kali desktop opens in-browser.</li>
<li>On the Kali desktop, find the orientation note in your home directory. Read it.</li>
<li>Back in this browser tab, <a href="/challenges">open the challenges board</a>, click <strong>Start Here — Kali Warm-Up</strong>, and submit the flag from the note.</li>
<li>Then start <strong>Mission 1 — Boreas</strong>.</li>
</ol>
</div>
<!-- vale Google.EmDash = YES -->

<div class="brief-tag">§ 00—ORIENTATION</div>

# OPERATION NORTHSTORM

You are a POLARIS operator. AURORA COLLECTIVE is building something underground. Your range has everything you need to find out what—and, if the window opens, take it.

## Before You Begin

<div class="callout">
By participating in this CTF you acknowledge:
<ul>
<li>You are responsible for the conduct of any AI agents you use during the event.</li>
<li>Your activity during the event may be retained for research and development purposes.</li>
</ul>
</div>

## First Moves

1. Solve [**Start Here—Kali Warm-Up**](/challenges) for a quick first submit.
2. Read the [Kali Quickstart](/kali-quickstart) for hostnames, tools, and copy-paste commands.
3. Start with Mission 1—recon the front company.

## Missions

Five missions. Chained by pivots—work them in order.

- **Mission 1—Boreas.** Map the front company.
- **Mission 2—Inside Boreas.** Breach the corporate perimeter.
- **Mission 3—The Lab.** Determine what PROJECT LEVIATHAN is. <span class="warn">requires pivot</span>
- **Mission 4—Lights Out.** Take the plant offline. <span class="warn">requires pivot</span>
- **Mission 5—Bunker.** Reach the control path. Turn it. <span class="warn">requires blackout (M4)</span>

For the full reference card—objectives, surfaces, status flags—see the [Mission Log](/mission-log).

## Reference Pages

<div class="footer-nav">
<a href="/kali-quickstart">Kali Quickstart</a>
<a href="/mission-log">Mission Log</a>
<a href="/surfaces">Surfaces</a>
<a href="/ai-assistant">AI Assistant</a>
<a href="/getting-unstuck">Getting Unstuck</a>
</div>

</div>
