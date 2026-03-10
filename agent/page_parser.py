"""Parse Playwright MCP accessibility tree into semantic zones.

Playwright ``browser_snapshot`` returns a text-based a11y tree where each node
is indented by two spaces per level.  Landmark roles (``banner``, ``navigation``,
``main``, ``contentinfo``, etc.) delimit semantic *zones* of the page.

This module provides helpers to:
* split a snapshot into zones,
* produce a compact overview (zone names + element counts),
* extract a single zone by name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ARIA landmark roles recognised as zone delimiters.
LANDMARK_ROLES: set[str] = {
    "banner",
    "navigation",
    "main",
    "contentinfo",
    "complementary",
    "search",
    "form",
    "region",
}

# Pattern: `- role "label" [ref=X]` or `- role [ref=X]` at any indent level.
_NODE_RE = re.compile(
    r"^(?P<indent>\s*)- (?P<role>\w+)(?:\s+\"(?P<label>[^\"]*)\")?\s*(?:\[ref=(?P<ref>\w+)\])?",
)


@dataclass
class Zone:
    """A contiguous block of the accessibility tree under one landmark role."""

    role: str
    label: str
    lines: list[str] = field(default_factory=list)

    @property
    def element_count(self) -> int:
        """Number of child nodes (lines starting with ``-``), excluding the zone header."""
        return sum(1 for ln in self.lines[1:] if ln.lstrip().startswith("-"))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _indent_level(line: str) -> int:
    """Return indentation depth (number of leading spaces)."""
    return len(line) - len(line.lstrip())


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_zones(snapshot: str) -> list[Zone]:
    """Split *snapshot* text into semantic :class:`Zone` objects.

    The function walks the tree top-down.  When a **top-level** node whose
    ``role`` is a landmark is found (i.e. not already inside another landmark
    zone), a new zone begins.  Nested landmarks (e.g. ``search`` inside
    ``banner``) are kept as children of their parent zone.

    Lines that precede the first landmark are collected into a synthetic
    ``"page"`` zone so nothing is lost.
    """
    lines = snapshot.split("\n")
    zones: list[Zone] = []
    current_zone: Zone | None = None
    zone_indent: int = -1

    for line in lines:
        if not line.strip():
            if current_zone is not None:
                current_zone.lines.append(line)
            continue

        m = _NODE_RE.match(line)
        indent = _indent_level(line)

        # Close the current zone when we return to the same or lesser indent.
        if current_zone is not None and indent <= zone_indent:
            current_zone = None
            zone_indent = -1

        # Start a new zone only for top-level landmarks (not nested).
        if m and m.group("role") in LANDMARK_ROLES and current_zone is None:
            current_zone = Zone(
                role=m.group("role"),
                label=m.group("label") or "",
            )
            current_zone.lines.append(line)
            zone_indent = indent
            zones.append(current_zone)
            continue

        # Lines inside a zone.
        if current_zone is not None:
            current_zone.lines.append(line)
            continue

        # Lines outside any landmark → collect into a "page" bucket.
        if not zones or zones[0].role != "page":
            zones.insert(0, Zone(role="page", label=""))
        zones[0].lines.append(line)

    return zones


def zone_summary(zones: list[Zone]) -> str:
    """Return a compact text overview of the zones.

    Example output::

        Zones:
        - banner: 3 elements
        - navigation: 12 elements
        - main: 45 elements
        - contentinfo: 2 elements
        Total: 62 elements
    """
    if not zones:
        return "No zones detected."

    parts = ["Zones:"]
    total = 0
    for z in zones:
        count = z.element_count
        total += count
        label_part = f' "{z.label}"' if z.label else ""
        parts.append(f"  - {z.role}{label_part}: {count} elements")
    parts.append(f"Total: {total} elements")
    return "\n".join(parts)


def extract_zone(snapshot: str, zone_name: str) -> str:
    """Return the text of the zone matching *zone_name*.

    *zone_name* is matched against both the ``role`` and (case-insensitively)
    the ``label`` of each zone.  ``"all"`` returns the full snapshot.
    If no matching zone is found an explanatory message is returned.
    """
    if zone_name == "all":
        return snapshot

    zones = parse_zones(snapshot)
    target = zone_name.lower()
    for z in zones:
        if z.role == target or z.label.lower() == target:
            return z.text

    available = ", ".join(z.role for z in zones)
    return f"Zone '{zone_name}' not found. Available zones: {available}"
