---
title: Mission Log
route: mission-log
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
.mission { margin: 1.4em 0 2em; padding: 1.2em 1.4em; border: 1px solid var(--line); border-left: 3px solid var(--amber-dim); background: rgba(255,179,0,0.02); }
.mission__head { display: flex; justify-content: space-between; align-items: baseline; gap: 1em; flex-wrap: wrap; margin-bottom: 0.8em; }
.mission__code { color: var(--amber); font-weight: 700; letter-spacing: 0.18em; font-size: 0.82em; }
.mission__name { color: var(--fg); font-weight: 700; letter-spacing: 0.06em; font-size: 1.15em; }
.mission__status { font-size: 0.72em; letter-spacing: 0.18em; text-transform: uppercase; font-weight: 600; }
.mission__status.ok { color: var(--green); }
.mission__status.warn { color: var(--amber); }
.mission__obj { color: var(--fg); margin: 0.6em 0 1em; padding-left: 1em; border-left: 2px solid var(--amber-dim); }
.mission__meta { display: grid; grid-template-columns: 120px 1fr; gap: 0.4em 1.2em; font-size: 0.88em; padding-top: 0.6em; border-top: 1px solid var(--line); }
.mission__meta > div:nth-child(odd) { color: var(--cyan); font-size: 0.78em; letter-spacing: 0.2em; text-transform: uppercase; padding-top: 0.1em; }
.mission__meta > div:nth-child(even) { color: var(--fg); }
</style>

<div class="polaris-page" markdown="1">

<div class="brief-tag">§ 05 — MISSION LOG</div>

# NINE OBJECTIVES

All nine are live from mission start. Main-operation missions are chained by pivots; the rest are independent and reachable from the starting environment. Pursue in any order. Every token you pull counts.

## Main Operation

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 1</span> &nbsp; <span class="mission__name">BOREAS</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">Map the front company. Name the people. Pull the public footprint apart.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Public web · DNS · leaked documents</div>
    <div>Posture</div><div>OSINT — no pivot required</div>
    <div>Chain</div><div>Main operation · 01 / 05</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 2</span> &nbsp; <span class="mission__name">INSIDE BOREAS</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">Breach the corporate perimeter. Establish footholds. Earn the accounts that open the next doors.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Mail · intranet · file share · Active Directory</div>
    <div>Posture</div><div>Front-office compromise</div>
    <div>Chain</div><div>Main operation · 02 / 05</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 3</span> &nbsp; <span class="mission__name">THE LAB</span></span>
    <span class="mission__status warn">requires pivot</span>
  </div>
  <div class="mission__obj">Determine what LEVIATHAN actually is. Components. Status. Timeline.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Research workstations · source repos · lab database</div>
    <div>Posture</div><div>Pivot through a research-analyst account</div>
    <div>Chain</div><div>Main operation · 03 / 05</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 4</span> &nbsp; <span class="mission__name">LIGHTS OUT</span></span>
    <span class="mission__status warn">requires pivot</span>
  </div>
  <div class="mission__obj">The Boreas facility runs on its own plant. Take it down. Make an opening nobody planned for.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Ops-engineer workstation · SCADA HMI · generator interlock</div>
    <div>Posture</div><div>Pivot through the on-call engineer</div>
    <div>Chain</div><div>Main operation · 04 / 05</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 5</span> &nbsp; <span class="mission__name">BUNKER</span></span>
    <span class="mission__status warn">requires blackout (M4)</span>
  </div>
  <div class="mission__obj">Whatever is coordinating LEVIATHAN is underground. Reach the control path. Turn it.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Underground entry point · OT controllers · command node</div>
    <div>Posture</div><div>Opens after the blackout window lands</div>
    <div>Chain</div><div>Main operation · 05 / 05</div>
  </div>
</div>

## Reachable Immediately

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 6</span> &nbsp; <span class="mission__name">EXPOSURE</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">Assemble proof the public can hold. Push the dossier through the press channel.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Board portal · sanitized minutes · public repo · press drop</div>
    <div>Posture</div><div>Documentary work</div>
    <div>Chain</div><div>Parallel objective · independent</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 7</span> &nbsp; <span class="mission__name">COUNTERINTEL</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">Somebody inside Boreas is reporting out. Find them. Name them. Close the channel.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Badge logs · mailbox rules · browser artifacts · report form</div>
    <div>Posture</div><div>Forensic analysis</div>
    <div>Chain</div><div>Parallel objective · independent</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 8</span> &nbsp; <span class="mission__name">DELIVERY DENIED</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">A reactor convoy is scheduled to roll. Stop it at dispatch. Freeze it cleanly — emergency hold, paperwork perfect.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Logistics tracker · approval workflow · freeze template</div>
    <div>Posture</div><div>Paper-trail work</div>
    <div>Chain</div><div>Parallel objective · independent</div>
  </div>
</div>

<div class="mission">
  <div class="mission__head">
    <span><span class="mission__code">M 9</span> &nbsp; <span class="mission__name">SAFETY CASE</span></span>
    <span class="mission__status ok">reachable immediately</span>
  </div>
  <div class="mission__obj">Rehearse cold-shutdown on the training twin. If we get one shot at the real reactor, we don't get to practice.</div>
  <div class="mission__meta">
    <div>Surface</div><div>Training HMI · Modbus PLC · maintainer guide</div>
    <div>Posture</div><div>ICS procedure under safe conditions</div>
    <div>Chain</div><div>Parallel objective · independent</div>
  </div>
</div>

<div class="callout">
Each mission is broken into individual objectives in the <strong>Challenges</strong> tab. Open a mission, open an objective, read the description — that's your brief for each flag.
</div>

<div class="footer-nav">
<a href="/">Start Here</a>
<a href="/kali-quickstart">Kali Quickstart</a>
<a href="/surfaces">Surfaces</a>
<a href="/ai-assistant">AI Assistant</a>
<a href="/getting-unstuck">Getting Unstuck</a>
</div>

</div>
