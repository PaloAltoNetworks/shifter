# CTF

Capture-the-flag events with scored challenges and a personal range per participant.

A CTF event is a time-boxed competition. Organizers publish a set of challenges; you
solve them by working inside your own isolated range and submitting the flags you
recover. Correct submissions earn points and move you up the scoreboard.

## Joining an Event

1. Open the registration link for the event (or the **CTF** area of the portal).
2. Complete registration before the event's registration deadline.
3. When the event opens, your dashboard shows the event status, your score, and the
   time remaining.

Registration closes at the deadline the organizer set. If the event is full
(`max_participants`), registration is refused.

## Your Range

Each participant gets a dedicated range built from the event's scenario. The range is
isolated from other participants' ranges.

- Open the **Range** page to see your range's status and connection details.
- Ranges are provisioned around event start; allow a few minutes for the range to
  become ready (the organizer sets a spin-up window).
- Connect to range instances with the same SSH/RDP terminal flow used elsewhere in
  the portal. See [Terminal](terminal).

You do not launch or destroy your CTF range yourself — the platform provisions it for
you and cleans it up after the event.

## Challenges

The **Challenges** page lists the challenges available to you.

| Field | Meaning |
|-------|---------|
| Category | The kind of challenge (web, forensics, etc.) |
| Points | Awarded on first correct flag for that challenge |
| Difficulty | Organizer-assigned difficulty label |
| Status | Locked, available, or solved |

Some challenges are released on a schedule or unlock only after you solve a
prerequisite, so the list can grow during the event.

## Submitting Flags

1. Open a challenge to read its description and target.
2. Recover the flag from your range.
3. Enter the flag in the submission box and submit.

Flags are checked server-side against a stored hash — the platform never holds your
flag in plaintext. Submissions are rate-limited: an event may set a cooldown between
attempts and a per-challenge attempt limit. A correct submission scores the
challenge's points the first time; later correct submissions for the same challenge do
not double-count.

## Hints

A challenge may offer hints. Taking a hint can reduce the points you earn for that
challenge, so the cost is shown before you reveal it.

## Teams and Brackets

If the event runs in team mode, you compete as part of a team (up to the event's team
size limit) and your team shares a score. Organizers may also group participants into
brackets so leaderboards are ranked within a cohort.

## Scoreboard

The **Scoreboard** ranks participants (or teams) by score. Organizers can:

- Hide the scoreboard entirely, or
- Freeze the scoreboard at a set time near the end so final standings are not
  revealed until the event closes.

Running a CTF as an organizer is covered in the
[CTF Organizer Guide](ctf-organizer-guide). The implementation is described in the
technical [CTF documentation](../technical/shifter_platform/ctf).
