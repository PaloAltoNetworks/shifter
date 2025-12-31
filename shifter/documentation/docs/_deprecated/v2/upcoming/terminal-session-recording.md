# Terminal UI: Session Recording

## Summary

Record terminal sessions for replay, review, and documentation. Supports export and playback.

## Problem

Users running demos or purple team exercises have no way to:
- Review what happened during a session
- Share terminal activity with colleagues
- Document attack chains for training
- Audit range usage

## Proposed Features

### 1. Session Recording

Capture all terminal I/O with timestamps.

```
┌─────────────────────────────────────────────────────────────────┐
│ ATTACKER · Kali                          [● REC] [⏹ Stop]      │
├─────────────────────────────────────────────────────────────────┤
```

**Behavior:**
- Toggle recording per terminal or globally
- Red dot indicator when recording
- Captures: output, input (optional), timestamps
- Stored server-side associated with range

### 2. Recording Format

Use asciicast v2 format (compatible with asciinema):

```json
{"version": 2, "width": 120, "height": 30, "timestamp": 1234567890}
[0.0, "o", "root@kali:~# "]
[0.5, "i", "whoami"]
[0.6, "o", "whoami\r\n"]
[0.7, "o", "root\r\n"]
[0.8, "o", "root@kali:~# "]
```

**Fields:**
- `o`: output event
- `i`: input event (optional, for full replay)
- Timestamp: seconds since recording start

### 3. Playback UI

Embedded player for recorded sessions.

```
┌─────────────────────────────────────────────────────────────────┐
│ Recording: Kali - 2024-01-15 14:30          [▶] [⏸] [1x ▼]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  root@kali:~# nmap -sV 10.1.1.20                               │
│  Starting Nmap 7.94...                                         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ ◀ [━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━] ▶  2:15 / 8:30    │
└─────────────────────────────────────────────────────────────────┘
```

**Controls:**
- Play/pause
- Seek via progress bar
- Playback speed: 0.5x, 1x, 2x, 4x
- Jump to timestamp

### 4. Export Options

- **Download asciicast**: `.cast` file for asciinema player
- **Download text**: Plain text transcript
- **Copy link**: Shareable playback URL (if hosted)

### 5. Recording Storage

**Backend:**
- Recordings stored in S3 bucket
- Metadata in Range model or separate Recording model
- Auto-cleanup with range deletion
- Size limits (e.g., 50MB per recording)

**Model:**
```python
class TerminalRecording(models.Model):
    range = models.ForeignKey(Range)
    instance_role = models.CharField()  # 'attacker', 'target'
    instance_name = models.CharField()  # 'kali', 'win-dc'
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True)
    s3_key = models.CharField()
    size_bytes = models.IntegerField()
```

### 6. Recording Controls

**Per-terminal:**
- Start/stop recording button in header
- Recording indicator (red dot)

**Global:**
- "Record All" toggle in page header
- Auto-record option in user settings

## Technical Approach

### Capture
- Intercept WebSocket messages in `terminal.js`
- Buffer events with timestamps
- Periodic flush to backend (every 10s or 1000 events)
- Final flush on recording stop or disconnect

### Storage
- Backend endpoint: `POST /api/recordings/`
- Chunked upload for large recordings
- S3 storage with presigned URLs for playback

### Playback
- Frontend: Custom player using xterm.js
- Feed recorded events at playback speed
- Seek by binary search through timestamp array

## Files to Modify

- `portal/static/js/terminal.js` - Recording capture logic
- `portal/templates/mission_control/terminal.html` - Recording controls
- `portal/static/css/terminal.css` - Recording indicator, player styling
- New: `portal/static/js/terminal-player.js` - Playback component
- New: `portal/mission_control/models.py` - TerminalRecording model
- New: `portal/mission_control/api/recordings.py` - Upload/download endpoints

## Acceptance Criteria

- [ ] Recording toggle in terminal header
- [ ] Red indicator when recording active
- [ ] Recording captures output with timestamps
- [ ] Recordings stored in S3
- [ ] Playback UI with play/pause/seek
- [ ] Playback speed controls (0.5x - 4x)
- [ ] Export as asciicast and text
- [ ] Recordings listed in range history
- [ ] Auto-cleanup when range deleted

## Dependencies

- S3 bucket for recording storage
- API endpoints for upload/download

## Labels

`enhancement`, `terminal`, `recording`, `audit`
