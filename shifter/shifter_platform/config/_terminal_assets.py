"""Terminal CDN asset URLs + SRI hashes.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Centralised so the terminal template
references symbolic names instead of inline absolute URIs (Sonar
Web:S1829 hardens this surface). When bumping a pin, update both
``url`` and ``integrity`` together.
"""

from __future__ import annotations

TERMINAL_CDN_ASSETS = {
    "xterm_css": {
        "url": "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css",
        "integrity": "sha384-LJcOxlx9IMbNXDqJ2axpfEQKkAYbFjJfhXexLfiRJhjDU81mzgkiQq8rkV0j6dVh",
    },
    "xterm_js": {
        "url": "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js",
        "integrity": "sha384-xjfWUeCWdMtvpAb/SmM6lMzS6pQGcQa0loOl1d97j6Odw0vjK9nW3+dTb/bn/mwH",
    },
    "xterm_addon_fit": {
        "url": "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js",
        "integrity": "sha384-dpjGwSSISUTz2taP54Bor7qkyMR20sSO9oe11UVYnGs2/YdUBf7HW30XKQx9PCzn",
    },
    "xterm_addon_web_links": {
        "url": "https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.min.js",
        "integrity": "sha384-iAAiqSZrWZz/YKZSTKOPNaRhVOg9JY14avg2EWEpYNnUsrnATA+Sg8pV7mak84/G",
    },
    "split_js": {
        "url": "https://unpkg.com/split.js@1.6.5/dist/split.min.js",
        "integrity": "",
    },
}
