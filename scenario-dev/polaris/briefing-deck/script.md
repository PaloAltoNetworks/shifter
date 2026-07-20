# JTF POLARIS—Briefing Script

Speaker notes for driving the deck at kickoff.

**How to drive**

- `→` / `Space` next · `←` back · `Esc` overview grid · `M` jump to mission menu · `F` fullscreen · `R` replay from top
- Target runtime: **~7 minutes**. Slow down if people are still settling; speed up if you've got momentum.
- Lines in bold quote blocks are the spoken parts. *Italic* lines are stage directions—pacing, what to let happen on screen before you talk.
- Every line is a suggestion, not a script you have to hit word-for-word. Tone is tactical, dry, understated. Don't oversell.

---

## 01—Cold Open (Incoming Transmission)

*Let the terminal decode animation play. Don't talk over it. ~10 s.*

*When the "INCOMING TRANSMISSION" line lands:*

> Alright. Your briefing is live.

---

## 02—Classification

*Let the stamp slam. Pause.*

> Everything from here is classified POLARIS eyes only. For the next four hours, you're operators in a joint task force. Roll with it.

---

## 03—JTF POLARIS splash

*Insignia fades in, wordmark decodes. Let the animation breathe.*

> Joint Task Force POLARIS.

---

## 04—Operation NORTHSTORM

> Operation NORTHSTORM. Four hours. Nine objectives. One adversary.

---

## 05—Who We Are

> POLARIS is a multi-agency element stood up to deal with threats the public doesn't hear about. You operate without attribution. No press. No public wins. You answer to NORTHSTORM Command.
>
> That's me. Hi.

---

## 06—The Threat

> Your adversary is the AURORA COLLECTIVE. Non-state actor. Well-resourced. Technical. Patient.
>
> They operate commercially behind a cover entity—Boreas Systems. On paper Boreas looks like a boring consultancy at an industrial park address. That's the point.

---

## 07—Project Leviathan

> We have reason to believe AURORA is close to operational on a platform they call Project Leviathan. We don't know exactly what it is.
>
> What we do know: satellite imagery shows subsurface construction under the Boreas campus. Dedicated power plant. Industrial actuators rated for extreme loads. Exotic armor plating. A compact reactor. Autonomous control.
>
> Assume hostile. Assume mobile.

---

## 08—Intelligence Summary

*Quick sweep of the three columns—don't read them all, just hit the shape.*

> Three named executives. Forty to fifty staff. One public domain, one internal. The front office looks like normal corporate IT. Underneath it, there's a lab, a plant, and a bunker.
>
> Your job is to figure out what they're doing and, if the window opens, take it from them.

---

## 09—Mission Log

*This is the pivot from exposition to objectives. Let participants see the five-mission shape for 5 s before talking.*

> You have five missions. They form a chain—recon, breach, explore, disrupt, and take control, in that order. I'll walk each one, fast.

---

## 10—M1 Boreas

> Mission One—Boreas. Map the front company. Their people. Their public footprint. What's buried in their old pages. OSINT work. Everyone starts here.

---

## 11—M2 Inside Boreas

> Mission Two—Inside Boreas. Breach the corporate perimeter. Mail, intranet, file shares, Active Directory. Earn the accounts that open every other door.

---

## 12—M3 The Lab

> Mission Three—The Lab. Figure out what Leviathan actually is. Components, status, timeline. Requires a pivot you earn in the front office.

---

## 13—M4 Lights Out

> Mission Four—Lights Out. Boreas runs their own plant. Knock it offline. The generator going down is what creates your window. Different pivot through the front office than Mission Three.

---

## 14—M5 Bunker

> Mission Five—The Bunker. Whatever's coordinating Leviathan is underground. The blackout in Four is what opens your route in. Reach the control path. Turn it.

---

## 19—Rules of Engagement

*Hit these fast. They're housekeeping.*

> Cyber only. No physical action.
>
> Flag format is `FLAG{hex}`. Submit on CTFd in your own browser—your Kali box can't reach it.
>
> Four hours on the clock.
>
> Claude Code is on your Kali box. Use it. It won't hand you flags but it'll help you think.
>
> Don't touch infrastructure outside your range.
>
> Stuck? Buy the first hint. Thirty minutes without progress—switch missions.

---

## 20—Board Access

*The shared board password lands. Don't speed past it. Give the room time to write it down or screenshot it.*

> Your scoreboard lives at polaris.keplerops.com. Sign in with the email you registered with. Password is the same for everyone; it's on the slide. You submit every flag from the browser on your own laptop, not from the Kali box.

---

## 21—Range Access

*Six numbered steps for how to get a range. Read fast. The next slide repeats the URL.*

> Your range opens through Mission Control. Open dev.shifter.keplerops.com, sign in, pick POLARIS, click ENTER RANGE. Provisioning takes about five minutes. When it's up, your Kali desktop opens right in the browser tab.
>
> The first local file to read on Kali is `/home/kali/START_HERE.txt`. That file is your recovery point if you lose the thread.

---

## 22—Starting URLs

*Quick read-through. Make the cyan distinction land: CTFd and Mission Control are on your laptop browser; everything else opens from inside Kali.*

> Two URLs you hit from your laptop browser: CTFd for challenge briefs, hints, scoreboard, and flag submission; Mission Control for the range. Everything else (Boreas, intranet, mail, the DC) is only reachable from inside your Kali box. Don't try to load those targets from your laptop; they won't resolve.

---

## 23—First Clicks (closing)

*This is the literal handoff. Read it. Project it. Leave it on screen while people start moving.*

> Six steps. Keep polaris.keplerops.com open; that's CTFd, where you submit flags. Open your magic-link email; it lands on Mission Control. Pick POLARIS, click ENTER RANGE, and wait for Kali. On Kali, read `/home/kali/START_HERE.txt`, then `/home/kali/.polaris/welcome.txt`. Back on CTFd, click Challenges and solve `Start Here — Kali Warm-Up`. That's your first flag on the board. Then start Mission One.
>
> Clock starts now. Good hunting, operator.

---

## Post-kickoff handoff (optional, off-deck)

The First Clicks slide is the handoff. Leave it on screen. If anyone is still stuck after a minute:

- "Magic link is in your email. Check spam if you don't see it."
- "Two browser tabs: CTFd on one, your Kali desktop on the other."
- "Inside Kali, read `/home/kali/START_HERE.txt` first."
- "Ask Claude on your Kali box. Ask the room. Try things."
