"""Terminal vendor asset static paths + SRI hashes.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Centralised so the terminal template
references symbolic names instead of inline literals (Sonar Web:S1829
hardens this surface).

These were previously loaded from public package CDNs. Per ADR-036 they are now
vendored under ``static/`` and served same-origin by WhiteNoise (the browser
security policy must not trust jsDelivr/unpkg as script authorities). ``url`` is
a ``STATICFILES_DIRS``-relative path resolved through ``{% static %}``;
``integrity`` is the SRI of the vendored bytes (WhiteNoise fingerprints the
filename, not the content, so SRI still matches). When bumping a pin, replace the
vendored file under ``static/`` and update ``integrity`` together.
"""

from __future__ import annotations

__all__ = ["TERMINAL_CDN_ASSETS"]

TERMINAL_CDN_ASSETS = {
    "xterm_css": {
        "url": "css/vendor/xterm.css",
        "integrity": "sha384-LJcOxlx9IMbNXDqJ2axpfEQKkAYbFjJfhXexLfiRJhjDU81mzgkiQq8rkV0j6dVh",
    },
    "xterm_js": {
        "url": "js/vendor/xterm.min.js",
        "integrity": "sha384-AVhes37YyPB7G0oxyTuYczBqf4EJQdhRVzG0+GGysdaQX7pfP1PbtJYAnOxwKjBt",
    },
    "xterm_addon_fit": {
        "url": "js/vendor/xterm-addon-fit.min.js",
        "integrity": "sha384-Vm0R4aF/Ma3ShGCifswMHTp0JxC92HZCHMdY9mUpDBJfjM6R0PzbgdTG7ezLXLGW",
    },
    "xterm_addon_web_links": {
        "url": "js/vendor/xterm-addon-web-links.min.js",
        "integrity": "sha384-t8w28+E7+af6B8A6OFhQmq//yvLkeu/O/gFLK0oXnlmhaHeAqXEymg5xhp3WekCL",
    },
    "split_js": {
        "url": "js/vendor/split.min.js",
        "integrity": "sha384-kqmTVGCmMolxaNUa2ke3QMADNEb2XKNJ/JbLmu/Ji7ZlUyQ6wzK8QkCTLZrfdU9g",
    },
}
