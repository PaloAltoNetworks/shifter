"""Neutral SDL-validation seam for RAES packs (ADR-031-R1).

The RAES SDL tooling (``raes``) may be imported only within ``shared.raes``.
Realization layers (for example ``cms`` content ingestion) must not import the
tooling directly; they call this seam to check whether an SDL start-state
document parses through RAES.

The seam returns a bounded, body-free signal: ``None`` when the document parses,
or the error *class* name when it does not. It never returns the raw RAES error
text, which may echo SDL fragments or input values.
"""

from __future__ import annotations

from pathlib import Path

from raes import SDLError, parse_sdl_file


def validate_sdl_document(path: Path) -> str | None:
    """Parse an RAES SDL document; return ``None`` if valid, else the error class.

    Args:
        path: Path to a ``*.sdl.yaml`` start-state document.

    Returns:
        ``None`` when the document parses through RAES, otherwise the exception
        class name (a bounded, non-sensitive label).
    """
    try:
        parse_sdl_file(path)
    except (SDLError, OSError, ValueError, TypeError) as exc:
        return type(exc).__name__
    return None
