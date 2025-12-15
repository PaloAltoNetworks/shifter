# Quickstart: Cortex XDR Portal Reskin

**Feature**: 183-cortex-xdr-reskin
**Date**: 2025-12-14

## Prerequisites

- Docker and Docker Compose installed
- Access to the portal codebase

## Running the Portal

From the `portal/` directory:

```bash
cd portal
make dev
```

This starts the Django development server with hot reload.

**Default URL**: http://localhost:8000

## Testing the Reskin

### Landing Page (P3)

1. Navigate to http://localhost:8000/
2. Verify:
   - Background is `#1f1f1f` (dark gray, not pure black)
   - Font is Lato (not Roboto)
   - Accent colors use Cortex blue `#128df3` (not neon green)
   - Shifter logo/wordmark is retained

### Mission Control (P1)

1. Log in (dev login at http://localhost:8000/dev-login/)
2. Navigate to http://localhost:8000/mission-control/
3. Verify on Dashboard:
   - Background: `#1f1f1f`
   - Cards: `#151515` background with `#484848` borders
   - Buttons: Pill-shaped (20px radius), white background, black text
   - Sidebar: Dark background with blue accent on active item
   - Typography: Lato font throughout

4. Check all pages:
   - `/mission-control/agents/`
   - `/mission-control/history/`
   - `/mission-control/settings/`
   - `/mission-control/help/`

5. Test interactive states:
   - Button hover (should lighten to `#f4f5f5`)
   - Sidebar item hover
   - Link hover (underline appears)
   - Form input focus (border color changes)

### Risk Register (P2)

1. Navigate to http://localhost:8000/risks/
2. Verify:
   - Styling matches Mission Control exactly
   - Table has horizontal-only borders
   - Severity badges are visible with clear hierarchy
   - Form inputs use bottom-border style

3. Check all pages:
   - `/risks/` (list)
   - `/risks/new/` (form)
   - `/risks/<id>/` (detail)
   - `/risks/apikeys/` (API keys)

## Visual Comparison

Open Cortex XDR in another browser tab for side-by-side comparison:
- https://077a95d2a-b8c1.xdr.ca.paloaltonetworks.com/

Reference CSS variables are in:
- `assets/styles/login.css`

## Browser Testing

Test in all target browsers:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

Minimum resolution: 1366×768

## Console Check

Open browser dev tools and verify:
- [ ] No CSS-related errors
- [ ] No missing font warnings
- [ ] No 404s for static assets

## Accessibility Check

Use browser dev tools to verify:
- [ ] Text contrast meets WCAG AA (4.5:1 minimum)
- [ ] Focus states are visible for keyboard navigation
- [ ] Interactive elements are properly sized (min 44×44px touch targets)
