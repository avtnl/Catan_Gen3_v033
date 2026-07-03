"""
test.py

Standalone outlook-logic test runner.

Purpose
-------
- Load/display a board state for outlook testing.
- If LOAD_GAME=True, load constants.SAVED_GAME via Game.load_game(...).
- If LOAD_GAME=False, optionally call Board.load_test_board(...) to add TestBoard cities/settlements/roads.
- Display board, button panel, and scoreboard.
- Show a "Test" button instead of the normal "Play" flow.
- When "Test" is clicked:
    1. call core.outlook_logic.update_outlook_targets(game)
    2. draw colored circles around each player's:
        - outlook.next_settlements
        - outlook.next_roads
        - outlook.new_settlements
        - outlook.new_settlement_paths

Circle radius by player color:
    Blue   -> 4
    Red    -> 6
    White  -> 8
    Orange -> 10

This file intentionally does NOT call InitialPlacement.run().
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple
import json

import pygame

from core.game import Game
from gui.gui import GUI
from gui.gui_constants import WIN, COLORS, POSITIONS, Font, initialize_sounds
from gui.event_handler import EventHandler
from core.outlook_logic import update_outlook_targets
from core.constants import LOAD_GAME, SAVED_GAME
from core.strategy_timing import (
    StrategyTimingEngine,
    format_game_top_strategies,
    write_strategy_timing_report_csv,
)
from core.action_planner import (
    build_action_timing_report,
    format_game_top_actions,
    save_action_timing_report_json,
    write_action_timing_report_csv,
)

# ──────────────────────────────────────────────────────────────────────────────
# Test configuration
# ──────────────────────────────────────────────────────────────────────────────

# TestBoard file to load for this standalone outlook test.
#
# Naming rule:
#   - PlayBoard... files are base-board files only.
#     They contain tiles and ports, but no cities, settlements, or roads.
#     They are loaded by Board.load_board(...).
#
#   - TestBoard... files are standalone test setups.
#     They contain base tile/port data plus optional CITIES, SETTLEMENTS,
#     and ROADS sections.
#     They are loaded by Board.load_test_board(...).
#
# Use None if you only want to use the normal board loading from constants.py.
#TEST_BOARD_FILE: Optional[str] = None

#TEST_BOARD_FILE: Optional[str] = "TestBoard_08_Apr_2026_13_33_06_OUTLOOK.txt"
TEST_BOARD_FILE: Optional[str] = None
TEST_BUTTON_RECT = pygame.Rect(20, 470, 130, 40)

STRATEGY_TIMING_TOP_N = 3
STRATEGY_TIMING_INCLUDE_ALL = False
STRATEGY_TIMING_INCLUDE_DEBUG = False

# New: report-only player trade opportunities.
STRATEGY_TIMING_INCLUDE_PLAYER_TRADE_OPPORTUNITIES = True
STRATEGY_TIMING_MAX_TRADE_VICTORY_POINTS = 6
STRATEGY_TIMING_MIN_TRADE_SURPLUS_CARDS = 1.25
STRATEGY_TIMING_MAX_TRADE_OPPORTUNITIES_PER_STRATEGY = 3

STRATEGY_TIMING_REPORT_DIR = Path(__file__).resolve().parent / "StrategyTimingReports"
STRATEGY_TIMING_ENGINE = None

# Stage-1 action timing report.
ACTION_TIMING_TOP_N = 5
ACTION_TIMING_INCLUDE_ALL = True
ACTION_TIMING_INCLUDE_DEBUG = False
ACTION_TIMING_REPORT_DIR = Path(__file__).resolve().parent / "ActionTimingReports"

PLAYER_RADIUS_BY_COLOR = {
    "Blue": 4,
    "Red": 6,
    "White": 8,
    "Orange": 10,
}


PANEL_STATE = {
    "selected_player_id": None,
    "player_buttons": [],
    "back_button": None,
}


# ──────────────────────────────────────────────────────────────────────────────
# Small drawing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _color_key(color: str) -> str:
    """Convert 'Blue' to 'BLUE' for COLORS lookup."""
    return str(color or "").upper()


def _player_draw_color(player) -> Tuple[int, int, int]:
    """Return the pygame color tuple for a player."""
    return COLORS.get(_color_key(getattr(player, "color", "")), COLORS["BLACK"])


def _player_circle_radius(player) -> int:
    """Return the requested overlay radius for a player."""
    return PLAYER_RADIUS_BY_COLOR.get(getattr(player, "color", ""), 5)


def _road_midpoint(road_id: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Return screen midpoint for a road id, or None if coordinates are missing."""
    try:
        a, b = tuple(road_id)
    except Exception:
        return None

    pos_a = POSITIONS["intersections"].get(a)
    pos_b = POSITIONS["intersections"].get(b)

    if pos_a is None or pos_b is None:
        return None

    return ((pos_a[0] + pos_b[0]) // 2, (pos_a[1] + pos_b[1]) // 2)


def draw_test_button(active: bool = True) -> None:
    """
    Draw a simple Test button in the same area where Play/next_turn2 normally sits.
    """
    border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
    text_color = COLORS["BLACK"] if active else COLORS["GRAY"]

    pygame.draw.rect(WIN, COLORS["LGRAY"], TEST_BUTTON_RECT)
    pygame.draw.rect(WIN, border_color, TEST_BUTTON_RECT, 2)

    font = Font.LARGE.value["regular"]
    text = font.render("Test", True, text_color)

    text_rect = text.get_rect(center=TEST_BUTTON_RECT.center)
    WIN.blit(text, text_rect)


def draw_outlook_overlay(game: Game) -> None:
    """
    Draw circles around outlook targets.

    Per player:
        - next_settlements: circle around intersection
        - new_settlements: circle around intersection
        - next_roads: circle at road midpoint

    All overlays use the player color and the requested per-color radius.
    """
    for player in game.players:
        outlooks = getattr(player, "outlook", [])
        if not outlooks:
            continue

        outlook = outlooks[0]
        color = _player_draw_color(player)
        radius = _player_circle_radius(player)

        # 1. Next settlements
        for inter_id in getattr(outlook, "next_settlements", []) or []:
            pos = POSITIONS["intersections"].get(inter_id)
            if pos is not None:
                pygame.draw.circle(WIN, color, pos, radius, width=2)

        # 2. New settlements
        for inter_id in getattr(outlook, "new_settlements", []) or []:
            pos = POSITIONS["intersections"].get(inter_id)
            if pos is not None:
                pygame.draw.circle(WIN, color, pos, radius, width=2)

        # 3. Next roads
        for road_id in getattr(outlook, "next_roads", []) or []:
            midpoint = _road_midpoint(tuple(road_id))
            if midpoint is not None:
                pygame.draw.circle(WIN, color, midpoint, radius, width=2)


def redraw_test_screen(game: Game, gui: GUI, overlay_tf: bool = False) -> None:
    """
    Redraw board, permanent buildings, scoreboard, Test button, outlook panel,
    and optional overlay.
    """
    WIN.fill(COLORS["LGRAY"])

    gui.display_fresh_board(game.board, scoreboard_tf=True)
    gui.draw_all_permanent_buildings(game.board)
    gui.update_round_turn(game, special=False)
    gui.update_scoreboard(game)

    draw_test_button(active=True)

    if overlay_tf:
        draw_outlook_overlay(game)

    draw_outlook_text_panel(game)

    pygame.display.update()

def _fmt_values(values) -> str:
    """Format a list of ids/roads for the outlook text panel."""
    values = list(values or [])

    if not values:
        return "-"

    return ", ".join(str(value) for value in values)


def _turns_label(value) -> str:
    """Format an EH turn estimate for the panel."""
    try:
        turns = float(value)
    except Exception:
        return "?"

    if turns >= 9999.0:
        return "∞"

    rounded = int(round(turns))
    if abs(turns - rounded) < 1e-9:
        return str(rounded)

    return f"{turns:.2f}"


def _record_for_new_settlement(outlook, inter_id: int):
    """Find the structured new-settlement path record for one target."""
    for record in getattr(outlook, "new_settlement_paths", []) or []:
        if not isinstance(record, dict):
            continue
        try:
            if int(record.get("intersection_id")) == int(inter_id):
                return record
        except Exception:
            continue
    return None


def _record_for_next_settlement(outlook, inter_id: int):
    """Find the EH next-settlement plan record for one target."""
    for record in getattr(outlook, "next_settlement_plans", []) or []:
        if not isinstance(record, dict):
            continue
        try:
            if int(record.get("intersection_id")) == int(inter_id):
                return record
        except Exception:
            continue
    return None


def _fmt_new_settlements_compact(outlook) -> str:
    """
    Compact default-panel format for new settlements.

    Example:
        53 (1/2), 54 (2/3)

    Meaning:
        1/2 = one additional road must still be built / path length 2
        2/3 = two additional roads must still be built / path length 3
    """
    values = list(getattr(outlook, "new_settlements", []) or [])

    if not values:
        return "-"

    parts = []
    for inter_id in values:
        record = _record_for_new_settlement(outlook, inter_id)
        if not record:
            parts.append(str(inter_id))
            continue

        roads_to_build = record.get("roads_to_build", []) or []
        road_count = record.get("road_count", len(roads_to_build))
        distance = record.get("distance", len(record.get("path", []) or []))
        parts.append(f"{inter_id} ({road_count}/{distance})")

    return ", ".join(parts)


def _fmt_player_common_new_details(game: Game, target_id: int) -> str:
    """
    Format common_new_settlements details by player, including EH turns if present.
    """
    parts = []

    for player in getattr(game, "players", []) or []:
        outlooks = getattr(player, "outlook", []) or []
        if not outlooks:
            continue

        record = _record_for_new_settlement(outlooks[0], target_id)
        if not record:
            continue

        turns = _turns_label(record.get("expected_turns"))
        parts.append(f"{player.color} {turns}")

    return ", ".join(parts) if parts else "-"


def _draw_button(rect: pygame.Rect, label: str, font, *, active: bool = True) -> None:
    """Draw a small text button and border."""
    border_color = COLORS["GREEN"] if active else COLORS.get("GRAY", (120, 120, 120))
    text_color = COLORS["BLACK"] if active else COLORS.get("GRAY", (120, 120, 120))
    pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), rect)
    pygame.draw.rect(WIN, border_color, rect, 2)
    text = font.render(label, True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))



def _is_white_color(color_name: str) -> bool:
    """Return True for the White player color."""
    return str(color_name or "").strip().lower() == "white"


def _color_tuple_from_name(color_name: str):
    """Return pygame color tuple for a color name."""
    return COLORS.get(str(color_name or "").upper(), COLORS.get("BLACK", (0, 0, 0)))


def _draw_player_diamond(
    color_name: str,
    center: Tuple[int, int],
    *,
    size: int = 7,
    border_width: int = 1,
) -> None:
    """
    Draw a player-color diamond.

    White diamonds always receive a black border so they remain visible.
    """
    fill = _color_tuple_from_name(color_name)
    border = COLORS.get("BLACK", (0, 0, 0))
    x, y = center
    points = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    pygame.draw.polygon(WIN, fill, points)
    pygame.draw.polygon(WIN, border, points, border_width)


def _draw_player_button_marker(player, center: Tuple[int, int]) -> None:
    """Draw the marker used inside a clickable player-title button."""
    _draw_player_diamond(getattr(player, "color", ""), center, size=7, border_width=1)


def _common_record_target_id(record) -> str:
    """Return display label for a common settlement/road record."""
    if isinstance(record, dict):
        if "intersection_id" in record:
            return str(record.get("intersection_id"))
        if "road_id" in record:
            return str(record.get("road_id"))
    return str(record)


def _common_record_players(record) -> list:
    """Return player entries from a structured common record."""
    if isinstance(record, dict):
        return list(record.get("players", []) or [])
    return []


def _dedupe_player_entries(entries) -> list:
    """
    Collapse common-target player entries to one entry per player.

    A player may appear more than once for the same common road/settlement when
    multiple paths or target settlements contain the same contested item.  For
    display we keep the best/earliest expected_turns for that player.
    """
    best_by_player = {}

    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue

        player_id = entry.get("player_id")
        color = entry.get("color", "")

        # Prefer player_id when available, otherwise fall back to color.
        key = player_id if player_id is not None else color
        if key in (None, ""):
            continue

        current_best = best_by_player.get(key)

        def _turn_value(item):
            try:
                return float(item.get("expected_turns", 9999.0))
            except Exception:
                return 9999.0

        if current_best is None or _turn_value(entry) < _turn_value(current_best):
            best_by_player[key] = entry

    def _sort_key(item):
        try:
            return (float(item.get("expected_turns", 9999.0)), int(item.get("player_id", 9999)))
        except Exception:
            return (9999.0, 9999)

    return sorted(best_by_player.values(), key=_sort_key)


def _common_record_players_deduped(record) -> list:
    """Return one best player entry per player for a common record."""
    return _dedupe_player_entries(_common_record_players(record))


def _common_record_player_count(record) -> int:
    """Return number of distinct players competing for a common record."""
    return len(_common_record_players_deduped(record))


def _fmt_common_records_compact(records) -> str:
    """
    Compact common-target format.

    Examples:
        9 (2), 15 (3)
        [15, 16] (2), [47, 48] (3)
    """
    parts = []
    for record in list(records or []):
        count = _common_record_player_count(record)
        if count <= 0:
            continue
        parts.append(f"{_common_record_target_id(record)} ({count})")

    return ", ".join(parts) if parts else "-"


def _records_for_selected_player(records, player_id: int) -> list:
    """Return common records where the selected player is one of the competitors."""
    selected = []
    for record in list(records or []):
        players = _common_record_players_deduped(record)
        try:
            found = any(int(entry.get("player_id")) == int(player_id) for entry in players)
        except Exception:
            found = False
        if found:
            selected.append(record)
    return selected


def _common_new_settlement_entries(game: Game, target_id: int) -> list:
    """Return structured player entries for one common_new_settlement target."""
    for record in getattr(game, "common_new_settlements", []) or []:
        if not isinstance(record, dict):
            continue

        try:
            if int(record.get("intersection_id")) == int(target_id):
                return _dedupe_player_entries(record.get("players", []) or [])
        except Exception:
            continue

    return []


def _draw_new_settlement_detail_line(
    game: Game,
    player,
    record: dict,
    x: int,
    y: int,
    font,
    text_color,
    max_width: int,
) -> int:
    """
    Draw one selected-player new-settlement line.

    Compact format:
        5: 6 turns  ♦ 8, ♦ 10

    The first turn value is for the selected player.  The diamonds show opponents
    that also target the same new settlement, with their expected turns.
    """
    if not isinstance(record, dict):
        return y

    inter_id = record.get("intersection_id", "?")
    turns = _turns_label(record.get("expected_turns"))
    base_text = f"{inter_id}: {turns} turns"

    base_surface = font.render(base_text, True, text_color)
    WIN.blit(base_surface, (x, y))
    cursor_x = x + base_surface.get_width() + 8
    line_h = 18

    entries = _common_new_settlement_entries(game, inter_id)
    competitors = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get("player_id")) == int(getattr(player, "id", -1)):
                continue
        except Exception:
            pass
        competitors.append(entry)

    for idx, entry in enumerate(competitors):
        # Wrap marker group to the next line if it does not fit.
        if cursor_x > x + max_width - 45:
            y += line_h
            cursor_x = x + 16

        _draw_player_diamond(entry.get("color", ""), (cursor_x + 7, y + 8), size=6, border_width=1)
        cursor_x += 17

        label = _turns_label(entry.get("expected_turns"))
        if idx < len(competitors) - 1:
            label += ", "

        surf = font.render(label, True, text_color)
        WIN.blit(surf, (cursor_x, y))
        cursor_x += surf.get_width() + 2

    return y + line_h


def _draw_common_record_line(
    record,
    x: int,
    y: int,
    font,
    text_color,
    max_width: int,
    *,
    prefix: str = "",
) -> int:
    """
    Draw one common/contested record with player diamonds and EH turns.

    Example visual content:
        44: ♦ 8, ♦ 9
        [41, 52]: ♦ 6, ♦ 8
    """
    label = f"{prefix}{_common_record_target_id(record)}: "
    label_surface = font.render(label, True, text_color)
    WIN.blit(label_surface, (x, y))
    cursor_x = x + label_surface.get_width()
    line_h = 18

    players = _common_record_players_deduped(record)
    if not players:
        dash = font.render("-", True, text_color)
        WIN.blit(dash, (cursor_x, y))
        return y + line_h

    for idx, entry in enumerate(players):
        if cursor_x > x + max_width - 45:
            y += line_h
            cursor_x = x + 12

        color_name = entry.get("color", "") if isinstance(entry, dict) else ""
        _draw_player_diamond(color_name, (cursor_x + 7, y + 8), size=6, border_width=1)
        cursor_x += 17

        turns = _turns_label(entry.get("expected_turns") if isinstance(entry, dict) else None)
        txt = turns
        if idx < len(players) - 1:
            txt += ", "
        surf = font.render(txt, True, text_color)
        WIN.blit(surf, (cursor_x, y))
        cursor_x += surf.get_width() + 2

    return y + line_h


def _draw_common_section(
    title: str,
    records,
    x: int,
    y: int,
    body_font,
    small_font,
    text_color,
    max_text_w: int,
) -> int:
    """Draw a titled common-target section with player diamonds and EH turns."""
    section = body_font.render(title, True, text_color)
    WIN.blit(section, (x, y))
    y += 22

    records = list(records or [])
    if not records:
        return _draw_wrapped_text("-", x + 10, y, small_font, text_color, max_text_w - 10, 18)

    for record in records:
        y = _draw_common_record_line(record, x + 10, y, small_font, text_color, max_text_w - 10)
    return y


def _draw_common_compact_section(
    title: str,
    records,
    x: int,
    y: int,
    body_font,
    small_font,
    text_color,
    max_text_w: int,
) -> int:
    """Draw a titled common-target section in compact count format."""
    section = body_font.render(title, True, text_color)
    WIN.blit(section, (x, y))
    y += 22
    return _draw_wrapped_text(
        _fmt_common_records_compact(records),
        x + 10,
        y,
        small_font,
        text_color,
        max_text_w - 10,
        18,
    )


def _draw_wrapped_text(
    text: str,
    x: int,
    y: int,
    font,
    color,
    max_width: int,
    line_height: int,
) -> int:
    """
    Draw text with simple word wrapping.

    Returns:
        next y-position after the rendered text.
    """
    words = str(text).split(" ")
    line = ""

    for word in words:
        test_line = word if not line else f"{line} {word}"

        if font.size(test_line)[0] <= max_width:
            line = test_line
        else:
            if line:
                surface = font.render(line, True, color)
                WIN.blit(surface, (x, y))
                y += line_height

            line = word

    if line:
        surface = font.render(line, True, color)
        WIN.blit(surface, (x, y))
        y += line_height

    return y


def _draw_default_outlook_panel(game: Game, x: int, y: int, max_text_w: int, body_font, small_font, text_color, border_color) -> int:
    """Draw the compact all-player outlook summary."""
    PANEL_STATE["player_buttons"] = []
    PANEL_STATE["back_button"] = None

    for player in game.players:
        outlooks = getattr(player, "outlook", [])
        outlook = outlooks[0] if outlooks else None

        player_color = _player_draw_color(player)
        player_name = f"Player {player.id} {player.color}"

        # Clickable player title.
        button_rect = pygame.Rect(x, y - 2, max_text_w, 22)
        PANEL_STATE["player_buttons"].append((button_rect, player.id))
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), button_rect)
        button_border = COLORS.get("BLACK", (0, 0, 0)) if _is_white_color(getattr(player, "color", "")) else player_color
        pygame.draw.rect(WIN, button_border, button_rect, 2)
        _draw_player_button_marker(player, (x + 10, y + 9))
        header = body_font.render(player_name, True, text_color)
        WIN.blit(header, (x + 24, y))
        y += 26

        if outlook is None:
            y = _draw_wrapped_text(
                "next_settlements: -",
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
                18,
            )
            y = _draw_wrapped_text(
                "new_settlements: -",
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
                18,
            )
        else:
            next_settlements = getattr(outlook, "next_settlements", []) or []

            y = _draw_wrapped_text(
                f"next_settlements: {_fmt_values(next_settlements)}",
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
                18,
            )

            y = _draw_wrapped_text(
                f"new_settlements: {_fmt_new_settlements_compact(outlook)}",
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
                18,
            )

        y += 8

    # Divider
    pygame.draw.line(WIN, border_color, (x, y), (x + max_text_w, y), 1)
    y += 12

    common_title = body_font.render("Common / contested", True, text_color)
    WIN.blit(common_title, (x, y))
    y += 24

    y = _draw_common_section(
        "common_next_settlements",
        getattr(game, "common_next_settlements", []),
        x,
        y,
        body_font,
        small_font,
        text_color,
        max_text_w,
    )
    y += 6

    y = _draw_common_compact_section(
        "common_new_settlements",
        getattr(game, "common_new_settlements", []),
        x,
        y,
        body_font,
        small_font,
        text_color,
        max_text_w,
    )
    y += 6

    y = _draw_common_compact_section(
        "common_new_roads",
        getattr(game, "common_new_roads", []),
        x,
        y,
        body_font,
        small_font,
        text_color,
        max_text_w,
    )

    return y


def _draw_player_detail_panel(game: Game, player, x: int, y: int, max_text_w: int, body_font, small_font, text_color, border_color) -> int:
    """Draw detailed outlook/EH information for one selected player."""
    PANEL_STATE["player_buttons"] = []

    back_rect = pygame.Rect(x, y, 70, 24)
    PANEL_STATE["back_button"] = back_rect
    _draw_button(back_rect, "Back", small_font)
    y += 34

    _draw_player_button_marker(player, (x + 10, y + 9))
    header = body_font.render(f"Player {player.id} {player.color} details", True, text_color)
    WIN.blit(header, (x + 24, y))
    y += 28

    outlooks = getattr(player, "outlook", []) or []
    outlook = outlooks[0] if outlooks else None
    if outlook is None:
        return _draw_wrapped_text("No outlook data yet. Click Test first.", x, y, small_font, text_color, max_text_w, 18)

    section = body_font.render("next_settlements", True, text_color)
    WIN.blit(section, (x, y))
    y += 22

    next_values = list(getattr(outlook, "next_settlements", []) or [])
    if not next_values:
        y = _draw_wrapped_text("-", x + 10, y, small_font, text_color, max_text_w - 10, 18)
    else:
        for inter_id in next_values:
            record = _record_for_next_settlement(outlook, inter_id)
            turns = _turns_label(record.get("expected_turns") if record else None)
            conf = record.get("confidence") if record else None
            conf_txt = f", conf={float(conf):.2f}" if isinstance(conf, (int, float)) else ""
            y = _draw_wrapped_text(
                f"{inter_id}: {turns} turns{conf_txt}",
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
                18,
            )

    y += 8
    section = body_font.render("new_settlements", True, text_color)
    WIN.blit(section, (x, y))
    y += 22

    records = list(getattr(outlook, "new_settlement_paths", []) or [])
    if not records:
        y = _draw_wrapped_text("-", x + 10, y, small_font, text_color, max_text_w - 10, 18)
    else:
        for record in records:
            if not isinstance(record, dict):
                continue
            y = _draw_new_settlement_detail_line(
                game,
                player,
                record,
                x + 10,
                y,
                small_font,
                text_color,
                max_text_w - 10,
            )

    y += 8
    pygame.draw.line(WIN, border_color, (x, y), (x + max_text_w, y), 1)
    y += 12

    selected_common_new_roads = _records_for_selected_player(
        getattr(game, "common_new_roads", []),
        getattr(player, "id", -1),
    )

    y = _draw_common_section(
        "common_new_roads",
        selected_common_new_roads,
        x,
        y,
        body_font,
        small_font,
        text_color,
        max_text_w,
    )

    return y


def draw_outlook_text_panel(game: Game) -> None:
    """
    Draw the right-side outlook panel.

    Default view:
        compact all-player summary, including new_settlements as:
            53 (1/2), 54 (2/3)

    Detail view:
        click a player title to show detailed EH timing for that player.
        click Back to return to the compact all-player summary.
    """
    bg_color = COLORS.get("WHITE", (255, 255, 255))
    border_color = COLORS.get("BLACK", (0, 0, 0))
    text_color = COLORS.get("BLACK", (0, 0, 0))
    muted_color = COLORS.get("GRAY", (120, 120, 120))

    title_font = Font.LARGE.value["regular"]
    body_font = pygame.font.SysFont(None, 20)
    small_font = pygame.font.SysFont(None, 18)

    intersection_positions = list(POSITIONS.get("intersections", {}).values())
    board_right = max(pos[0] for pos in intersection_positions) if intersection_positions else 850

    panel_x = board_right + 70
    panel_y = 55
    panel_w = WIN.get_width() - panel_x - 20

    if panel_w < 280:
        panel_w = 320
        panel_x = max(20, WIN.get_width() - panel_w - 20)

    panel_h = WIN.get_height() - panel_y - 25
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    pygame.draw.rect(WIN, bg_color, panel_rect)
    pygame.draw.rect(WIN, border_color, panel_rect, 2)

    x = panel_x + 12
    y = panel_y + 10
    max_text_w = panel_w - 24

    selected_player_id = PANEL_STATE.get("selected_player_id")
    selected_player = None
    if selected_player_id is not None:
        selected_player = next((p for p in game.players if p.id == selected_player_id), None)

    title_text = "Outlook details" if selected_player is not None else "Outlook targets"
    title = title_font.render(title_text, True, text_color)
    WIN.blit(title, (x, y))
    y += 34

    hint_text = "Click Back for all players" if selected_player is not None else "Click Test to refresh; click player for details"
    hint = small_font.render(hint_text, True, muted_color)
    WIN.blit(hint, (x, y))
    y += 26

    if selected_player is not None:
        _draw_player_detail_panel(game, selected_player, x, y, max_text_w, body_font, small_font, text_color, border_color)
    else:
        _draw_default_outlook_panel(game, x, y, max_text_w, body_font, small_font, text_color, border_color)


def handle_outlook_panel_click(pos) -> bool:
    """
    Handle clicks on the right-side outlook panel.

    Returns True when the click changed the panel state.
    """
    back_button = PANEL_STATE.get("back_button")
    if back_button is not None and back_button.collidepoint(pos):
        PANEL_STATE["selected_player_id"] = None
        return True

    for rect, player_id in PANEL_STATE.get("player_buttons", []) or []:
        if rect.collidepoint(pos):
            PANEL_STATE["selected_player_id"] = player_id
            return True

    return False

# ──────────────────────────────────────────────────────────────────────────────
# Test-board loading / player sync
# ──────────────────────────────────────────────────────────────────────────────

def sync_players_from_board(game: Game) -> None:
    """
    Best-effort sync after Board.load_test_board(...).

    Board.load_test_board(...) should ideally update both:
        - board intersections/roads
        - player.settlements/player.roads/player.cities

    This helper protects the test runner when load_test_board only updates board
    objects. It rebuilds player settlements, cities, and roads from board colors.
    """
    color_to_player = {
        getattr(player, "color", None): player
        for player in game.players
        if getattr(player, "color", None)
    }

    for player in game.players:
        player.settlements = []
        player.cities = []
        player.roads = []

    for inter in getattr(game.board, "intersections", []) or []:
        if inter is None:
            continue
        if not getattr(inter, "occupied_tf", False):
            continue

        player = color_to_player.get(getattr(inter, "color", None))
        if player is None:
            continue

        face = getattr(inter, "face", "Settlement")
        if face == "City":
            if inter.id not in player.cities:
                player.cities.append(inter.id)
        else:
            if inter.id not in player.settlements:
                player.settlements.append(inter.id)

    for road in getattr(game.board, "roads", []) or []:
        if road is None:
            continue
        if not getattr(road, "occupied_tf", False):
            continue

        player = color_to_player.get(getattr(road, "color", None))
        if player is None:
            continue

        road_id = tuple(sorted(getattr(road, "id", ())))
        if len(road_id) == 2 and road_id not in player.roads:
            player.roads.append(road_id)

    for player in game.players:
        try:
            game.update_strategy_dashboard(player)
        except Exception:
            pass


def maybe_load_test_board(game: Game) -> None:
    """
    Load TEST_BOARD_FILE when configured.

    This branch is used only when LOAD_GAME=False.

    Rules:
        - TEST_BOARD_FILE must start with 'TestBoard'.
        - Board.load_test_board(...) must be used for TestBoard files.
        - Saved_Game files must not be assigned to TEST_BOARD_FILE.
          Saved games are loaded via constants.SAVED_GAME when LOAD_GAME=True.
    """
    if not TEST_BOARD_FILE:
        print("test.py | TEST_BOARD_FILE is None; using board as initialized by Game/Board.")
        return

    test_path = Path(TEST_BOARD_FILE)

    if test_path.name.startswith("Saved_Game"):
        raise ValueError(
            f"TEST_BOARD_FILE must not point to a saved game: {test_path.name!r}. "
            "Use constants.LOAD_GAME=True and constants.SAVED_GAME instead."
        )

    if not test_path.name.startswith("TestBoard"):
        raise ValueError(
            f"test.py expected TEST_BOARD_FILE to start with 'TestBoard', "
            f"got {test_path.name!r}. "
            "Use a TestBoard file for outlook tests. "
            "Use Saved_Game files only through Game.load_game(...)."
        )

    if not hasattr(game.board, "load_test_board"):
        print(
            "test.py | Board.load_test_board(...) does not exist yet. "
            "Add it to core/board.py before using TEST_BOARD_FILE."
        )
        return

    print(f"test.py | loading test board: {test_path}")

    try:
        result = game.board.load_test_board(str(test_path), players=game.players)
    except TypeError:
        result = game.board.load_test_board(str(test_path))

    print(f"test.py | load_test_board result = {result}")

    sync_players_from_board(game)


# ──────────────────────────────────────────────────────────────────────────────
# Test action
# ──────────────────────────────────────────────────────────────────────────────

def run_action_timing_report(game: Game) -> dict:
    """
    Generate and save the Stage-1/2 build-action timing and projection report.

    Stage 1 evaluates concrete build actions found from outlook_logic:
        - city upgrades from current settlements
        - next settlements
        - new settlements plus required roads

    Stage 2 adds the hypothetical after-action player state.
    Later Stage 3 will add top-3 continuation strategies.
    """
    print("test.py | generating Stage-1/2 action timing + projection report")

    report = build_action_timing_report(
        game,
        top_n_actions=ACTION_TIMING_TOP_N,
        include_all=ACTION_TIMING_INCLUDE_ALL,
        include_debug=ACTION_TIMING_INCLUDE_DEBUG,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    round_label = getattr(game, "round", "X")
    turn_label = getattr(game, "turn", "X")
    filename = f"ActionPlan_Report_{timestamp}_R{round_label}T{turn_label}.json"

    ACTION_TIMING_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ACTION_TIMING_REPORT_DIR / filename
    csv_path = report_path.with_suffix(".csv")

    save_action_timing_report_json(report, report_path)
    write_action_timing_report_csv(report, csv_path)

    game.action_timing_report = report
    game.action_timing_report_path = str(report_path)
    game.action_timing_report_csv_path = str(csv_path)

    print(format_game_top_actions(report, limit=ACTION_TIMING_TOP_N))
    print(f"test.py | action projection report saved: {report_path}")
    print(f"test.py | action projection CSV saved: {csv_path}")

    return report

def run_strategy_timing_report(game: Game) -> dict:
    """
    Generate and save the JSON-friendly 142-way strategy timing report.

    The report is also attached to:
        game.strategy_timing_report
        game.strategy_timing_report_path
    """
    global STRATEGY_TIMING_ENGINE

    if STRATEGY_TIMING_ENGINE is None:
        STRATEGY_TIMING_ENGINE = StrategyTimingEngine()

    print("test.py | generating 142-way strategy timing report")

    report = STRATEGY_TIMING_ENGINE.rank_for_game(
        game,
        top_n=STRATEGY_TIMING_TOP_N,
        include_all=STRATEGY_TIMING_INCLUDE_ALL,
        include_debug=STRATEGY_TIMING_INCLUDE_DEBUG,
        include_player_trade_opportunities=STRATEGY_TIMING_INCLUDE_PLAYER_TRADE_OPPORTUNITIES,
        max_trade_victory_points=STRATEGY_TIMING_MAX_TRADE_VICTORY_POINTS,
        min_trade_surplus_cards=STRATEGY_TIMING_MIN_TRADE_SURPLUS_CARDS,
        max_trade_opportunities_per_strategy=STRATEGY_TIMING_MAX_TRADE_OPPORTUNITIES_PER_STRATEGY,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    round_label = getattr(game, "round", "X")
    turn_label = getattr(game, "turn", "X")

    filename = f"StrategyTiming_Report_{timestamp}_R{round_label}T{turn_label}.json"

    STRATEGY_TIMING_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = STRATEGY_TIMING_REPORT_DIR / filename

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    csv_path = report_path.with_suffix(".csv")
    write_strategy_timing_report_csv(report, csv_path, top_n=STRATEGY_TIMING_TOP_N)

    game.strategy_timing_report = report
    game.strategy_timing_report_path = str(report_path)
    game.strategy_timing_report_csv_path = str(csv_path)

    print(format_game_top_strategies(report, limit=STRATEGY_TIMING_TOP_N))
    print(f"test.py | strategy timing report saved: {report_path}")
    print(f"test.py | strategy timing CSV saved: {csv_path}")

    return report

def run_outlook_test(game: Game, gui: GUI) -> None:
    """
    Main test action triggered by pressing the Test button.

    Current behavior:
        1. refresh outlook targets
        2. generate 142-way strategy timing JSON report
        3. redraw test overlay
    """
    print("test.py | Test clicked -> updating outlook targets")

    update_outlook_targets(game)

    for player in game.players:
        outlook = player.outlook[0]
        print(
            f"Player {player.id} {player.color}: "
            f"next_settlements={getattr(outlook, 'next_settlements', [])}, "
            f"new_settlements={getattr(outlook, 'new_settlements', [])}, "
            f"new_settlements_compact={_fmt_new_settlements_compact(outlook)}, "
            f"next_roads={getattr(outlook, 'next_roads', [])}"
        )

    print(
        "Common targets: "
        f"common_next_settlements={getattr(game, 'common_next_settlements', [])}, "
        f"common_new_settlements={getattr(game, 'common_new_settlements', [])}, "
        f"common_next_roads={getattr(game, 'common_next_roads', [])}, "
        f"common_new_roads={getattr(game, 'common_new_roads', [])}"
    )

    run_action_timing_report(game)
    run_strategy_timing_report(game)

    redraw_test_screen(game, gui, overlay_tf=True)


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the outlook test GUI."""
    pygame.init()
    initialize_sounds()
    clock = pygame.time.Clock()

    today = datetime.now().strftime("%Y%m%d")

    game = Game(
        sequence_number=1,
        id_=f"test_{today}",
        phase="Test",
        state="OutlookTest",
        state_1="0",
        state_2="0",
        myplayers=None,
        board_name="Base_Random",
    )

    if LOAD_GAME:
        if not SAVED_GAME:
            raise ValueError("constants.LOAD_GAME=True, but constants.SAVED_GAME is empty.")

        if not Path(SAVED_GAME).name.startswith("Saved_Game"):
            raise ValueError(
                f"constants.SAVED_GAME should start with 'Saved_Game', got {SAVED_GAME!r}."
            )

        if not hasattr(game, "load_game"):
            raise AttributeError(
                "Game.load_game(...) does not exist. "
                "Add the saved-game update to core/game.py first."
            )

        print(f"test.py | LOAD_GAME=True -> loading saved game: {SAVED_GAME}")
        game.load_game(SAVED_GAME)

        # Keep the loaded round/turn/board/player state, but run the GUI in test mode.
        game.phase = "Test"
        game.state = "OutlookTest"
        game.sync_round_turn()

    else:
        # Normal execution-ish state for settlement distance/road logic.
        game.round = 1
        game.turn = 1
        game.phase = "Test"
        game.state = "OutlookTest"
        game.sync_round_turn()

    gui = GUI(round_number=game.round, turn=game.turn, game=game)
    game.gui = gui

    event_handler = EventHandler()

    if not LOAD_GAME:
        maybe_load_test_board(game)
    else:
        print("test.py | skipped TEST_BOARD_FILE because saved game was loaded.")

    overlay_tf = False
    redraw_test_screen(game, gui, overlay_tf=overlay_tf)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            if event.type == pygame.MOUSEBUTTONDOWN:
                if TEST_BUTTON_RECT.collidepoint(event.pos):
                    overlay_tf = True
                    run_outlook_test(game, gui)
                    continue

                if handle_outlook_panel_click(event.pos):
                    redraw_test_screen(game, gui, overlay_tf=overlay_tf)
                    continue

                # Keep the regular handler available for future small extensions.
                event_handler.handle_click(event.pos, game)

        pygame.display.update()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
