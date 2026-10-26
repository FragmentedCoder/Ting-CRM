"""The colour choices people and Administrators pick from.

For the named colours only names travel and are stored; frontend/src/lib/colours.ts
holds the actual colours, each checked for contrast in light and dark mode, and a
frontend test checks it offers exactly these names. Administrators may also set
the site's colours to any colour (#RRGGBB); the browser then works out a light-
and a dark-mode shade of it that stay readable.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, StringConstraints

PrimaryColour = Literal["fjord", "pine", "teal", "plum", "rose", "slate"]
AccentColour = Literal["lyng", "copper", "moss", "sky", "rose", "violet"]
HexColour = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$"),
    AfterValidator(str.upper),
]
# The site's colours: a named one, or one an Administrator picked.
SitePrimary = PrimaryColour | HexColour
SiteAccent = AccentColour | HexColour

DEFAULT_PRIMARY: PrimaryColour = "fjord"
DEFAULT_ACCENT: AccentColour = "lyng"
