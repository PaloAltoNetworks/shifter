---
id: UX-015
title: "Form accessibility"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:38:11.798649Z
updated_at: 2026-05-09T04:38:11.798649Z
---

# UX-015: Form accessibility

## Statement

Every form input shall have a programmatically associated label. Validation errors shall be associated with the relevant input via aria-describedby and announced. Multi-field forms shall surface a summary of errors at the top with anchor links to each affected field. Required fields shall be indicated through more than visual styling alone (for example text label, aria-required).

## Rationale

Forms are how participants and organizers do almost everything: register, manage events, configure scenarios, score submissions. Inaccessible forms make the platform unusable for assistive-technology users at the most basic interaction level.
