#!/usr/bin/env python3
"""Generate the Modern Light SVG icon set and its auditable inventory.

The generated SVGs are build inputs. This script is a development helper only;
The native MSVC/Qt build does not execute Python.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
MONO_DIR = HERE / "mono"
COLOR_DIR = HERE / "color"
REPO = HERE.parents[2]
QRENDERDOC = REPO / "qrenderdoc"
ARTIFACTS = REPO / "artifacts" / "icon-modernization" / "v3"
GREEN = "#20A76B"
AMBER = "#A76B1D"
RED = "#B4473D"
BLUE = "#3C86B8"
LIGHT_BLUE = "#62A9D2"
CYAN = "#2FA9C5"
ORANGE = "#CF7628"
YELLOW = "#D0A12A"
PURPLE = "#7557B5"
MAGENTA = "#C04783"
NEUTRAL = "#66717D"
NEUTRAL_LIGHT = "#87929D"
GRID = "#B3BDC6"

LEGACY_COLOR_PALETTE = {
    "success_current_green": GREEN,
    "warning_amber": AMBER,
    "error_red": RED,
    "legacy_action_blue": BLUE,
    "legacy_light_blue": LIGHT_BLUE,
    "legacy_cyan": CYAN,
    "legacy_orange": ORANGE,
    "legacy_yellow": YELLOW,
    "legacy_purple": PURPLE,
    "legacy_magenta": MAGENTA,
    "neutral": NEUTRAL,
    "neutral_light": NEUTRAL_LIGHT,
    "chart_grid": GRID,
}
SOURCE_COLORS = tuple(LEGACY_COLOR_PALETTE.values())


def svg(body: str, root_stroke: str = "#000000") -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{root_stroke}" stroke-width="1.75" stroke-linecap="round" '
        'stroke-linejoin="round">\n'
        f"{body.strip()}\n"
        "</svg>\n"
    )


def monochrome(body: str) -> str:
    """Collapse fixed semantic accents into the canonical black tint mask."""
    for color in SOURCE_COLORS:
        body = body.replace(color, "#000000")
    return body


def document(extra: str = "") -> str:
    return f'''  <path d="M5 2.5h9l5 5v14H5z"/>
  <path d="M14 2.5v5h5"/>
{extra}'''


def control(reverse: bool, marker: str) -> str:
    """Rebuild the legacy transport grammar with sharp, non-overlapping marks.

    The marker always stays on the right in the legacy cursor/NaN/sample
    family, even for reverse traversal. Base/play are intentionally plain
    triangles. Start is the only left-bar + reverse-triangle combination.
    """
    if marker in {"base", "play"}:
        triangle = "M15 7v10l-7-5z" if reverse else "M9 7v10l7-5z"
    elif marker == "start":
        triangle = "M18 7v10l-7-5z"
    else:
        triangle = "M13 7.5v9l-6-4.5z" if reverse else "M7 7.5v9l6-4.5z"

    detail = ""
    if marker == "start":
        detail = f'<rect x="6" y="7" width="2" height="10" fill="{BLUE}" stroke="none"/>'
    elif marker == "cursor":
        detail = f'<path d="M16 7h4v2h-1v6h1v2h-4v-2h1V9h-1z" fill="{BLUE}" stroke="none"/>'
    elif marker == "end":
        detail = f'<rect x="17" y="7" width="2" height="10" fill="{BLUE}" stroke="none"/>'
    elif marker == "nan":
        detail = (
            f'<path d="M15 8l-1 8M19 8l-1 8M13 11h7M13 14h7" '
            f'stroke="{NEUTRAL}" stroke-width="1.5"/>'
        )
    elif marker == "sample":
        detail = (
            f'<rect x="15" y="8" width="2" height="2" fill="{RED}" stroke="none"/>'
            f'<rect x="17" y="10" width="2" height="2" fill="{RED}" stroke="none"/>'
            f'<rect x="15" y="12" width="2" height="2" fill="{RED}" stroke="none"/>'
            f'<rect x="17" y="14" width="2" height="2" fill="{RED}" stroke="none"/>'
        )

    return (
        f'  <circle cx="12" cy="12" r="9" stroke="{BLUE}" stroke-width="1.5"/>\n'
        f'  <path d="{triangle}" fill="{LIGHT_BLUE}" stroke="{BLUE}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        f'  {detail}'
    )


ICONS: dict[str, str] = {
    "action": '''  <path d="M3 8h9V4l8 8-8 8v-4H3z"/>''',
    "action_hover": f'''  <path d="M3 8h9V4l8 8-8 8v-4H3z" stroke="{GREEN}"/>''',
    "add": f'''  <circle cx="12" cy="12" r="8.5" stroke="{GREEN}"/>
  <path d="M12 7.5v9M7.5 12h9" stroke="{GREEN}"/>''',
    "align": f'''  <path d="M4 3v18" stroke="{NEUTRAL}"/>
  <rect x="7" y="4" width="7" height="4" rx="1" stroke="{NEUTRAL_LIGHT}"/>
  <rect x="7" y="10" width="13" height="4" rx="1" stroke="{ORANGE}"/>
  <path d="M13 18H7m0 0 3-3m-3 3 3 3" stroke="{BLUE}"/>''',
    "arrow_in": f'''  <path d="M3 3l6 6M9 5v4H5M21 3l-6 6m0-4v4h4M3 21l6-6m0 4v-4H5M21 21l-6-6m0 4v-4h4" stroke="{GREEN}" stroke-width="2"/>''',
    "arrow_join": '''  <path d="M6 21v-4c0-3 2-5 6-5s6 2 6 5v4M12 12V4M8 8l4-4 4 4"/>''',
    "arrow_left": '''  <path d="M20.5 8.5H10V4l-7.5 8 7.5 8v-4.5h10.5z"/>''',
    "arrow_out": f'''  <path d="M9 9 3 3m0 4V3h4M15 9l6-6m-4 0h4v4M9 15l-6 6m0-4v4h4M15 15l6 6m-4 0h4v-4" stroke="{GREEN}" stroke-width="2"/>''',
    "arrow_refresh": f'''  <path d="M3 10.5C5 4.5 10.5 2.5 16 4.5l-1.5 3C10.5 6 7.5 7.5 6 11.5z" fill="{GREEN}" stroke="none"/>
  <path d="m14 2 7 4.5-7 4.5z" fill="{GREEN}" stroke="none"/>
  <path d="M21 13.5c-2 6-7.5 8-13 6l1.5-3c4 1.5 7 .0 8.5-4z" fill="{GREEN}" stroke="none"/>
  <path d="m10 13-7 4.5 7 4.5z" fill="{GREEN}" stroke="none"/>''',
    "arrow_right": '''  <path d="M3.5 8.5H14V4l7.5 8-7.5 8v-4.5H3.5z"/>''',
    "arrow_undo": f'''  <path d="M3 3h10c5.5 0 8 3.5 8 8s-2.5 8-8 8H8v3l-6-5 6-5v3h5c2.5 0 4-1.5 4-4s-1.5-4-4-4H3z" fill="{GREEN}" stroke="none"/>''',
    "asterisk_orange": f'''  <path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4" stroke="{ORANGE}"/>''',
    "bookmark_blue": '''  <path d="M7 3h10v18l-5-3.5L7 21z"/>''',
    "bug": f'''  <rect x="7" y="5.5" width="10" height="14" rx="5" stroke="{ORANGE}"/>
  <path d="M9 5.5V4a3 3 0 0 1 6 0v1.5M7 10H3m4 4H3m4 4-3 2m13-10h4m-4 4h4m-4 4 3 2M12 6v13.5" stroke="{NEUTRAL}"/>''',
    "chart_curve": f'''  <rect x="3" y="3" width="18" height="18" stroke="{NEUTRAL}"/>
  <path d="M9 3v18M15 3v18M3 9h18M3 15h18" stroke="{GRID}" stroke-width="1.5"/>
  <path d="M5 18c2-7 3-12 6-12s4 9 8 11" stroke="{RED}" stroke-width="1.5"/>
  <path d="M5 9c3-3 5-1 7 3s4 5 7-2" stroke="{GREEN}" stroke-width="1.5"/>
  <path d="M5 5c4 1 5 10 8 12s4-2 6-7" stroke="{BLUE}" stroke-width="1.5"/>''',
    "checkerboard": f'''  <rect x="3" y="3" width="18" height="18" stroke="{ORANGE}"/>
  <path d="M3 3h4.5v4.5H3zM12 3h4.5v4.5H12zM7.5 7.5H12V12H7.5zM16.5 7.5H21V12h-4.5zM3 12h4.5v4.5H3zM12 12h4.5v4.5H12zM7.5 16.5H12V21H7.5zM16.5 16.5H21V21h-4.5z" fill="#000000" stroke="none"/>''',
    "cog": '''  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06-2.12 2.12-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V20h-3v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06-2.12-2.12.06-.06A1.65 1.65 0 0 0 7.2 15a1.65 1.65 0 0 0-1.51-1H5.6v-3h.09A1.65 1.65 0 0 0 7.2 10a1.65 1.65 0 0 0-.33-1.82l-.06-.06L8.93 6l.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V4.8h3v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06 2.12 2.12-.06.06A1.65 1.65 0 0 0 19.4 10a1.65 1.65 0 0 0 1.51 1H21v3h-.09a1.65 1.65 0 0 0-1.51 1z"/>''',
    "color_wheel": f'''  <path d="M12 12 12 3A9 9 0 0 1 19.8 7.5Z" fill="{YELLOW}" stroke="none"/>
  <path d="M12 12 19.8 7.5A9 9 0 0 1 19.8 16.5Z" fill="{ORANGE}" stroke="none"/>
  <path d="M12 12 19.8 16.5A9 9 0 0 1 12 21Z" fill="{MAGENTA}" stroke="none"/>
  <path d="M12 12 12 21A9 9 0 0 1 4.2 16.5Z" fill="{PURPLE}" stroke="none"/>
  <path d="M12 12 4.2 16.5A9 9 0 0 1 4.2 7.5Z" fill="{BLUE}" stroke="none"/>
  <path d="M12 12 4.2 7.5A9 9 0 0 1 12 3Z" fill="{GREEN}" stroke="none"/>
  <circle cx="12" cy="12" r="9" stroke="{NEUTRAL}"/>
  <path d="M12 12V3M12 12l7.8-4.5M12 12l7.8 4.5M12 12v9M12 12l-7.8 4.5M12 12 4.2 7.5" stroke="{NEUTRAL}" stroke-width="1.5"/>''',
    "connect": f'''  <g transform="rotate(-45 12 12)" stroke="{BLUE}">
    <path d="M2.5 12h3.5"/>
    <path d="M6 9.5v5M8 9v6"/>
    <rect x="8" y="7.5" width="7.25" height="9" rx="2"/>
    <path d="M15.25 10h5.25M15.25 14h5.25" stroke="{GREEN}"/>
  </g>''',
    "control_base_blue": control(False, "base"),
    "control_cursor_blue": control(False, "cursor"),
    "control_end_blue": control(False, "end"),
    "control_nan_blue": control(False, "nan"),
    "control_play_blue": control(False, "play"),
    "control_reverse_base_blue": control(True, "base"),
    "control_reverse_blue": control(True, "play"),
    "control_reverse_cursor_blue": control(True, "cursor"),
    "control_reverse_nan_blue": control(True, "nan"),
    "control_reverse_sample_blue": control(True, "sample"),
    "control_sample_blue": control(False, "sample"),
    "control_start_blue": control(True, "start"),
    "copy": '''  <rect x="8" y="7" width="11" height="14" rx="1.5"/>
  <path d="M16 7V4.5A1.5 1.5 0 0 0 14.5 3h-9A1.5 1.5 0 0 0 4 4.5v12A1.5 1.5 0 0 0 5.5 18H8"/>''',
    "cross": f'''  <path d="M5 5l14 14M19 5 5 19" stroke="{RED}"/>''',
    "cut": f'''  <circle cx="6" cy="18" r="3" stroke="{BLUE}"/>
  <circle cx="18" cy="18" r="3" stroke="{BLUE}"/>
  <path d="M8.5 16.3 18 4M15.5 16.3 6 4" stroke="{NEUTRAL}"/>''',
    "del": f'''  <circle cx="12" cy="12" r="8.5" stroke="{RED}"/>
  <path d="M7.5 12h9" stroke="{RED}"/>''',
    "disconnect": f'''  <g transform="rotate(-45 12 12)" stroke="{BLUE}">
    <path d="M2.5 12h3.5"/>
    <path d="M6 9.5v5M8 9v6"/>
    <rect x="8" y="7.5" width="7.25" height="9" rx="2"/>
    <path d="M15.25 10h2.25M15.25 14h2.25" stroke="{RED}"/>
  </g>
  <path d="m18 2.75 4 4M22 2.75l-4 4" stroke="{RED}"/>''',
    "draw_vertex": f'''  <path d="M7 17 12 7l5 10" stroke="{BLUE}"/>
  <circle cx="6" cy="18" r="2" stroke="{NEUTRAL}"/>
  <circle cx="12" cy="5" r="2" stroke="{NEUTRAL}"/>
  <circle cx="18" cy="18" r="2" stroke="{NEUTRAL}"/>''',
    "filter": f'''  <path d="M3 4h18l-7 8v6l-4 2v-8z" stroke="{BLUE}"/>''',
    "filter_reapply": f'''  <path d="M3 4h13l-5 6v5l-3 1.5V10z" stroke="{BLUE}"/>
  <path d="M15 10a4.5 4.5 0 0 1 5 1l1-1v4h-4l1.4-1.4M20 17a4.5 4.5 0 0 1-5-1l-1 1v-4h4l-1.4 1.4" stroke="{GREEN}"/>''',
    "find": '''  <path d="M8 5v4m8-4v4M6 9l-2 8a3 3 0 0 0 5.7 1L12 12l2.3 6a3 3 0 0 0 5.7-1l-2-8zM9 9h6"/>
  <circle cx="7" cy="16" r="2.5"/><circle cx="17" cy="16" r="2.5"/>''',
    "flag_green": f'''  <path d="M6 21V3" stroke="{ORANGE}"/>
  <path d="M6 4h11l-2 4 2 4H6" stroke="{GREEN}"/>''',
    "flip_y": f'''  <path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4" stroke="{GREEN}"/>''',
    "folder": '''  <path d="M3 6h7l2 2h9v11H3z"/>''',
    "folder_page_white": f'''  <path d="M3 6h7l2 2h9v6" stroke="{YELLOW}"/>
  <path d="M3 6v13h8" stroke="{ORANGE}"/>
  <path d="M12 11h5l4 4v6h-9zM17 11v4h4" stroke="{LIGHT_BLUE}"/>''',
    "help": '''  <circle cx="12" cy="12" r="9"/>
  <path d="M9.5 9a2.6 2.6 0 1 1 4.1 2.1c-1 .7-1.6 1.2-1.6 2.4M12 17h.01"/>''',
    "hourglass": f'''  <path d="M6 3h12M6 21h12M7 3c0 5 2 6 5 9-3 3-5 4-5 9M17 3c0 5-2 6-5 9 3 3 5 4 5 9" stroke="{ORANGE}"/>
  <path d="M9 7h6l-3 4zM9 18h6l-3-4z" fill="{LIGHT_BLUE}" stroke="none"/>''',
    "house": f'''  <path d="M3 11 12 3l9 8" stroke="{ORANGE}"/>
  <path d="M5 10v11h14V10" stroke="{NEUTRAL}"/>
  <path d="M9 21v-7h6v7" stroke="{ORANGE}"/>
  <rect x="7" y="11" width="3" height="3" rx="0.5" stroke="{BLUE}"/>''',
    "information": '''  <circle cx="12" cy="12" r="9"/>
  <path d="M12 11v6M12 7h.01"/>''',
    "link": '''  <path d="M9.5 14.5 8 16a3.5 3.5 0 1 1-5-5l3-3a3.5 3.5 0 0 1 5 0M14.5 9.5 16 8a3.5 3.5 0 1 1 5 5l-3 3a3.5 3.5 0 0 1-5 0M8.5 15.5l7-7"/>''',
    "page_go": document(f'''  <path d="M10 16h9m0 0-3-3m3 3-3 3" stroke="{GREEN}"/>'''),
    "page_white_code": document(f'''  <path d="M10 13 7 16l3 3M14 13l3 3-3 3" stroke="{BLUE}"/>'''),
    "page_white_database": document(f'''  <ellipse cx="13" cy="14" rx="4.5" ry="2" stroke="{LIGHT_BLUE}"/>
  <path d="M8.5 14v4c0 1.1 2 2 4.5 2s4.5-.9 4.5-2v-4" stroke="{LIGHT_BLUE}"/>'''),
    "page_white_delete": document(f'''  <circle cx="15.5" cy="16.5" r="3.5" stroke="{RED}"/>
  <path d="M13.5 16.5h4" stroke="{RED}"/>'''),
    "page_white_edit": document(f'''  <path d="m9 19 1-4 6-6 3 3-6 6zM16 9l3 3" stroke="{AMBER}"/>'''),
    "page_white_link": document('''  <path d="M9.5 18.5 8 20a2.5 2.5 0 0 1-3.5-3.5L6 15a2.5 2.5 0 0 1 3.5 0M14.5 13.5 16 12a2.5 2.5 0 0 1 3.5 3.5L18 17a2.5 2.5 0 0 1-3.5 0M9 18l6-6"/>'''),
    "page_white_stack": '''  <path d="M9 3h7l4 4v12H9zM16 3v4h4"/>
  <path d="M6 6H4v12h2M6.5 9H6v12h10v-2"/>''',
    "paste": f'''  <path d="M8 5H5v16h14V5h-3" stroke="{ORANGE}"/>
  <rect x="8" y="3" width="8" height="4" rx="1" stroke="{NEUTRAL}"/>
  <path d="M10 11h6M10 15h6" stroke="{BLUE}"/>''',
    "pixel_history": f'''  <path d="M5 9H2l3-3 3 3H5a7 7 0 1 1 1 7" stroke="{GREEN}"/>
  <path d="M12 8v4l3 2"/>''',
    "plugin": f'''  <path d="M9 3h4v3a2 2 0 1 0 4 0V3h4v6h-3a2 2 0 1 0 0 4h3v8h-8v-3a2 2 0 1 0-4 0v3H3v-8h3a2 2 0 1 0 0-4H3V3h6z" stroke="{AMBER}"/>''',
    "plugin_add": f'''  <path d="M8 3h4v3a2 2 0 1 0 4 0V3h4v6h-3a2 2 0 0 0 0 4h1" stroke="{AMBER}"/>
  <path d="M10 21H3v-8h3a2 2 0 1 0 0-4H3V3h5" stroke="{AMBER}"/>
  <circle cx="17" cy="17" r="4" stroke="{GREEN}"/><path d="M17 15v4M15 17h4" stroke="{GREEN}"/>''',
    "save": '''  <path d="M4 3h14l2 2v16H4z"/>
  <path d="M7 3v6h9V3M8 21v-7h8v7"/>''',
    "text_add": document(f'''  <path d="M9 11h6M9 14h4"/>
  <circle cx="17" cy="18" r="3.5" stroke="{GREEN}"/><path d="M17 16v4M15 18h4" stroke="{GREEN}"/>'''),
    "tick": f'''  <path d="m4 12 5 5L20 6" stroke="{GREEN}"/>''',
    "time": f'''  <circle cx="12" cy="12" r="9" stroke="{BLUE}"/>
  <path d="M12 7v5l3 2" stroke="{YELLOW}"/>''',
    "timeline_marker": f'''  <path d="M4 9v10M8 7v12M12 10v9M16 8v11M20 6v13" stroke="{NEUTRAL_LIGHT}"/>
  <path d="m9 3 3 4 3-4z" stroke="{BLUE}"/>''',
    "update": f'''  <path d="M10 22C4.5 21.5 1.5 17.5 1.5 12S4.5 2.5 10 2l.5 4C7 6.5 5.5 8.5 5.5 12s1.5 5.5 5 6z" fill="{BLUE}" stroke="none"/>
  <path d="m6.5 3 6.5 1-3 6z" fill="{BLUE}" stroke="none"/>
  <path d="M14 2c5.5.5 8.5 4.5 8.5 10S19.5 21.5 14 22l-.5-4c3.5-.5 5-2.5 5-6s-1.5-5.5-5-6z" fill="{LIGHT_BLUE}" stroke="none"/>
  <path d="m17.5 21-6.5-1 3-6z" fill="{LIGHT_BLUE}" stroke="none"/>''',
    "upfolder": f'''  <path d="M3 7h7l2 2h9v10H3z" stroke="{YELLOW}"/>
  <path d="M12 16V4M8 8l4-4 4 4" stroke="{GREEN}"/>''',
    "wand": f'''  <path d="m3.25 18.75 2 2L17.5 8.5l-2-2z" fill="{NEUTRAL}" stroke="none"/>
  <path d="m2 19 3 3 2-2-3-3z" fill="{BLUE}" stroke="none"/>
  <path d="m3.25 19 1.75 1.75.75-.75L4 18.25z" fill="{LIGHT_BLUE}" stroke="none"/>
  <path d="M18 .5 18.6 4.5 22 2 19.5 5.4 23.5 6 19.5 6.6 22 10 18.6 7.5 18 11.5 17.4 7.5 14 10 16.5 6.6 12.5 6 16.5 5.4 14 2 17.4 4.5z" fill="{ORANGE}" stroke="none"/>''',
    "wireframe_mesh": '''  <path d="m12 2.5 8 4.5v10l-8 4.5L4 17V7zM4 7l8 5 8-5M12 12v9.5M4 17l8-5 8 5M4 7l8 14.5M20 7l-8 14.5"/>''',
    "wrench": '''  <path d="M14 5a5 5 0 0 0-6 6L3 16a3 3 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-3-3z"/>''',
    "zoom": f'''  <circle cx="10.5" cy="10.5" r="6.5" stroke="{LIGHT_BLUE}"/>
  <path d="m15.5 15.5 5 5" stroke="{ORANGE}"/>''',
}


COLOR_PRIMARY = {
    "action": NEUTRAL_LIGHT,
    "action_hover": GREEN,
    "add": GREEN,
    "arrow_in": GREEN,
    "arrow_join": GREEN,
    "arrow_left": GREEN,
    "arrow_out": GREEN,
    "arrow_refresh": GREEN,
    "arrow_right": GREEN,
    "arrow_undo": GREEN,
    "bookmark_blue": BLUE,
    "cog": NEUTRAL_LIGHT,
    "copy": BLUE,
    "cross": RED,
    "del": RED,
    "find": NEUTRAL_LIGHT,
    "flip_y": GREEN,
    "folder": YELLOW,
    "help": BLUE,
    "information": BLUE,
    "link": NEUTRAL_LIGHT,
    "page_go": BLUE,
    "page_white_code": NEUTRAL_LIGHT,
    "page_white_database": NEUTRAL_LIGHT,
    "page_white_delete": NEUTRAL_LIGHT,
    "page_white_edit": NEUTRAL_LIGHT,
    "page_white_link": NEUTRAL_LIGHT,
    "page_white_stack": NEUTRAL_LIGHT,
    "plugin": ORANGE,
    "plugin_add": ORANGE,
    "save": BLUE,
    "text_add": BLUE,
    "tick": GREEN,
    "update": BLUE,
    "wireframe_mesh": NEUTRAL,
    "wrench": BLUE,
}
COLOR_PRIMARY.update({name: BLUE for name in ICONS if name.startswith("control_")})


MONO_OVERRIDES = {
    "color_wheel": '''  <circle cx="12" cy="12" r="9"/>
  <path d="M12 12V3M12 12l7.8-4.5M12 12l7.8 4.5M12 12v9M12 12l-7.8 4.5M12 12 4.2 7.5"/>''',
}


CATEGORIES = {
    "navigation": {"action", "action_hover", "arrow_in", "arrow_join", "arrow_left", "arrow_out", "arrow_refresh", "arrow_right", "arrow_undo", "update", "upfolder"},
    "playback": {name for name in ICONS if name.startswith("control_")},
    "files": {"copy", "cut", "folder", "folder_page_white", "page_go", "page_white_code", "page_white_database", "page_white_delete", "page_white_edit", "page_white_link", "page_white_stack", "paste", "save", "text_add"},
    "status": {"add", "asterisk_orange", "cross", "del", "flag_green", "help", "information", "plugin_add", "tick"},
    "view": {"align", "chart_curve", "checkerboard", "color_wheel", "draw_vertex", "filter", "filter_reapply", "find", "flip_y", "pixel_history", "time", "timeline_marker", "wireframe_mesh", "zoom"},
    "tools": {"bookmark_blue", "bug", "cog", "connect", "disconnect", "hourglass", "house", "link", "plugin", "wand", "wrench"},
}


SEMANTICS = {
    "action": "Execute or open the selected action",
    "action_hover": "Hovered execute/open action state",
    "add": "Add a new item",
    "align": "Align data or columns",
    "arrow_in": "Collapse or move four directions inward",
    "arrow_join": "Join branches into the forward path",
    "arrow_left": "Move to the previous item",
    "arrow_out": "Expand or move four directions outward",
    "arrow_refresh": "Refresh the current view",
    "arrow_right": "Move to the next item",
    "arrow_undo": "Undo the most recent operation",
    "asterisk_orange": "Attention or modified marker",
    "bookmark_blue": "Bookmark the current item",
    "bug": "Debug a shader or event",
    "chart_curve": "Open the curve or chart view",
    "checkerboard": "Toggle transparency checkerboard",
    "cog": "Open settings",
    "color_wheel": "Choose or inspect a color",
    "connect": "Connect to a target",
    "copy": "Copy the selected data",
    "cross": "Close or cancel",
    "cut": "Cut the selected data",
    "del": "Delete or remove an item",
    "disconnect": "Disconnect from a target",
    "draw_vertex": "Display or highlight mesh vertices",
    "filter": "Filter the current data set",
    "filter_reapply": "Reapply the active filter",
    "find": "Find a resource or event",
    "flag_green": "Mark the current event",
    "flip_y": "Flip the image vertically",
    "folder": "Open a folder",
    "folder_page_white": "Open a file from a folder",
    "help": "Open contextual help",
    "hourglass": "Operation is waiting or in progress",
    "house": "Return to the home/default location",
    "information": "Show information",
    "link": "Create or follow a link",
    "page_go": "Open or export a document",
    "page_white_code": "Open source code",
    "page_white_database": "Open structured or database data",
    "page_white_delete": "Remove a document",
    "page_white_edit": "Edit a document",
    "page_white_link": "Link a document",
    "page_white_stack": "View a stack of documents",
    "paste": "Paste clipboard data",
    "pixel_history": "Open pixel history",
    "plugin": "Manage a plugin",
    "plugin_add": "Add a plugin",
    "save": "Save the current data",
    "text_add": "Create a text or document item",
    "tick": "Confirm or indicate success",
    "time": "Show timing information",
    "timeline_marker": "Mark a position on the timeline",
    "update": "Update or reload data",
    "upfolder": "Move to the parent folder",
    "wand": "Run an automatic helper operation",
    "wireframe_mesh": "Toggle wireframe mesh display",
    "wrench": "Open tools or configuration",
    "zoom": "Zoom or inspect closely",
}


CONTROL_SEMANTICS = {
    "control_base_blue": "Move to the base or first event",
    "control_cursor_blue": "Move to the cursor event",
    "control_end_blue": "Move to the end event",
    "control_nan_blue": "Move to the NaN-special event",
    "control_play_blue": "Play forward",
    "control_reverse_base_blue": "Move backward to the base event",
    "control_reverse_blue": "Play backward",
    "control_reverse_cursor_blue": "Move backward to the cursor event",
    "control_reverse_nan_blue": "Move backward to the NaN-special event",
    "control_reverse_sample_blue": "Move backward to the sample event",
    "control_sample_blue": "Move forward to the sample event",
    "control_start_blue": "Move to the start event",
}
SEMANTICS.update(CONTROL_SEMANTICS)


SEMANTIC_COLORS = {
    "action_hover": "success_current",
    "add": "success_current",
    "asterisk_orange": "warning",
    "cross": "error",
    "del": "error",
    "connect": "success_current",
    "disconnect": "error",
    "filter_reapply": "success_current",
    "flag_green": "success_current",
    "flip_y": "success_current",
    "page_go": "success_current",
    "page_white_delete": "error",
    "page_white_edit": "warning",
    "pixel_history": "success_current",
    "plugin": "warning",
    "plugin_add": "success_current",
    "text_add": "success_current",
    "tick": "success_current",
    "upfolder": "success_current",
    "wand": "warning",
}


DIRECTIONAL = {
    "action", "action_hover", "align", "arrow_in", "arrow_join", "arrow_left", "arrow_out",
    "arrow_refresh", "arrow_right", "arrow_undo", "filter_reapply", "flag_green", "flip_y",
    "page_go", "pixel_history", "update", "upfolder",
    *{name for name in ICONS if name.startswith("control_")},
}


SYMMETRY = {
    "add": "radial",
    "asterisk_orange": "radial",
    "checkerboard": "radial",
    "color_wheel": "radial",
    "cross": "radial",
    "del": "radial",
    "information": "vertical",
}


NOTES = {
    "action_hover": "State variant of action; preserve rightward direction",
    "arrow_in": "Four diagonal arrows terminate at the centre-facing corners; never reuse arrow_out geometry",
    "arrow_out": "Four diagonal arrows terminate at the outer corners; never reuse arrow_in geometry",
    "arrow_refresh": "Two separated horizontal curved arrows; solid 3 px bands keep the legacy refresh silhouette legible at 16 px",
    "arrow_undo": "Solid leftward U-turn silhouette; never substitute a circular refresh arrow",
    "control_base_blue": "Legacy-equivalent plain forward triangle; intentionally matches control_play_blue",
    "control_play_blue": "Legacy-equivalent plain forward triangle; intentionally matches control_base_blue",
    "control_reverse_base_blue": "Legacy-equivalent plain reverse triangle; intentionally matches control_reverse_blue",
    "control_reverse_blue": "Legacy-equivalent plain reverse triangle; intentionally matches control_reverse_base_blue",
    "control_cursor_blue": "Forward triangle plus a right-side I-beam with a two-unit separation zone",
    "control_nan_blue": "Hash marker distinguishes NaN navigation from sample navigation",
    "control_start_blue": "Left stop bar plus a left-facing triangle, matching the legacy start control",
    "control_reverse_cursor_blue": "Left-facing triangle plus the legacy right-side I-beam marker",
    "control_reverse_nan_blue": "Left-facing reverse control with hash marker",
    "control_reverse_sample_blue": "Left-facing reverse control with checker sample marker",
    "control_sample_blue": "Right-facing forward control with checker sample marker",
    "connect": "Single cable and plug body with separated twin pins; no mirrored second body that can read as a dumbbell",
    "disconnect": "Same two-prong plug family as connect, plus a visible X so the state remains distinct without color",
    "page_white_code": "Angle brackets are paths, not text glyphs",
    "update": "Two vertically split blue circulating arrows; intentionally distinct from the horizontal green refresh pair",
    "wand": "Long neutral shaft with a solid orange tip burst; no short pencil-like body",
}


INTENTIONAL_BODY_EQUIVALENCES = {
    frozenset({"control_base_blue", "control_play_blue"}),
    frozenset({"control_reverse_base_blue", "control_reverse_blue"}),
}

DISTINCT_SEMANTIC_PAIRS = {
    frozenset({"arrow_in", "arrow_out"}),
    frozenset({"arrow_refresh", "arrow_undo"}),
    frozenset({"arrow_refresh", "update"}),
    frozenset({"arrow_undo", "update"}),
    frozenset({"control_base_blue", "control_start_blue"}),
    frozenset({"control_end_blue", "control_start_blue"}),
    frozenset({"control_cursor_blue", "control_reverse_cursor_blue"}),
    frozenset({"control_nan_blue", "control_reverse_nan_blue"}),
    frozenset({"control_sample_blue", "control_reverse_sample_blue"}),
}


def canonical_body(body: str) -> str:
    """Remove palette and formatting differences for geometry collision checks."""
    for color in SOURCE_COLORS:
        body = body.replace(color, "#COLOR")
    return "".join(body.split())


def validate_semantic_distinctness() -> None:
    groups: dict[str, list[str]] = {}
    for name, body in ICONS.items():
        groups.setdefault(canonical_body(body), []).append(name)

    duplicate_groups = {
        frozenset(names) for names in groups.values() if len(names) > 1
    }
    unexpected = duplicate_groups - INTENTIONAL_BODY_EQUIVALENCES
    missing = INTENTIONAL_BODY_EQUIVALENCES - duplicate_groups
    if unexpected:
        raise SystemExit(f"Unexpected semantic geometry collisions: {sorted(map(sorted, unexpected))}")
    if missing:
        raise SystemExit(f"Legacy-equivalent control pairs drifted apart: {sorted(map(sorted, missing))}")

    for pair in DISTINCT_SEMANTIC_PAIRS:
        left, right = sorted(pair)
        if canonical_body(ICONS[left]) == canonical_body(ICONS[right]):
            raise SystemExit(f"Distinct icon semantics collapsed into one geometry: {left}, {right}")


def category_for(name: str) -> str:
    for category, names in CATEGORIES.items():
        if name in names:
            return category
    return "misc"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_code_reference_index(names: list[str]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {name: [] for name in names}
    needles = {
        name: (f"Icons::{name}", f"Pixmaps::{name}", f'"{name}.png"', f":/{name}.png")
        for name in names
    }
    search_paths: list[Path] = []
    for directory in ("Code", "Styles", "Widgets", "Windows"):
        search_paths.extend((QRENDERDOC / directory).rglob("*"))
    search_paths.extend(QRENDERDOC.glob("*"))
    search_paths.append(QRENDERDOC / "Resources" / "resources.qrc")

    for path in sorted(set(search_paths)):
        if path.suffix.lower() not in {".cpp", ".h", ".ui", ".qrc"}:
            continue
        if HERE in path.parents:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            for name, name_needles in needles.items():
                if any(needle in line for needle in name_needles):
                    refs[name].append(f"{path.relative_to(REPO).as_posix()}:{line_no}")
    return refs


def reference_cells(name: str) -> list[str]:
    root = ARTIFACTS / "reference-cells"
    if not root.exists():
        return []
    matches = sorted(root.glob(f"*_{name}.png")) + sorted(root.glob(f"*_{name}@2x.png"))
    return [path.relative_to(REPO).as_posix() for path in matches]


def legacy_color_families() -> dict[str, list[str]]:
    report = ARTIFACTS / "legacy_color_audit.json"
    if not report.exists():
        return {}
    data = json.loads(report.read_text(encoding="utf-8"))
    return {entry["id"]: entry["chromatic_families"] for entry in data["icons"]}


def svg_source_colors(text: str) -> list[str]:
    colors = []
    for token in ("#000000", *SOURCE_COLORS):
        if token in text and token not in colors:
            colors.append(token)
    return colors


def main() -> int:
    missing_semantics = sorted(set(ICONS) - set(SEMANTICS))
    if missing_semantics:
        raise SystemExit(f"Missing semantic descriptions: {missing_semantics}")
    validate_semantic_distinctness()

    MONO_DIR.mkdir(parents=True, exist_ok=True)
    COLOR_DIR.mkdir(parents=True, exist_ok=True)

    for name, body in sorted(ICONS.items()):
        color_svg = svg(body, COLOR_PRIMARY.get(name, "#000000"))
        mono_body = MONO_OVERRIDES.get(name, monochrome(body))
        mono_svg = svg(mono_body)
        # Keep the compatibility path on the restrained semantic-color variant.
        (HERE / f"{name}.svg").write_text(color_svg, encoding="utf-8", newline="\n")
        (COLOR_DIR / f"{name}.svg").write_text(color_svg, encoding="utf-8", newline="\n")
        (MONO_DIR / f"{name}.svg").write_text(mono_svg, encoding="utf-8", newline="\n")

    reference_index = build_code_reference_index(sorted(ICONS))
    family_index = legacy_color_families()
    entries = []
    for name in sorted(ICONS):
        normal = QRENDERDOC / "Resources" / f"{name}.png"
        high_dpi = QRENDERDOC / "Resources" / f"{name}@2x.png"
        entries.append(
            {
                "id": name,
                "source_file": normal.relative_to(REPO).as_posix(),
                "source_file_2x": high_dpi.relative_to(REPO).as_posix(),
                "source_sha256": sha256(normal),
                "source_2x_sha256": sha256(high_dpi),
                "qrc_alias": f":/modern/{name}.svg",
                "semantic": SEMANTICS[name],
                "category": category_for(name),
                "states": ["hover"] if name == "action_hover" else ["normal", "hover", "disabled"],
                "style": "outline",
                "symmetry": SYMMETRY.get(name, "none"),
                "direction_sensitive": name in DIRECTIONAL,
                "semantic_color": SEMANTIC_COLORS.get(name),
                "target_svg": f"qrenderdoc/Resources/modern/{name}.svg",
                "target_svg_color": f"qrenderdoc/Resources/modern/color/{name}.svg",
                "target_svg_mono": f"qrenderdoc/Resources/modern/mono/{name}.svg",
                "color_strategy": "legacy palette reconstruction" if COLOR_PRIMARY.get(name) or len(svg_source_colors(svg(ICONS[name]))) > 1 else "runtime tint mask",
                "legacy_color_families": family_index.get(name, []),
                "color_variant_source_colors": svg_source_colors(svg(ICONS[name], COLOR_PRIMARY.get(name, "#000000"))),
                "reference_cells": reference_cells(name),
                "code_references": reference_index[name],
                "notes": NOTES.get(name, "Preserve the legacy action semantics"),
            }
        )

    manifest = {
        "schema": 2,
        "design_source": "DComp Modern Light UI asset bundle v3, legacy PNG palette audit, seven ImageGen art-direction sheets, and the focused connector corrective reference",
        "canonical_viewbox": [0, 0, 24, 24],
        "display_sizes_px": [16, 20, 24, 32, 48],
        "legacy_png_records": 142,
        "logical_icons": len(entries),
        "variants": ["mono", "legacy_color"],
        "default_variant": "legacy_color",
        "legacy_color_palette": LEGACY_COLOR_PALETTE,
        "palette_policy": "Preserve legacy functional hue families with flat modern colours; colour is never the only state cue",
        "small_size_strategy": "Prefer solid silhouettes, integer-aligned geometry, the maximum permitted 2 px detail stroke, two-unit semantic gaps, and direct rendering at each target size over smoothing a single raster",
        "intentional_geometry_equivalences": [sorted(pair) for pair in sorted(INTENTIONAL_BODY_EQUIVALENCES, key=lambda pair: sorted(pair))],
        "semantic_distinctness_guards": [sorted(pair) for pair in sorted(DISTINCT_SEMANTIC_PAIRS, key=lambda pair: sorted(pair))],
        "icons": entries,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (HERE / "icon-manifest.json").write_text(text, encoding="utf-8", newline="\n")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "icon_inventory.json").write_text(text, encoding="utf-8", newline="\n")
    print(f"generated {len(entries)} logical icons in mono and semantic-color variants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
