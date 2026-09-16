# Range-to-workspace scoping administration

Range-to-workspace scoping administration lets a workspace owner or admin see the
ranges scoped to a workspace and move a range from one workspace to another. It is
the **Range scoping** surface inside the **Administer** organization console,
reached under a selected workspace.

A range carries a workspace scope that says which workspace it belongs to. This
surface administers that scope only. It never changes who owns the range, its
lifecycle, or how the range is accessed.

## Access

- The surface is visible only to staff accounts, and only for a workspace where
  your role is owner or admin. A workspace member does not see it.
- Listing the ranges in a workspace and reassigning a range both require the
  workspace owner or admin role. A staff session alone is not sufficient, and a
  workspace owner who is not a staff account cannot use this surface.
- The controls a page shows are advisory. The server derives what applies and
  reauthorizes every request, so a hidden or disabled control is never the only
  thing standing between a caller and an action.

## Viewing ranges scoped to a workspace

Select a workspace in the console, then open **Range scoping**. The table lists
each range scoped to that workspace with its range identifier, its source, its
lifecycle status, the owner, and when it was created. The list is administrative
visibility only. It does not give you access to another user's range, and it does
not show range internals such as addresses, credentials, or the range
specification.

## Reassigning a range to another workspace

Use **Reassign** on a range row to move it to another workspace. You choose the
target from the workspaces you administer. A move requires all of the following,
and the server enforces each one:

- You hold the owner or admin role in both the current workspace and the target
  workspace.
- The range owner is already a member of the target workspace. The move never
  creates that membership, so the owner keeps the same access to the range after
  the move.
- The target workspace is active. You can move ranges out of an archived
  workspace to evacuate it, but you cannot move a range into an archived
  workspace.

Reassignment changes the workspace scope only. The range keeps its owner, its
source, its lifecycle status, its lease, and its access. Moving a range to the
workspace it already belongs to succeeds and changes nothing.

## What you cannot reassign here

- A range that belongs to a capture-the-flag event is managed by that event and
  cannot be reassigned from this surface. Its **Reassign** control is disabled.
- If the range and its projections have drifted out of agreement, or another
  administrator moves the same range at the same time, the move is refused rather
  than applied to a partly consistent state. Retry after the conflict clears.

## What this surface does not do

- It does not change the owner of a range or share a range with other members of
  a workspace.
- It does not open, operate, pause, destroy, extend, or connect to a range.
- It does not add or remove workspace members, and it does not change roles.
- It behaves identically on AWS and GCP deployments.
