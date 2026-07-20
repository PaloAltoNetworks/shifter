"""Neutral SDL-validation seam for ACES packs (ADR-031-R1).

The ACES SDL tooling (``aces-sdl``) may be imported only within ``shared.aces``.
Realization layers (for example ``cms`` content ingestion) must not import the
tooling directly; they call this seam to check whether an SDL start-state
document parses through ACES.

The seam returns a bounded, body-free signal: ``None`` when the document parses,
or the error *class* name when it does not. It never returns the raw ACES error
text, which may echo SDL fragments or input values.
"""

from __future__ import annotations

from pathlib import Path

from aces_sdl import SDLError, parse_sdl_file


def validate_sdl_document(path: Path) -> str | None:
    """Parse an ACES SDL document; return ``None`` if valid, else the error class.

    Args:
        path: Path to a ``*.sdl.yaml`` start-state document.

    Returns:
        ``None`` when the document parses through ACES, otherwise the exception
        class name (a bounded, non-sensitive label).
    """
    try:
        parse_sdl_file(path)
    except (SDLError, OSError, ValueError, TypeError) as exc:
        return type(exc).__name__
    return None
