"""gui/gui_execution_debug_panel.py

Display-only Execution Debug panel.

This panel intentionally does not mutate game state.  It only explains the
current execution checkpoint:
- scan legality from viable_action_scanner / ExecutionPhaseManager
- strategic direction persisted by action_planner.py
- actionable intersection of strategy and legality
- best immediate action, wait reason, or forced-flow instruction
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import COLORS, EXECUTION_DEBUG_PANEL_RECT, Font, POSITIONS, WIN


BUY_DCARD = "Buy development_card"
BUILD_CITY = "Build city"
BUILD_SETTLEMENT = "Build settlement"
BUILD_ROAD = "Build road"
TWB = "TwB"

ACTION_ROWS: Tuple[Tuple[str, str], ...] = (
    (BUILD_CITY, "City"),
    (BUILD_SETTLEMENT, "Settle"),
    (BUILD_ROAD, "Road"),
    (BUY_DCARD, "DCard"),
    (TWB, "TwB"),
)

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_SHORT: Tuple[str, ...] = ("Wh", "O", "Wd", "B", "Sh")

ROBBER_STATES = {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"}


# ──────────────────────────────────────────────────────────────────────────────
# Public renderer
# ──────────────────────────────────────────────────────────────────────────────


def draw_execution_debug_panel(game: Any) -> None:
    """Draw the Execution Debug panel for the current-turn player."""

    panel = EXECUTION_DEBUG_PANEL_RECT.copy()
    pygame.draw.rect(WIN, COLORS["LGRAY"], panel)
    pygame.draw.rect(WIN, COLORS["BLACK"], panel, 1)

    title_font = Font.NORMAL.value["bold"]
    font = Font.SMALL.value["regular"]
    bold = Font.SMALL.value["bold"]

    x = panel.x + 8
    y = panel.y + 5
    line_h = 12

    _blit(title_font, "Execution Debug", x, y)
    y += 19

    if game is None:
        _blit(font, "No game object", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    player = _current_player(game)
    if player is None:
        _blit(font, "No current player", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    if str(getattr(game, "phase", "")) != "Execution":
        _blit(font, "Waiting for Execution phase", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    report = _current_player_report(game, player)
    choices = _current_player_choices(game, player)
    needs = _current_player_needs(game, player)
    direction = _strategy_direction(player)

    player_label = f"P{_safe_int(getattr(player, 'id', '?'))} {getattr(player, 'color', '')}"
    state = str(getattr(game, "state", "") or report.get("state", ""))
    round_num = _safe_int(getattr(game, "round", report.get("round", 0)))
    turn = _safe_int(getattr(game, "turn", report.get("turn", 0)))
    dice = _dice_text(game, report)

    _blit(bold, f"{player_label} | R{round_num} T{turn}", x, y)
    y += line_h
    _blit(font, f"{state or '-'} | Dice {dice}", x, y)
    y += line_h

    hand = _hand_vector(player)
    _blit(font, f"Hand {'/'.join(RESOURCE_SHORT)}: {'/'.join(str(v) for v in hand)}", x, y)
    y += line_h + 4

    forced = report.get("forced_action_mode")
    if forced:
        _blit(bold, f"FORCED: {forced}", x, y, COLORS["RED"])
        y += line_h + 4

    _section_title(bold, "SCAN", x, y)
    y += line_h
    y = _draw_scan_rows(game, player, report, choices, x, y, line_h, font, bold, panel)

    y += 3
    _section_title(bold, "STRATEGY", x, y)
    y += line_h
    y = _draw_strategy_rows(game, player, direction, needs, x, y, line_h, font, panel)

    y += 3
    _section_title(bold, "ACTIONABLE", x, y)
    y += line_h
    y = _draw_actionable_rows(game, player, choices, x, y, line_h, font, bold, panel)

    y += 3
    _section_title(bold, "BEST NOW", x, y)
    y += line_h
    best = _best_now_or_wait(game, player, direction, choices, report)
    _blit(font if best.startswith(("No ", "Wait", "Roll", "Resolve")) else bold, _fit_text(best, 64), x, y,
          COLORS["DGRAY"] if best.startswith("No ") else COLORS["BLACK"])

    _update(panel)


# ──────────────────────────────────────────────────────────────────────────────
# Section drawing
# ──────────────────────────────────────────────────────────────────────────────


def _draw_scan_rows(
    game: Any,
    player: Any,
    report: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    choices_by_action = {str(row.get("action", "")): row for row in choices if isinstance(row, Mapping)}

    scan = getattr(game, "current_viable_action_scan", None)
    flags: Dict[str, Any] = {}
    candidates_by_action: Dict[str, Any] = {}
    blockers_by_action: Dict[str, Any] = {}
    if isinstance(scan, Mapping):
        flags = dict(scan.get("action_flags", {}) or {})
        candidates_by_action = dict(scan.get("candidates", {}) or {})
        blockers_by_action = dict(scan.get("blockers", {}) or {})
    else:
        flags = dict(getattr(scan, "action_flags", {}) or {})
        candidates_by_action = dict(getattr(scan, "candidates", {}) or {})
        blockers_by_action = dict(getattr(scan, "blockers", {}) or {})

    for action, label in ACTION_ROWS:
        if y > panel.bottom - 72:
            return y

        choice = choices_by_action.get(action, {})
        choice_candidates = list(choice.get("candidates", []) or []) if isinstance(choice, Mapping) else []
        raw_candidates = list(candidates_by_action.get(action, []) or [])
        candidates = choice_candidates or raw_candidates
        blockers = list(choice.get("blockers", []) or blockers_by_action.get(action, []) or []) if isinstance(choice, Mapping) else list(blockers_by_action.get(action, []) or [])
        candidate_count = int(choice.get("candidate_count", len(candidates)) or len(candidates)) if isinstance(choice, Mapping) else len(candidates)

        strategy_locked = _is_strategy_locked_choice(choice, blockers)
        raw_viable = bool(
            (isinstance(choice, Mapping) and choice.get("scan_viable", False))
            or flags.get(action, False)
            or (strategy_locked and candidate_count > 0)
        )
        display_viable = raw_viable or bool(choice.get("viable", False)) if isinstance(choice, Mapping) else raw_viable

        marker = "Y" if display_viable else "N"
        row_color = COLORS["GREEN"] if display_viable else COLORS["DGRAY"]
        left = f"{marker} {label:<6} {candidate_count:>2}"
        _blit(bold, left, x, y, row_color)

        canonical = _canonical_best_now_action(game)
        canonical_action = str(canonical.get("action", "") or "") if canonical else ""
        canonical_label = str(canonical.get("best_now_label", "") or "") if canonical else ""
        blocked_action = str(canonical.get("blocked_action", "") or "") if canonical else ""

        if display_viable and strategy_locked:
            detail = "No strategic priority"
            detail_font = bold
            detail_color = COLORS["GREEN"]
        elif display_viable and canonical_action == action and canonical_label:
            detail = f"best {canonical_label}".strip()
            detail_font = font
            detail_color = COLORS["BLACK"]
        elif display_viable and bool(canonical.get("route_blocked")) and blocked_action == action:
            detail = "route target not legal"
            detail_font = bold
            detail_color = COLORS["DGRAY"]
        elif display_viable:
            detail = f"best {_best_label_for_action(game, player, action, candidates)}".strip()
            detail_font = font
            detail_color = COLORS["BLACK"]
        else:
            detail = _short_blocker(blockers) or (f"best {_best_label_for_action(game, player, action, candidates)}".strip())
            detail_font = font
            detail_color = COLORS["DGRAY"]

        if detail:
            _blit(detail_font, _fit_text(detail, 38), x + 78, y, detail_color)
        y += line_h

    return y

def _draw_strategy_rows(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    needs: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    panel: pygame.Rect,
) -> int:
    way = _way_id(direction)
    _blit(font, f"Way: {way if way not in (None, '') else '-'}", x, y)
    y += line_h

    tags = _strategy_tags(direction)
    tag_text = " | ".join(tags) if tags else "-"
    _blit(font, _fit_text(f"Tags: {tag_text}", 64), x, y)
    y += line_h

    needs_text = _strategy_needs_text(direction, needs)
    _blit(font, _fit_text(f"Needs: {needs_text}", 64), x, y)
    y += line_h

    target = _strategy_target_text(game, direction)
    risk = _strategy_risk_text(direction)
    target_line = f"Target: {target if target else '-'}"
    if risk:
        target_line += f" | Risk: {risk}"
    _blit(font, _fit_text(target_line, 64), x, y)
    return y + line_h



def _canonical_best_now_action(game: Any) -> Mapping[str, Any]:
    """Return Game's frozen BEST NOW object, if available."""
    item = getattr(game, "current_best_now_action", None)
    if isinstance(item, Mapping) and item.get("action"):
        return dict(item)
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping):
        item = report.get("canonical_best_now_action")
        if isinstance(item, Mapping) and item.get("action"):
            return dict(item)
    return {}

def _draw_actionable_rows(
    game: Any,
    player: Any,
    choices: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    canonical_blocked = _canonical_best_now_action(game)
    if canonical_blocked and bool(canonical_blocked.get("route_blocked")):
        _blit(font, "None", x, y, COLORS["DGRAY"])
        return y + line_h

    actionable = [row for row in choices if isinstance(row, Mapping) and bool(row.get("actionable"))]
    if not actionable:
        _blit(font, "None", x, y, COLORS["DGRAY"])
        return y + line_h

    for idx, row in enumerate(actionable[:3], start=1):
        if y > panel.bottom - 36:
            break
        action = str(row.get("action", ""))
        candidates = list(row.get("candidates", []) or [])
        canonical = _canonical_best_now_action(game) if idx == 1 else {}
        if canonical and str(canonical.get("action", "") or "") == action:
            best = str(canonical.get("best_now_label", "") or "")
        else:
            best = _best_label_for_action(game, player, action, candidates)
        text = f"{idx}. {_short_action(action)} {best}".strip()
        # Actionable rows represent real choices now. Make them visually stand
        # out from informational scan rows: green + bold whenever ACTIONABLE is
        # not None.
        _blit(bold, _fit_text(text, 64), x, y, COLORS["GREEN"])
        y += line_h
    return y


# ──────────────────────────────────────────────────────────────────────────────
# Strategic-direction formatting
# ──────────────────────────────────────────────────────────────────────────────


def _strategy_direction(player: Any) -> Mapping[str, Any]:
    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping) and direction:
        return direction
    last_direction = getattr(player, "last_strategic_direction", None)
    if isinstance(last_direction, Mapping) and last_direction:
        return last_direction
    return {}


def _way_id(direction: Mapping[str, Any]) -> Any:
    if not isinstance(direction, Mapping):
        return "-"
    return direction.get("preferred_way_id", direction.get("way_id", "-"))


def _strategy_tags(direction: Mapping[str, Any]) -> List[str]:
    """Return compact Way tags only.

    Tags describe the Way itself, not the route/board mechanics.  Therefore
    Port and Road are filtered out, while LR is kept because Longest Road is a
    victory objective.  LA/VP do not show the development-card count in
    brackets; those counts are confusing once the player is part-way there.
    """
    if not isinstance(direction, Mapping):
        return []

    raw_tags = list(direction.get("tags", []) or [])
    summary = direction.get("strategy_summary", {}) if isinstance(direction.get("strategy_summary", {}), Mapping) else {}
    remaining = direction.get("remaining", {}) if isinstance(direction.get("remaining", {}), Mapping) else {}

    out: List[str] = []
    for raw in raw_tags:
        tag = _normalise_way_tag(raw)
        if tag:
            _add_or_replace_tag(out, tag)

    # Some planner versions may not provide clean tags. Build conservative tags
    # from strategy_summary/remaining, but do not use Road or Port as strategy tags.
    if _truthy(summary.get("largest_army")) or _positive_from(summary, ("largest_army",)):
        _add_or_replace_tag(out, "LA")
    if _truthy(summary.get("longest_road")):
        _add_or_replace_tag(out, "LR")

    for label, keys in (
        ("City", ("cities", "city_upgrades", "cities_to_build", "remaining_city_upgrades", "remaining_cities_to_upgrade")),
        ("Settle", ("settlements", "new_settlements", "settlements_to_build", "remaining_new_settlements", "remaining_settlements_to_build")),
        ("VP", ("victory_points", "vp_cards", "victory_point_cards", "remaining_vp_cards")),
        ("DC", ("development_cards_to_buy", "dev_cards_to_buy", "dcards_to_buy", "remaining_dev_cards_to_buy")),
    ):
        value = _positive_from(summary, keys)
        if value <= 0:
            value = _positive_from(remaining, keys)
        if value > 0:
            # Do not add generic DC when the Way already explains the DC purpose
            # via LA or VP.
            if label == "DC" and ("LA" in out or any(_tag_root(t) == "VP" for t in out)):
                continue
            _add_or_replace_tag(out, f"{value} {label}")

    return _sort_way_tags(out)[:5]


def _normalise_way_tag(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    # Drop explanatory bracket text such as "(6 DC)" or "(10 DC)".
    main = text.split("(", 1)[0].strip()
    lower = main.lower().replace("_", " ").replace("-", " ")
    lower = " ".join(lower.split())
    if not lower:
        return ""

    # Not Way tags; these are target/path details.
    if lower in {"port", "ports", "harbor", "harbour", "road", "roads"}:
        return ""
    if lower.startswith(("port ", "ports ", "road ", "roads ")):
        return ""

    if lower in {"la", "largest army", "largestarmy"}:
        return "LA"
    if lower in {"lr", "longest road", "longestroad"}:
        return "LR"

    words = lower.split()
    first = words[0] if words else lower
    second = words[1] if len(words) > 1 else ""

    # Accept both "3 City" and "City 3" styles, with singular display.
    if first.isdigit() and second:
        num = int(first)
        root = _word_to_way_root(second)
        if root:
            return f"{num} {root}"

    root = _word_to_way_root(first)
    if root:
        num = _first_int_in_text(main)
        return f"{num} {root}" if num is not None else root

    if "victory point" in lower:
        num = _first_int_in_text(main)
        return f"{num} VP" if num is not None else "VP"

    # Avoid noisy long free-text tags.
    if len(main) > 14:
        return ""
    return main

def _word_to_way_root(word: str) -> str:
    word = str(word or "").strip().lower()
    if word in {"city", "cities"}:
        return "City"
    if word in {"settle", "settles", "settlement", "settlements"}:
        return "Settle"
    if word in {"vp", "vps", "victory"}:
        return "VP"
    if word in {"dc", "dcs", "dcard", "dcards", "dev", "development"}:
        return "DC"
    return ""


def _tag_root(tag: str) -> str:
    parts = str(tag or "").split()
    if not parts:
        return ""
    if parts[0].isdigit() and len(parts) > 1:
        return parts[1]
    return parts[0]


def _add_or_replace_tag(tags: List[str], tag: str) -> None:
    root = _tag_root(tag)
    if not root:
        return
    # LA and LR are unique objective tags. For numbered components, prefer the
    # newest/clearest count over a duplicated raw tag.
    for idx, existing in enumerate(list(tags)):
        if _tag_root(existing) == root:
            tags[idx] = tag
            return
    tags.append(tag)


def _sort_way_tags(tags: Sequence[str]) -> List[str]:
    priority = {"LA": 0, "LR": 1, "City": 2, "Settle": 3, "VP": 4, "DC": 5}
    return sorted(list(tags), key=lambda tag: (priority.get(_tag_root(tag), 99), list(tags).index(tag)))


def _is_strategy_locked_choice(choice: Any, blockers: Sequence[Any]) -> bool:
    if isinstance(choice, Mapping) and bool(choice.get("strategy_locked", False)):
        return True
    for blocker in blockers or []:
        text = str(blocker).lower()
        if "strategic lock" in text or "strategic priority" in text or "preferred support" in text:
            return True
    return False


def _strategy_needs_text(direction: Mapping[str, Any], needs: Sequence[Mapping[str, Any]]) -> str:
    immediate = [_short_action(str(n.get("action", ""))) for n in needs if isinstance(n, Mapping)]
    immediate = [x for x in immediate if x]

    if not immediate:
        support = _support_action_label(direction)
        if support:
            immediate = [support]

    if not immediate:
        return "None"

    immediate_unique = _unique_keep_order(immediate)
    later = _later_need_labels(direction, immediate_unique)
    text = " + ".join(immediate_unique)
    if later:
        text += " | Later: " + " + ".join(later)
    return text


def _later_need_labels(direction: Mapping[str, Any], immediate: Sequence[str]) -> List[str]:
    tags = _strategy_tags(direction)
    later: List[str] = []
    imm = set(immediate)

    # LA and VP usually imply later development-card buys unless DCard is already immediate.
    if (any(t == "LA" for t in tags) or any(t.startswith("VP ") for t in tags)) and "DCard" not in imm:
        later.append("DC")

    for tag in tags:
        root = tag.split()[0]
        label = {
            "City": "City",
            "Settle": "Settle",
            "VP": "DC",
            "DC": "DC",
        }.get(root, "")
        if label and label not in imm and label not in later:
            later.append(label)

    return later[:2]


def _support_action_label(direction: Mapping[str, Any]) -> str:
    support = str(direction.get("supporting_action_type", "") or "").strip()
    if not support:
        return ""
    return {
        "city_upgrade": "City",
        "build_city": "City",
        "next_settlement": "Settle",
        "new_settlement": "Road",
        "build_settlement": "Settle",
        "road": "Road",
        "build_road": "Road",
        "buy_dcard": "DCard",
        "buy_development_card": "DCard",
        "development_card": "DCard",
        "dcard": "DCard",
    }.get(support, _short_action(support))


def _strategy_target_text(game: Any, direction: Mapping[str, Any]) -> str:
    if not isinstance(direction, Mapping) or not direction:
        return ""
    support = str(direction.get("supporting_action_type", "") or "").strip()
    target = direction.get("supporting_action_target_id")

    if support:
        label = {
            "city_upgrade": "city_upgrade",
            "build_city": "city_upgrade",
            "next_settlement": "next_settle",
            "new_settlement": "new_settle",
            "build_settlement": "settle",
            "road": "road",
            "build_road": "road",
            "buy_dcard": "buy_dcard",
            "buy_development_card": "buy_dcard",
            "development_card": "buy_dcard",
            "dcard": "buy_dcard",
        }.get(support, support)
    else:
        label = "target"

    if label == "buy_dcard":
        return "buy_dcard"

    if target in (None, ""):
        # Road targets are sometimes stored only in roads_to_build.
        road = _first_road_from_direction(direction)
        if road:
            return f"road{_format_road_id(road)}"
        return label

    text = f"{label}@{target}"
    port = _target_port_suffix(game, target)
    if port:
        text += f" {port}"
    return text


def _first_road_from_direction(direction: Mapping[str, Any]) -> Any:
    for key in ("supporting_action_roads_to_build", "roads_to_build", "supporting_action_path"):
        values = direction.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
            first = values[0]
            if _road_key(first):
                return first
    return None


def _target_port_suffix(game: Any, target_id: Any) -> str:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    has_port = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
    return "(port)" if has_port else ""


def _strategy_risk_text(direction: Mapping[str, Any]) -> str:
    for key in ("action_risk_level", "risk_level", "road_risk_level"):
        value = str(direction.get(key, "") or "").strip()
        if value:
            return value
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Data extraction
# ──────────────────────────────────────────────────────────────────────────────


def _current_player(game: Any) -> Any:
    getter = getattr(game, "get_current_player", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    turn = _safe_int(getattr(game, "turn", 0))
    for player in list(getattr(game, "players", []) or []):
        if _safe_int(getattr(player, "id", 0)) == turn:
            return player
    return None


def _current_player_report(game: Any, player: Any) -> Dict[str, Any]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        return dict(report)

    scan = getattr(game, "current_viable_action_scan", None)
    if isinstance(scan, Mapping) and _same_player(scan.get("player_id"), player):
        return dict(scan)

    return {
        "player_id": getattr(player, "id", None),
        "player_color": getattr(player, "color", ""),
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "phase": getattr(game, "phase", ""),
        "state": getattr(game, "state", ""),
        "dice_value": getattr(game, "dice_roll", 0),
    }


def _current_player_choices(game: Any, player: Any) -> List[Mapping[str, Any]]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        values = report.get("buy_build_choices")
        if isinstance(values, list):
            return [dict(v) for v in values if isinstance(v, Mapping)]

    values = getattr(game, "current_execution_choices", []) or []
    if isinstance(values, list):
        return [dict(v) for v in values if isinstance(v, Mapping)]
    return []


def _current_player_needs(game: Any, player: Any) -> List[Mapping[str, Any]]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        values = report.get("strategic_needs")
        if isinstance(values, list):
            return [dict(v) for v in values if isinstance(v, Mapping)]

    values = getattr(game, "current_strategic_needs", []) or []
    if isinstance(values, list):
        return [dict(v) for v in values if isinstance(v, Mapping)]
    return []


def _hand_vector(player: Any) -> List[int]:
    method = getattr(player, "rcards_in_hand", None)
    if callable(method):
        try:
            values = method()
            # Some project versions return (hand_vector, trade_rates, trade_counts).
            if isinstance(values, (list, tuple)) and len(values) == 3 and isinstance(values[0], (list, tuple)):
                values = values[0]
            if isinstance(values, (list, tuple)) and len(values) >= 5:
                return [_safe_int(v) for v in list(values)[:5]]
        except Exception:
            pass

    cards = getattr(player, "rcards", {}) or {}
    out: List[int] = []
    for name in RESOURCE_NAMES:
        value = 0
        if isinstance(cards, Mapping):
            value = cards.get(name, cards.get(name.upper(), cards.get(name.lower(), 0)))
            if value == 0:
                for key, raw in cards.items():
                    key_name = str(getattr(key, "name", getattr(key, "value", key))).lower()
                    if key_name == name.lower():
                        value = raw
                        break
        out.append(_safe_int(value))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Best / target helpers
# ──────────────────────────────────────────────────────────────────────────────


def _best_now_or_wait(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> str:
    state = str(getattr(game, "state", "") or report.get("state", ""))
    forced = str(report.get("forced_action_mode", "") or "")
    if state == "AwaitingDiceRoll" or forced == "roll_dice":
        return "Roll dice first"
    if state in ROBBER_STATES or forced == "robber":
        return "Resolve robber / steal"

    canonical = _canonical_best_now_action(game)
    if canonical:
        text = str(canonical.get("best_now_text", "") or "").strip()
        if text:
            return text
        action = str(canonical.get("action", "") or "")
        best = str(canonical.get("best_now_label", "") or "")
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return f"{verb} {best}".strip()

    actionable = [row for row in choices if isinstance(row, Mapping) and bool(row.get("actionable"))]
    if actionable:
        actionable.sort(key=lambda row: _safe_int(row.get("priority", 99)))
        first = actionable[0]
        action = str(first.get("action", ""))
        candidates = list(first.get("candidates", []) or [])
        best = _best_label_for_action(game, player, action, candidates)
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return f"{verb} {best}".strip()

    target = _strategy_target_text(game, direction)
    if target:
        return f"Wait / Prio: {target}"
    return "No strategic buy/build action"



def _candidate_target_id(candidate: Mapping[str, Any]) -> Any:
    if not isinstance(candidate, Mapping):
        return None
    for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
        if key in candidate:
            return candidate.get(key)
    return None


def _pips_label(pips: float) -> str:
    try:
        value = float(pips or 0)
    except Exception:
        value = 0.0
    if value <= 0:
        return ""
    text = _format_number(value)
    return f"({text} pips)"

def _best_label_for_action(game: Any, player: Any, action: str, candidates: Sequence[Any]) -> str:
    if action == BUY_DCARD:
        stack = ""
        if candidates and isinstance(candidates[0], Mapping):
            count = candidates[0].get("dcards_stack_count")
            stack = f"stack {count}" if count not in (None, "") else "buy"
        return stack or "buy"

    if action in {BUILD_CITY, BUILD_SETTLEMENT}:
        candidate = _best_intersection_candidate(game, candidates)
        if not candidate:
            return ""
        target = _candidate_target_id(candidate)
        pips = _intersection_pips(game, target)
        port = _port_label(game, target)
        parts = [f"{target}"]
        pips_text = _pips_label(pips)
        if pips_text:
            parts.append(pips_text)
        if port:
            parts.append(port)
        return " ".join(parts)

    if action == BUILD_ROAD:
        road = _best_road_candidate(player, candidates)
        if not road:
            return ""
        road_id = road.get("road_id")
        return _format_road_id(road_id)

    if action == TWB:
        if candidates and isinstance(candidates[0], Mapping):
            candidate = candidates[0]
            give = str(candidate.get("give_resource", "") or "")
            get = str(candidate.get("get_resource", "") or "")
            rate = candidate.get("rate", "")
            if give and get and rate not in (None, ""):
                return f"{rate} {give}->{get}"
            if give and get:
                return f"{give}->{get}"
        return "trade"

    return ""


def _best_intersection_candidate(game: Any, candidates: Sequence[Any]) -> Dict[str, Any]:
    valid = [dict(c) for c in candidates if isinstance(c, Mapping)]
    if not valid:
        return {}
    return max(valid, key=lambda c: (_intersection_pips(game, _candidate_target_id(c)), -_safe_int(_candidate_target_id(c) or 9999)))


def _best_road_candidate(player: Any, candidates: Sequence[Any]) -> Dict[str, Any]:
    valid = [dict(c) for c in candidates if isinstance(c, Mapping)]
    if not valid:
        return {}

    outlook = getattr(player, "outlook", None)
    paths = list(getattr(outlook, "new_settlement_paths", []) or [])
    candidate_by_road = {_road_key(c.get("road_id")): c for c in valid if _road_key(c.get("road_id"))}

    for path in paths:
        if not isinstance(path, Mapping):
            continue
        for road in list(path.get("roads_to_build", []) or []):
            key = _road_key(road)
            if key in candidate_by_road:
                return candidate_by_road[key]

    return valid[0]


def _intersection_pips(game: Any, target_id: Any) -> float:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return 0.0
    if inter is None:
        return 0.0

    for attr in ("all_tile_pips", "three_tile_pips"):
        values = getattr(inter, attr, None)
        if isinstance(values, (list, tuple)):
            try:
                return float(sum(float(v or 0) for v in values))
            except Exception:
                pass
    return 0.0


def _port_label(game: Any, target_id: Any) -> str:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    if not bool(getattr(inter, "port_tf", False)) and str(getattr(inter, "portYN", "N")) != "Y":
        return ""
    port = str(getattr(inter, "port_type", "") or "").strip()
    return "" if port.lower() in {"", "blank"} else port.replace("Wool", "Sheep")


# ──────────────────────────────────────────────────────────────────────────────
# Text/render helpers
# ──────────────────────────────────────────────────────────────────────────────


def _section_title(font: Any, text: str, x: int, y: int) -> None:
    _blit(font, text, x, y, COLORS["BLACK"])


def _blit(font: Any, text: str, x: int, y: int, color: Optional[Tuple[int, int, int]] = None) -> None:
    surface = font.render(str(text), True, color or COLORS["BLACK"])
    WIN.blit(surface, (int(x), int(y)))


def _update(panel: pygame.Rect) -> None:
    try:
        pygame.display.update(panel)
    except Exception:
        pygame.display.update()


def _short_action(action: str) -> str:
    return {
        BUILD_CITY: "City",
        BUILD_SETTLEMENT: "Settle",
        BUILD_ROAD: "Road",
        BUY_DCARD: "DCard",
        TWB: "TwB",
    }.get(str(action), str(action))


def _short_blocker(blockers: Sequence[Any]) -> str:
    if not blockers:
        return ""
    text = str(blockers[0])
    replacements = {
        "Missing resources:": "Missing",
        "No legal settlement target currently reachable": "no legal target",
        "No legal road target currently connected to player network": "no legal road",
        "Strategic lock: preferred support is Build city": "skip: preferred City",
        "Strategic lock: preferred support is Build settlement": "skip: preferred Settle",
        "Strategic lock: preferred support is Build road": "skip: preferred Road",
        "Strategic lock: preferred support is Buy development_card": "skip: preferred DCard",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return _fit_text(text, 38)


def _dice_text(game: Any, report: Mapping[str, Any]) -> str:
    value = getattr(game, "dice_roll", None)
    if value in (None, "", [], 0):
        value = report.get("dice_value", "-")
    if isinstance(value, (list, tuple)):
        try:
            return str(sum(int(v) for v in value))
        except Exception:
            return str(value)
    return str(value if value not in (None, "") else "-")


def _same_player(value: Any, player: Any) -> bool:
    return _safe_int(value) == _safe_int(getattr(player, "id", 0))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _first_int_in_text(text: str) -> Optional[int]:
    digits = ""
    for ch in str(text):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def _positive_from(mapping: Mapping[str, Any], keys: Iterable[str]) -> int:
    if not isinstance(mapping, Mapping):
        return 0
    for key in keys:
        value = _safe_int(mapping.get(key, 0))
        if value > 0:
            return value
    return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _unique_keep_order(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _format_number(value: float) -> str:
    if abs(value - int(value)) < 0.0001:
        return str(int(value))
    return f"{value:.1f}"


def _road_key(road_id: Any) -> Tuple[int, int]:
    try:
        a, b = list(road_id)[:2]
        return tuple(sorted((int(a), int(b))))  # type: ignore[return-value]
    except Exception:
        return ()


def _format_road_id(road_id: Any) -> str:
    key = _road_key(road_id)
    if not key:
        return ""
    return f"[{key[0]},{key[1]}]"


def _fit_text(text: str, max_chars: int = 58) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


__all__ = ["draw_execution_debug_panel"]
