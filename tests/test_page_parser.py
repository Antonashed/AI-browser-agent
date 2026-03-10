from __future__ import annotations

import pytest

from agent.page_parser import Zone, extract_zone, parse_zones, zone_summary

# ---------------------------------------------------------------------------
# Realistic a11y tree fixtures
# ---------------------------------------------------------------------------

SNAPSHOT_WITH_LANDMARKS = """\
- banner "Gmail" [ref=e1]
  - link "Gmail logo" [ref=e2]
  - search "Search mail" [ref=e3]
    - textbox "Search" [ref=e4]
  - button "Profile" [ref=e5]
- navigation "Sidebar" [ref=e6]
  - link "Inbox (3)" [ref=e7]
  - link "Starred" [ref=e8]
  - link "Sent" [ref=e9]
  - link "Drafts" [ref=e10]
  - link "Spam" [ref=e11]
  - link "Trash" [ref=e12]
  - link "Categories" [ref=e13]
  - link "Social" [ref=e14]
  - link "Promotions" [ref=e15]
  - link "Updates" [ref=e16]
  - link "Forums" [ref=e17]
  - link "Labels" [ref=e18]
- main "Email list" [ref=e19]
  - checkbox "Select all" [ref=e20]
  - button "Refresh" [ref=e21]
  - listitem "Email 1 — John: Meeting tomorrow" [ref=e22]
  - listitem "Email 2 — Store: 50% off sale" [ref=e23]
  - listitem "Email 3 — Boss: Q1 review" [ref=e24]
- contentinfo [ref=e25]
  - text "Last activity: 2 minutes ago"
  - link "Details" [ref=e26]"""

SNAPSHOT_NO_LANDMARKS = """\
- document "My Page" [ref=e1]
  - heading "Welcome" [ref=e2]
  - paragraph "Hello world" [ref=e3]
  - button "Click me" [ref=e4]
  - link "About" [ref=e5]"""


class TestParseZones:
    def test_with_aria_landmarks(self) -> None:
        zones = parse_zones(SNAPSHOT_WITH_LANDMARKS)
        roles = [z.role for z in zones]
        assert "banner" in roles
        assert "navigation" in roles
        assert "main" in roles
        assert "contentinfo" in roles

    def test_zone_element_counts(self) -> None:
        zones = parse_zones(SNAPSHOT_WITH_LANDMARKS)
        by_role = {z.role: z for z in zones}
        # banner: link, search (with textbox child), button → 4 child "-" lines
        assert by_role["banner"].element_count >= 3
        # navigation: 12 links
        assert by_role["navigation"].element_count == 12
        # main: checkbox, button, 3 listitems = 5
        assert by_role["main"].element_count == 5

    def test_flat_fallback(self) -> None:
        """When no landmarks exist, all lines land in the 'page' zone."""
        zones = parse_zones(SNAPSHOT_NO_LANDMARKS)
        roles = [z.role for z in zones]
        assert "page" in roles
        # All nodes should be in the page zone
        page_zone = next(z for z in zones if z.role == "page")
        assert page_zone.element_count >= 4


class TestZoneSummary:
    def test_format(self) -> None:
        zones = parse_zones(SNAPSHOT_WITH_LANDMARKS)
        summary = zone_summary(zones)
        assert "Zones:" in summary
        assert "banner" in summary
        assert "main" in summary
        assert "Total:" in summary
        assert "elements" in summary

    def test_empty(self) -> None:
        assert "No zones" in zone_summary([])


class TestExtractZone:
    def test_extract_main(self) -> None:
        text = extract_zone(SNAPSHOT_WITH_LANDMARKS, "main")
        assert "Email list" in text
        assert "Email 1" in text
        # Should NOT include navigation
        assert "Inbox" not in text

    def test_extract_navigation(self) -> None:
        text = extract_zone(SNAPSHOT_WITH_LANDMARKS, "navigation")
        assert "Inbox" in text
        assert "Starred" in text

    def test_extract_all(self) -> None:
        text = extract_zone(SNAPSHOT_WITH_LANDMARKS, "all")
        assert text == SNAPSHOT_WITH_LANDMARKS

    def test_extract_missing_zone(self) -> None:
        text = extract_zone(SNAPSHOT_WITH_LANDMARKS, "nonexistent")
        assert "not found" in text.lower()
        assert "banner" in text  # lists available zones

    def test_extract_by_label(self) -> None:
        text = extract_zone(SNAPSHOT_WITH_LANDMARKS, "Sidebar")
        assert "Inbox" in text
