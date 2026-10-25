"""Platform-owned acquisition recipes for backend-owned feature artifacts (ADR-034-R11).

A recipe is reviewed platform code that maps one known RAES feature source name
to an upstream location, an integrity check, and an extraction rule. Packs and
scenarios never supply recipes; they only declare a source name and version.
Unknown source names fail closed, and there is no generic URL fetch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# RAES ``Source.version`` default: the author left the version open.
OPEN_VERSION = "*"

# ASCII-only: \d must not admit non-ASCII Unicode digits into a version.
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[\dA-Za-z.-]+)?$", re.ASCII)


class RecipeError(ValueError):
    """A feature source cannot be acquired by any platform recipe."""


@dataclass(frozen=True)
class NpmBinaryRecipe:
    """Acquire one executable from a platform-specific npm package.

    ``platform_packages`` maps a Shifter guest platform key to the npm package
    that carries the binary for it. ``member`` is the exact tar member to
    extract. ``default_version`` is the deterministic choice for an open
    version (never "latest at fetch time"); it changes only through review.
    """

    source_name: str
    platform_packages: dict[str, str]
    member: str
    default_version: str
    payload_kind: str = "file"
    install_policy: str = "executable"

    @property
    def recipe_id(self) -> str:
        """Stable identifier recorded on every acquired artifact."""
        return f"npm-binary/{self.source_name}/v1"

    def package_for(self, platform: str) -> str:
        """Return the npm package carrying the binary for ``platform``."""
        try:
            return self.platform_packages[platform]
        except KeyError:
            raise RecipeError(
                f"feature source {self.source_name!r} is not available for platform {platform!r}"
            ) from None

    def resolve_version(self, version: str) -> str:
        """Apply RAES version semantics: exact is honored, open uses the default."""
        if version == OPEN_VERSION:
            return self.default_version
        if not _EXACT_VERSION.fullmatch(version):
            raise RecipeError(f"feature source {self.source_name!r} version {version!r} is not an exact version")
        return version


RECIPES: dict[str, NpmBinaryRecipe] = {
    recipe.source_name: recipe
    for recipe in (
        # Claude Code ships its CLI as a self-contained native executable in a
        # per-platform package; the top-level @anthropic-ai/claude-code package
        # is only a shim that links one of these in at install time (#2463).
        NpmBinaryRecipe(
            source_name="claude-code",
            platform_packages={"linux-x64-glibc": "@anthropic-ai/claude-code-linux-x64"},
            member="package/claude",
            default_version="2.1.289",
        ),
    )
}


def recipe_for(source_name: str) -> NpmBinaryRecipe:
    """Return the platform recipe for ``source_name`` or fail closed."""
    try:
        return RECIPES[source_name]
    except KeyError:
        raise RecipeError(f"no platform acquisition recipe for feature source {source_name!r}") from None
