# Privacy Notice And Cookie Disclosure

The Shifter portal ships a neutral privacy notice shell and a dismissible
browser-storage disclosure. These are operator-facing mechanics only. They are
not legal advice, not a binding privacy policy, and not a GDPR compliance claim.

## What Shipped In OSS

- A dismissible notice on portal HTML pages explaining that strictly necessary
  browser storage is used for authentication, session behavior, and remembering
  notice dismissal.
- A public `/privacy/` route that renders placeholder content until the
  deployment operator replaces it.
- No analytics, advertising, tracking cookies, or non-essential consent flows.

## Operator Replacement Steps

1. Copy or edit `shifter/shifter_platform/templates/privacy/notice_content.html`
   in your deployment overlay, fork, or image build step.
2. Replace the placeholder with reviewed legal text for your deployment,
   including at minimum:
   - data controller identity and contact details
   - categories of personal data processed
   - retention periods
   - subprocessors or processors, if any
   - international transfers, if any
   - lawful bases, if applicable
   - data-subject rights mechanisms
3. Rebuild and redeploy the portal image or static bundle so the updated
   template is served at `/privacy/`.
4. Verify `/privacy/` is reachable without authentication and that the cookie
   notice links to it.

If you maintain environment-specific template directories, point Django's
template loader at your operator-owned template path instead of editing the
upstream file in place.

## Cookie Notice Behavior

- Dismissal is stored locally in the browser under the versioned key
  `shifter.cookieNotice.dismissed.v1`.
- The notice uses disclosure language and a **Dismiss** action. It is not a
  consent banner and does not manage non-essential cookie preferences.
- The notice does not call the server when dismissed.

## Out Of Scope

- `/terms/` or terms-of-service content
- Organization-specific legal commitments authored by the OSS project
- Analytics, advertising, or granular consent management

## Related Files

- `templates/partials/cookie_notice.html`
- `templates/privacy/notice.html`
- `templates/privacy/notice_content.html`
- `static/js/cookie-notice.js`
