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
        "integrity": "sha384-+A7/K289qOc/7hDFDYusvcPWHxUxFrMI8LgNO3ds+f9hkl+ZyqOuIhEhkqhRDYZc",
    },
    "xterm_addon_fit": {
        "url": "js/vendor/xterm-addon-fit.min.js",
        "integrity": "sha384-/SwRRNv5P4cWCaZpH2vEXjktzBE8Uu02oLlItKk03dQtYMNXIgQQDXfxNBAqUKtF",
    },
    "xterm_addon_web_links": {
        "url": "js/vendor/xterm-addon-web-links.min.js",
        "integrity": "sha384-rUWsPmYgoSft9fC92pMHSDRp0zJM8F4Bqu5vEtdJutFWrA0HQCjLS53x0DP3B5fF",
    },
    "split_js": {
        "url": "js/vendor/split.min.js",
        "integrity": "sha384-q2ksSc8z6Q4ZUnxlfZj9AXZLpSdWmD3q/YrId1twTeNHh56fNh98YbJSpppzGUvL",
    },
}
