"""Mission 1 (Boreas OSINT) adapters — challenges 1-6.

Every path here is executed from the a14-kali container against the A0 Boreas
public website and the DNS sidecar. Logic is factored from
``tests/smoketests/A0-smoketest.sh``; each adapter produces the literal
``FLAG{...}`` a participant would recover and leaves the equality check to the
harness.
"""

from __future__ import annotations

import re

from . import AdapterContext, Produced, register

RUNNER = "a14-kali"
_FLAG_RE = re.compile(r"FLAG\{[A-Fa-f0-9]+\}")


def _first_flag(text: str) -> str | None:
    """Return the first ``FLAG{...}`` literal in ``text``, or None."""
    match = _FLAG_RE.search(text or "")
    return match.group(0) if match else None


def _curl(ctx: AdapterContext, url: str) -> str:
    """Fetch ``url`` from the runner container and return the response body."""
    result = ctx.runner.exec(RUNNER, ["curl", "-s", url])
    return result.stdout


@register(1, runner=RUNNER)
def challenge_1(ctx: AdapterContext) -> Produced:
    """Company Info — flag in an HTML comment on the About page."""
    body = _curl(ctx, f"http://{ctx.host('a0')}/about.html")
    return Produced(_first_flag(body), "flag", "about.html HTML comment")


@register(2, runner=RUNNER)
def challenge_2(ctx: AdapterContext) -> Produced:
    """Employee Directory — flag in org_chart.pdf metadata (Author field)."""
    pdf_path = "/tmp/sst-org_chart.pdf"
    ctx.runner.exec(
        RUNNER,
        ["curl", "-sf", f"http://{ctx.host('a0')}/internal/org_chart.pdf",
         "-o", pdf_path],
    )
    meta = ctx.runner.exec(RUNNER, ["exiftool", pdf_path])
    return Produced(_first_flag(meta.stdout), "flag", "org_chart.pdf metadata")


@register(3, runner=RUNNER)
def challenge_3(ctx: AdapterContext) -> Produced:
    """Tech Stack Revealed — flag in a hidden form field on the Careers page."""
    body = _curl(ctx, f"http://{ctx.host('a0')}/careers.html")
    return Produced(_first_flag(body), "flag", "careers.html hidden field")


@register(4, runner=RUNNER)
def challenge_4(ctx: AdapterContext) -> Produced:
    """Client Contracts — flag in an HTML comment on the archived client list."""
    body = _curl(ctx, f"http://{ctx.host('a0')}/old/clients.html")
    return Produced(_first_flag(body), "flag", "old/clients.html HTML comment")


@register(5, runner=RUNNER)
def challenge_5(ctx: AdapterContext) -> Produced:
    """DNS Reconnaissance — flag in a TXT record exposed by a zone transfer."""
    result = ctx.runner.exec(
        RUNNER,
        ["dig", "+short", "axfr", "boreas-systems.ctf", f"@{ctx.dns}"],
    )
    return Produced(_first_flag(result.stdout), "flag", "DNS AXFR TXT record")


@register(6, runner=RUNNER)
def challenge_6(ctx: AdapterContext) -> Produced:
    """Follow the Money — flag baked into the hidden annual report PDF.

    This is the Ottawa "Follow the Money" regression (#619): the PDF shipped
    without the canonical flag literal. The adapter fetches the unlisted
    report and extracts text the way the walkthrough instructs participants to.
    """
    pdf_path = "/tmp/sst-annual.pdf"
    ctx.runner.exec(
        RUNNER,
        ["curl", "-sf",
         f"http://{ctx.host('a0')}/internal/boreas-annual-2025.pdf",
         "-o", pdf_path],
    )
    text = ctx.runner.exec(RUNNER, ["pdftotext", pdf_path, "-"])
    return Produced(_first_flag(text.stdout), "flag", "annual report PDF text")
