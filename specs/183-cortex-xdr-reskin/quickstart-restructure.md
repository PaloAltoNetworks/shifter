# Quickstart: Cortex XDR Layout Restructure

## Prerequisites

- Docker and Docker Compose installed
- Portal running locally (`cd portal && make up`)
- Access to http://localhost:8000

## Quick Test

1. **Start the portal**:
   ```bash
   cd portal
   make up
   ```

2. **Log in via dev login**:
   - Navigate to http://localhost:8000/dev-login/
   - Click "Login as Dev User"

3. **Verify restructure**:

   | Component | What to Check |
   |-----------|---------------|
   | Icon Sidebar | Narrow icon strip on far left (~56px) |
   | Icons | Dashboard, Agents, History, Settings, Help visible |
   | Active State | Current section icon highlighted in blue |
   | Tooltips | Hover over icon shows section name |
   | Secondary Panel | Click icon → text panel slides out (if applicable) |
   | Background | Near-black (#000), not gray (#1f1f1f) |
   | Cards | Darker surface (#151515), visible contrast |
   | Empty States | Graphical circular element, not just text |
   | User Avatar | Initials circle at bottom of icon sidebar |

## Visual Comparison Checklist

Compare against Cortex XDR reference:

- [ ] Icon sidebar width matches Cortex (~48-60px)
- [ ] Secondary panel width matches Cortex (~180-200px)
- [ ] Background darkness matches Cortex (#000)
- [ ] Navigation icons are recognizable
- [ ] Active state uses Cortex blue (#128df3)
- [ ] Hover states work on all icons
- [ ] Panel slide animation is smooth
- [ ] User avatar positioned at bottom
- [ ] Empty state has circular graphic

## Page-by-Page Verification

### Mission Control

1. **Dashboard** (`/mission-control/`)
   - [ ] Icon sidebar visible
   - [ ] Dashboard icon active (highlighted)
   - [ ] Empty state shows graphic when no range active

2. **Agents** (`/mission-control/agents/`)
   - [ ] Agents icon active
   - [ ] Empty state shows graphic when no agents

3. **Settings** (`/mission-control/settings/`)
   - [ ] Settings icon active
   - [ ] Cards visible against dark background

### Risk Register

1. **All Risks** (`/risk-register/`)
   - [ ] Risk Register icon active
   - [ ] Secondary panel shows: All Risks, New Risk, API Keys
   - [ ] Empty state shows graphic when no risks

2. **API Keys** (`/risk-register/api-keys/`)
   - [ ] API Keys sub-item highlighted in secondary panel

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Icons not showing | Check SVG paths in template, verify static files collected |
| Panel not sliding | Check JavaScript console for errors, verify sidebar.js loaded |
| Colors wrong | Clear browser cache, verify CSS loaded |
| Layout broken | Check for CSS specificity conflicts with Phase 1 styles |

## File Locations

| Component | File |
|-----------|------|
| Icon sidebar CSS | `portal/static/css/xdr-sidebar.css` |
| Sidebar JavaScript | `portal/static/js/sidebar.js` |
| MC base template | `portal/templates/mission_control/base.html` |
| RR base template | `portal/templates/risk_register/base.html` |
| Theme variables | `portal/static/css/xdr-theme.css` |
