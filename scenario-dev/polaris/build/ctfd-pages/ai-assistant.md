---
title: AI Assistant
route: ai-assistant
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
.polaris-page .mode { border-left: 3px solid var(--amber); background: rgba(255,179,0,0.04); padding: 1em 1.3em; margin: 1em 0; }
.polaris-page .mode__name { color: var(--amber); font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; font-size: 0.95em; display: block; margin-bottom: 0.3em; }
.polaris-page .mode__sub { color: var(--cyan); font-size: 0.78em; letter-spacing: 0.2em; text-transform: uppercase; margin-left: 0.5em; }
</style>

<div class="polaris-page" markdown="1">

<div class="brief-tag">§ 08 — AI ASSISTANT</div>

# WORKING WITH CLAUDE

Claude is pre-configured on your Kali box. It knows the operation context — who POLARIS is, what Boreas is, what the missions look like. Invoke it with:

```
claude
```

Ask it anything. Worst case, it declines gracefully.

## Three Modes

Naming the modes helps you pick the right one instead of defaulting to whatever comes to mind first.

<div class="mode">
<span class="mode__name">Advice / Analysis</span>
Claude explains, interprets, reasons. No action — just thinking together. Good for walking through a technique before you try it, asking what a piece of output means, or getting a second opinion on an ambiguous finding. Fastest turns. No execution risk.
</div>

<div class="mode">
<span class="mode__name">Co-Operator <span class="mode__sub">usually the sweet spot</span></span>
You drive, Claude is your wingman — writes the script you ask for, suggests the next step, debugs the command that didn't work. You decide what runs and when. Fast enough to move, slow enough to actually learn what you did. Most operator time is well spent here.
</div>

<div class="mode">
<span class="mode__name">Autonomous Operator</span>
Hand Claude a task and let it run for a stretch — enumerate something, try an attack and report back, parse a dataset. Useful for long-running work or parallel effort. Less useful when you're close to a flag and want full control over the final step.
</div>

Most operators spend most of the day in Co-Operator. Advice / Analysis before attempting a technique they haven't seen. Autonomous when they're waiting on something else.

## What Claude Brings

- Explains error messages, protocol behavior, and tool output.
- Writes exploit scripts from a description of the vulnerability you found.
- Parses binary, decodes formats, extracts fields from noisy data.
- Walks through attack techniques end-to-end.
- Translates between toolchains.
- Challenges your assumptions when your mental model is off.

## Workflow Tips

- **Give it real context.** Where you are, what you tried, what you got, what you expected. Vague context, vague answers.
- **Point it at files.** Claude reads paths on the Kali box directly — handing it a file path is faster than moving the contents around.
- **Ask for code, then read it.** Run exploit scripts knowing what they do, not on trust.
- **Push back on it.** If a suggestion fails, tell it. It will debug with you.
- **Switch modes deliberately.** Different work, different mode.

<div class="callout">
Claude is a force multiplier. Operators who name their mode, hand over context, and ask narrow questions move faster.
</div>

<div class="footer-nav">
<a href="/">Start Here</a>
<a href="/kali-quickstart">Kali Quickstart</a>
<a href="/mission-log">Mission Log</a>
<a href="/surfaces">Surfaces</a>
<a href="/getting-unstuck">Getting Unstuck</a>
</div>

</div>
