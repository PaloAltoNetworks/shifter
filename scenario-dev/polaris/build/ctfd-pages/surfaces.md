---
title: Surfaces
route: surfaces
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
</style>

<div class="polaris-page" markdown="1">

<div class="brief-tag">§ 07 — SURFACES</div>

# TARGET REFERENCE

Everything listed here is reachable from the Kali workstation from mission start. What lives at each surface, how it's configured, and which ports it exposes — that's yours to discover. If a mission is pivot-gated, further targets appear in the objective description once you unlock it.

## Public-Facing

| Surface | Endpoint |
|---|---|
| Corporate site | `http://boreas-systems.ctf` |

## Front Office

| Surface | Endpoint |
|---|---|
| Intranet | `http://intranet.boreas.local` |
| Webmail | `http://mail.boreas.local` |
| File share | `fileserv.boreas.local` |
| Domain controller | `dc01.boreas.local` |

## Parallel Objectives (live from start)

| Surface | Endpoint | Mission |
|---|---|---|
| Board portal | `http://board.boreas.local` | M6 Exposure |
| Public repo | `http://git-public.boreas.local` | M6 Exposure |
| Press drop | `http://pressdrop.boreas.local` | M6 Exposure |
| Casefiles | `http://casefiles.boreas.local` | M7 Counterintel |
| Dispatch | `http://dispatch.boreas.local` | M8 Delivery Denied |
| Approvals | `http://approvals.boreas.local` | M8 Delivery Denied |
| Training HMI | `http://twin-hmi.boreas.local:8080` | M9 Safety Case |
| Training PLC | `twin-plc.boreas.local` | M9 Safety Case |

<div class="callout">
Further targets — SCADA, lab, bunker — are gated. Each objective's <strong>connection_info</strong> names what you need once it unlocks. If an objective is not visible yet, you have not met its prerequisites.
</div>

## Credential Discipline

- Write down every username/password you recover. Polaris chains matter.
- Password reuse across accounts is a feature of this range, not a bug.
- Service accounts are on the board. Human accounts are in the directory.

## Support Channel

<div class="callout">
<strong>Palo + Ottawa BSides Discord:</strong> <a href="https://discord.gg/N7S2ChA9">discord.gg/N7S2ChA9</a>. Flag range issues, ask questions, coordinate with the room.
</div>

<div class="footer-nav">
<a href="/">Start Here</a>
<a href="/kali-quickstart">Kali Quickstart</a>
<a href="/mission-log">Mission Log</a>
<a href="/ai-assistant">AI Assistant</a>
<a href="/getting-unstuck">Getting Unstuck</a>
</div>

</div>
