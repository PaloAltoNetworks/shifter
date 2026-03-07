# Phase 6: Participant Portal

## Overview

This phase implements the participant-facing views for the CTF competition. Participants access these views after registering via their invite link. The portal allows them to view challenges, submit flags, see the scoreboard, and access their range.

## Current State

### Completed
- Participant authentication decorators (`ctf_participant_required`)
- `ctf_login` view with invite token handling
- All participant URL routes defined
- View stubs returning placeholder templates
- Services: `submit_flag`, `use_hint`, `get_scoreboard`, `calculate_score`
- Template files exist (placeholder content)

### Pending
- Implement all participant views
- Implement flag submission API
- Implement scoreboard updates
- Build out templates with challenge UI
- WebSocket/polling for real-time scoreboard (optional)

## Implementation Tasks

### 6.1 Participant Registration Flow
**File:** `ctf/views.py` - enhance `ctf_login`

The login page already handles invite tokens. Need to implement the registration completion flow.

```python
def ctf_register(request: HttpRequest) -> HttpResponse:
    """Complete participant registration from invite link."""
```

**Flow:**
1. User clicks invite link with token
2. Validate token (not expired, participant not registered)
3. If user not logged in: redirect to Cognito login with return URL
4. If user logged in: link user to participant record
5. Call `register_participant(participant_id, user, cognito_sub)`
6. Redirect to participant dashboard

**URL:** `path("register/", views.ctf_register, name="ctf_register")`

### 6.2 Participant Dashboard
**File:** `ctf/views.py` (line ~123)

```python
@login_required
@ctf_participant_required
def participant_dashboard(request: HttpRequest) -> HttpResponse:
    """Participant main dashboard."""
```

**Requirements:**
- Get participant via `get_participant_by_user(request.user)`
- Get event details
- Show event status (upcoming/active/ended)
- Display quick stats: score, rank, solved challenges
- Show recent activity
- Quick links to challenges, scoreboard, range

**Template:** `ctf/participant/dashboard.html`

### 6.3 Participant Event View
**File:** `ctf/views.py` (line ~132)

```python
@login_required
@ctf_participant_required
def participant_event(request: HttpRequest) -> HttpResponse:
    """Participant event detail view."""
```

**Requirements:**
- Event description (Markdown rendered)
- Event schedule (start/end times with countdown)
- Rules and guidelines
- Participant's team info (if team mode)

**Template:** `ctf/participant/event.html`

### 6.4 Challenges List
**File:** `ctf/views.py` (line ~143)

```python
@login_required
@ctf_participant_required
def participant_challenges(request: HttpRequest) -> HttpResponse:
    """Participant challenges list."""
```

**Requirements:**
- Get available challenges via `get_available_challenges(event_id)`
- Group by category
- Show: name, points, difficulty, solve count
- Mark solved challenges with checkmark
- Show locked challenges (not yet released) as teaser
- Filter by category

**Template:** `ctf/participant/challenges.html`

### 6.5 Challenge Detail & Submission
**File:** `ctf/views.py` (line ~154)

```python
@login_required
@ctf_participant_required
def challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Participant challenge detail with submission form."""
```

**Requirements:**
- Challenge description (Markdown)
- Flag format hint
- Hint button (shows penalty, confirms before revealing)
- Flag submission form
- Previous attempts display
- Success/failure feedback
- First blood indicator

**Template:** `ctf/participant/challenge_detail.html`

### 6.6 Flag Submission API
**File:** `ctf/views.py` (line ~880)

```python
@login_required
@require_POST
def api_submit_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Submit flag for a challenge."""
```

**Request:**
```json
{
  "flag": "FLAG{...}"
}
```

**Response:**
```json
{
  "correct": true,
  "points_awarded": 100,
  "new_rank": 5,
  "first_blood": false,
  "message": "Correct! +100 points"
}
```

**Error Response:**
```json
{
  "correct": false,
  "attempts_remaining": 2,
  "message": "Incorrect flag. Try again."
}
```

### 6.7 Hint Usage API
**File:** `ctf/views.py` (line ~891)

```python
@login_required
@require_POST
def api_use_hint(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Use hint for a challenge."""
```

**Response:**
```json
{
  "hint": "The flag contains...",
  "penalty_applied": 10,
  "new_max_points": 90
}
```

### 6.8 Scoreboard View
**File:** `ctf/views.py` (line ~181)

```python
@login_required
@ctf_participant_required
def scoreboard(request: HttpRequest) -> HttpResponse:
    """Public scoreboard view."""
```

**Requirements:**
- Call `get_scoreboard(event_id)` or `get_team_scoreboard` for team mode
- Show rank, name/team, score, solves, last solve time
- Highlight current participant
- Auto-refresh (polling or WebSocket)
- Optional: score graph over time

**Template:** `ctf/participant/scoreboard.html`

### 6.9 Scoreboard API
**File:** `ctf/views.py` (line ~971)

```python
@login_required
@require_GET
def api_scoreboard(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get scoreboard data."""
```

Returns scoreboard data for AJAX updates.

### 6.10 Range Access View
**File:** `ctf/views.py` (line ~170)

```python
@login_required
@ctf_participant_required
def participant_range(request: HttpRequest) -> HttpResponse:
    """Participant range status and access."""
```

**Requirements:**
- Show range provisioning status
- Display connection info when ready (IP, credentials)
- Guacamole iframe or link
- Troubleshooting tips

**Template:** `ctf/participant/range.html`

### 6.11 Team Views (Team Mode Only)
**File:** `ctf/views.py` (lines ~192, ~203)

```python
@login_required
@ctf_participant_required
def participant_team(request: HttpRequest) -> HttpResponse:
    """Participant team view."""

@login_required
@ctf_participant_required
def team_join(request: HttpRequest) -> HttpResponse:
    """Join a team using invite code."""
```

**Requirements:**
- Show team members, captain
- Team score and ranking
- Leave team option
- Join team form with invite code

### 6.12 Submissions API
**File:** `ctf/views.py` (line ~904)

```python
@login_required
@require_GET
def api_submissions(request: HttpRequest) -> JsonResponse:
    """API: Get submissions for current user."""
```

Returns participant's submission history.

## Templates

### dashboard.html
- Hero section with event name, countdown
- Stats cards (rank, score, solves)
- Challenge progress bar
- Recent activity feed
- Quick action buttons

### challenges.html
- Category tabs/filters
- Challenge cards in grid
- Difficulty badges
- Points display
- Solved indicator

### challenge_detail.html
- Challenge description (Markdown)
- Flag input with submit button
- Hint reveal button with warning modal
- Attempt history
- Success celebration animation

### scoreboard.html
- Leaderboard table
- Current user highlight
- Auto-refresh indicator
- Optional: live update animation

### range.html
- Status indicator (provisioning/ready/error)
- Connection info card
- Guacamole embed or link
- Credentials display

## Testing Requirements

### Unit Tests
- `test_participant_dashboard`: Verify data display
- `test_challenge_list`: Filter, categorization, solved status
- `test_challenge_detail`: Description, submission form
- `test_flag_submission`: Correct/incorrect, rate limit, already solved
- `test_hint_usage`: Penalty calculation, tracking
- `test_scoreboard`: Ranking accuracy, tie-breaking

### Integration Tests
- Full solve flow: view challenge -> submit flag -> see updated score
- Hint flow: request hint -> reduced points on solve
- Registration flow: invite link -> login -> participate

## Security Considerations

- Rate limit flag submissions (prevent brute force)
- Don't expose flag hash in any response
- Validate participant belongs to challenge's event
- Hide unreleased challenges completely
- Log all submission attempts (audit trail)

## Dependencies

- Phase 5 complete (participants can be invited/registered)
- Cognito integration for authentication
- Range integration (Phase 7) for full range view

## Estimated Effort

| Task | Hours |
|------|-------|
| 6.1 Registration Flow | 3 |
| 6.2 Dashboard | 3 |
| 6.3 Event View | 1 |
| 6.4 Challenges List | 3 |
| 6.5 Challenge Detail | 4 |
| 6.6-6.7 Flag/Hint APIs | 3 |
| 6.8-6.9 Scoreboard | 4 |
| 6.10 Range View | 2 |
| 6.11 Team Views | 3 |
| Templates & Styling | 6 |
| Testing | 6 |
| **Total** | **38** |
