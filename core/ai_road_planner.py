"""core/ai_road_planner.py

Strategy-aware AI road planner.

This module is the Step-2 home for road intelligence.  It does not mutate game
state.  It combines:
- outlook/path discovery from core.outlook_logic;
- conservative risk checks from core.risk_assessment;
- optional Expected-Hand timing from core.resource_time_estimator;
- current player strategic_direction / last_strategic_direction.

Game.py should only ask this module: "is a Build-road candidate strategically
allowed, and which legal road should be executed?"
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from core.outlook_logic import (
        _normalise_road_key,
        candidate_road_set,
        find_reachable_new_settlement_paths,
        future_settlement_target_is_open,
        player_owned_road_keys,
        route_path_is_clear_for_player,
    )
except Exception:  # pragma: no cover - editor/import fallback
    def _normalise_road_key(road: Any) -> Tuple[int, int]:  # type: ignore[misc]
        try:
            a, b = list(road)[:2]
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return ()  # type: ignore[return-value]

    def candidate_road_set(*_: Any, **__: Any) -> set[Tuple[int, int]]:
        return set()

    def find_reachable_new_settlement_paths(*_: Any, **__: Any) -> List[Dict[str, Any]]:
        return []

    def future_settlement_target_is_open(*_: Any, **__: Any) -> bool:
        return False

    def player_owned_road_keys(*_: Any, **__: Any) -> set[Tuple[int, int]]:
        return set()

    def route_path_is_clear_for_player(*_: Any, **__: Any) -> bool:
        return False

try:
    from core.risk_assessment import assess_new_settlement_path_risk
except Exception:  # pragma: no cover
    def assess_new_settlement_path_risk(*_: Any, **__: Any) -> Dict[str, Any]:
        return {"risk_level": "low", "risk_score": 0.0, "risk_class": 0, "reasons": []}

try:
    from core.resource_time_estimator import estimate_new_settlement_target
except Exception:  # pragma: no cover - optional timing layer
    estimate_new_settlement_target = None  # type: ignore[assignment]


BUILD_ROAD = "Build road"
MAX_AI_SETTLEMENT_ROAD_DISTANCE = 3


def execution_player_is_human(game: Any, player: Any) -> bool:
    """Return True when player should be treated as human in Execution."""
    if player is None:
        return False
    try:
        if bool(getattr(player, "is_human", False)):
            return True
    except Exception:
        pass
    try:
        human_player = bool(getattr(game, "HUMAN_PLAYER", False))
    except Exception:
        human_player = False
    # Most versions use core.constants.HUMAN_PLAYER rather than game.HUMAN_PLAYER.
    try:
        from core.constants import HUMAN_PLAYER  # type: ignore
        human_player = bool(HUMAN_PLAYER)
    except Exception:
        pass
    if not human_player:
        return False
    try:
        if hasattr(game, "_normalised_human_player_ids_for_execution"):
            return int(getattr(player, "id", 0) or 0) in game._normalised_human_player_ids_for_execution()
    except Exception:
        pass
    try:
        from core.constants import HP_ID  # type: ignore
        raw = HP_ID if isinstance(HP_ID, (list, tuple, set)) else [HP_ID]
        return int(getattr(player, "id", 0) or 0) in {int(x) for x in raw}
    except Exception:
        return False


def ai_road_longest_road_exception_active(game: Any, player: Any) -> bool:
    """Placeholder for the later Longest Road exception.

    Current version deliberately returns False.  Non-settlement LR road building
    can later be enabled here without weakening the settlement-path guard.
    """
    return False


def ai_road_guard_applies(game: Any, player: Any) -> bool:
    """Return True when settlement-route road filtering should protect player."""
    if player is None:
        return False
    if execution_player_is_human(game, player):
        return False
    if ai_road_longest_road_exception_active(game, player):
        return False
    return True


def _as_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _road_key_from_any(road: Any) -> Tuple[int, int]:
    return _normalise_road_key(road)


def _route_roads_from_value(value: Any) -> List[Tuple[int, int]]:
    """Extract road keys from mixed planner fields."""
    roads: List[Tuple[int, int]] = []

    def add_road(raw: Any) -> None:
        key = _road_key_from_any(raw)
        if key and key not in roads:
            roads.append(key)

    if isinstance(value, Mapping):
        for road_key in ("road_id", "road", "edge", "target_road", "road_to_build"):
            if road_key in value:
                add_road(value.get(road_key))
        for nested_key in (
            "roads_to_build",
            "supporting_action_roads_to_build",
            "supporting_action_path",
            "path",
            "road_path",
            "route_roads",
            "new_settlement_roads_to_build",
        ):
            if nested_key in value:
                for nested in _route_roads_from_value(value.get(nested_key)):
                    add_road(nested)
        return roads

    if isinstance(value, (list, tuple)):
        # Single road pair: [15, 16]
        if len(value) == 2 and all(not isinstance(x, (list, tuple, dict)) for x in value):
            add_road(value)
            return roads
        # Node path: [15, 16, 42]
        if len(value) >= 3 and all(not isinstance(x, (list, tuple, dict)) for x in value):
            nodes = list(value)
            for a, b in zip(nodes, nodes[1:]):
                add_road((a, b))
            return roads
        # List of road pairs or nested dicts.
        for item in value:
            for nested in _route_roads_from_value(item):
                add_road(nested)
    return roads


def _normalise_supporting_action_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "city": "city_upgrade",
        "build_city": "city_upgrade",
        "city_upgrade": "city_upgrade",
        "upgrade_city": "city_upgrade",
        "next_settlement": "next_settlement",
        "next_settle": "next_settlement",
        "build_next_settlement": "next_settlement",
        "new_settlement": "new_settlement",
        "new_settle": "new_settlement",
        "build_new_settlement": "new_settlement",
        "settlement": "build_settlement",
        "settle": "build_settlement",
        "build_settlement": "build_settlement",
        "road": "build_road",
        "build_road": "build_road",
        "dcard": "buy_dcard",
        "development_card": "buy_dcard",
        "buy_dcard": "buy_dcard",
    }
    return aliases.get(text, text)


def _current_player_strategic_direction(player: Any) -> Dict[str, Any]:
    """Return strategic_direction or last_strategic_direction as a plain dict."""
    if player is None:
        return {}
    for attr in ("strategic_direction", "last_strategic_direction"):
        value = getattr(player, attr, None)
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _target_from_direction(direction: Mapping[str, Any]) -> Optional[int]:
    for key in (
        "settlement_target_id",
        "new_settlement_target_id",
        "next_settlement_target_id",
        "target_settlement_id",
        "target_id",
        "intersection_id",
        "target",
        "location",
    ):
        if key in direction:
            target = _as_int(direction.get(key))
            if target is not None:
                return target

    # Parse labels like "new_settlement@49".
    for key in ("target_label", "label", "supporting_action", "best_now_label"):
        text = str(direction.get(key, "") or "")
        if "@" in text:
            maybe = _as_int(text.split("@")[-1].strip())
            if maybe is not None:
                return maybe
    return None


def strategy_new_settlement_route_plan(game: Any, player: Any) -> Dict[str, Any]:
    """Return strategy-approved new-settlement target/route metadata.

    This function only identifies the strategy target.  It does not choose the
    final road; outlook/risk/timing layers do that afterwards.
    """
    direction = _current_player_strategic_direction(player)
    if not direction:
        return {}

    support = ""
    for key in (
        "supporting_action_type",
        "supporting_action",
        "preferred_action_type",
        "preferred_action",
        "action_type",
        "action",
        "target_type",
    ):
        if key in direction:
            support = _normalise_supporting_action_type(direction.get(key))
            if support:
                break

    target = _target_from_direction(direction)
    roads = _route_roads_from_value(direction)

    kind = ""
    if support == "new_settlement":
        kind = "new_settlement"
    elif support in {"next_settlement", "build_settlement"}:
        kind = "next_settlement"
    elif roads and target is not None:
        # Strategy supplied a target + road path, so this is a road-supported new settlement.
        kind = "new_settlement"

    # Conservative: do not infer a generic new settlement if strategy only says
    # "Build road" without a settlement target.  That is exactly the random-road
    # behavior we are trying to prevent.
    if kind != "new_settlement" or target is None:
        return {}

    return {
        "kind": "new_settlement",
        "target_settlement_id": int(target),
        "roads_to_build": list(roads),
        "target_label": f"new_settle@{int(target)}",
        "supporting_action_type": support or "new_settlement",
        "direction": direction,
    }


def _candidate_target_id(candidate: Mapping[str, Any]) -> Optional[int]:
    for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
        if key in candidate:
            value = _as_int(candidate.get(key))
            if value is not None:
                return value
    return None


def _candidate_pips(game: Any, target_id: int) -> float:
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
    total = 0.0
    try:
        for tile, _corner in game.board.intersection_to_corners.get(int(target_id), []) or []:
            for attr in ("pips", "pip", "production_pips"):
                value = getattr(tile, attr, None)
                if value not in (None, ""):
                    total += float(value)
                    break
    except Exception:
        pass
    return total


def _target_port_bonus(game: Any, target_id: int) -> float:
    try:
        inter = game.board.intersections[int(target_id)]
        port_tf = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
        if not port_tf:
            return 0.0
        port_type = str(getattr(inter, "port_type", "") or "").strip().lower()
        if port_type in {"", "blank", "none"}:
            return 0.0
        if port_type in {"3:1", "three", "any", "general"}:
            return 8.0
        return 5.0
    except Exception:
        return 0.0


def _expected_hand_timing_bonus(game: Any, player: Any, target_id: int, roads_to_build: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """Return optional EH timing metadata and a score adjustment.

    If resource_time_estimator is unavailable, this quietly returns neutral
    timing.  This keeps the road planner independent enough for tests while still
    using EH timing in the real v033 project.
    """
    if estimate_new_settlement_target is None:
        return {"timing_score_adjustment": 0.0, "expected_turns": None, "timing_found": None}
    try:
        estimate = estimate_new_settlement_target(
            board=getattr(game, "board", None),
            player=player,
            settlement_id=int(target_id),
            roads_to_build=list(roads_to_build or []),
            current_turn=getattr(game, "turn", None),
            target_player_id=getattr(player, "id", None),
            num_players=len(list(getattr(game, "players", []) or [])) or 4,
        )
    except Exception:
        return {"timing_score_adjustment": 0.0, "expected_turns": None, "timing_found": None}

    try:
        turns = float(estimate.get("expected_turns", estimate.get("turns", 9999.0)) or 9999.0)
    except Exception:
        turns = 9999.0
    found = bool(estimate.get("found", turns < 9999.0))
    if not found or turns >= 9999.0:
        adjustment = -35.0
    else:
        adjustment = -min(40.0, turns * 2.0)
    return {
        "timing_score_adjustment": adjustment,
        "expected_turns": round(turns, 3) if turns < 9999.0 else 9999.0,
        "timing_found": found,
        "eh_estimate": estimate,
    }


def score_new_settlement_road_path(game: Any, player: Any, path: Mapping[str, Any]) -> Dict[str, Any]:
    """Score one reachable path toward a strategy-approved new settlement."""
    target_id = _as_int(path.get("target_settlement_id"))
    if target_id is None:
        return dict(path) | {"route_score": float("-inf"), "blocked": True, "reason": "invalid target"}

    roads_to_build = [_road_key_from_any(r) for r in list(path.get("roads_to_build", []) or [])]
    roads_to_build = [r for r in roads_to_build if r]
    all_roads = [_road_key_from_any(r) for r in list(path.get("route_all_roads", roads_to_build) or [])]
    all_roads = [r for r in all_roads if r]

    risk = assess_new_settlement_path_risk(game, player, target_id, all_roads or roads_to_build)
    if str(risk.get("risk_level", "")) == "blocked":
        return dict(path) | {
            "route_score": float("-inf"),
            "blocked": True,
            "risk": risk,
            "reason": "; ".join(list(risk.get("reasons", []) or [])) or "path blocked",
        }

    timing = _expected_hand_timing_bonus(game, player, target_id, roads_to_build)
    pips = _candidate_pips(game, target_id)
    port_bonus = _target_port_bonus(game, target_id)
    distance_penalty = 10.0 * max(1, len(roads_to_build))
    risk_penalty = float(risk.get("risk_score", 0.0) or 0.0)
    timing_adjustment = float(timing.get("timing_score_adjustment", 0.0) or 0.0)

    score = (pips * 6.0) + port_bonus - distance_penalty - risk_penalty + timing_adjustment
    reasons = [
        f"target pips={round(pips, 2)}",
        f"roads_to_build={len(roads_to_build)}",
        f"risk={risk.get('risk_level', 'low')}",
    ]
    if timing.get("expected_turns") not in (None, ""):
        reasons.append(f"EH turns={timing.get('expected_turns')}")

    out = dict(path)
    out.update({
        "kind": "new_settlement",
        "target_settlement_id": target_id,
        "roads_to_build": roads_to_build,
        "route_all_roads": all_roads or roads_to_build,
        "next_road": roads_to_build[0] if roads_to_build else None,
        "target_label": f"new_settle@{target_id}",
        "route_score": round(float(score), 3),
        "route_risk": risk.get("risk_class", 0),
        "risk": risk,
        "timing": timing,
        "strategy_reason": "; ".join(reasons),
        "blocked": False,
    })
    return out


def build_ai_road_plan(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return the best validated road plan for an AI player.

    Empty dict means: do not build a road now.
    """
    if not ai_road_guard_applies(game, player):
        return {}

    strategy_plan = strategy_new_settlement_route_plan(game, player)
    if not strategy_plan:
        return {}

    target_id = _as_int(strategy_plan.get("target_settlement_id"))
    if target_id is None:
        return {}
    if not future_settlement_target_is_open(game, player, target_id):
        return {}

    legal_candidates = [dict(c) for c in list(candidates or []) if isinstance(c, Mapping)]
    legal_roads = candidate_road_set(legal_candidates)
    owned = player_owned_road_keys(game, player)

    # First honour explicit route supplied by strategy_timing/action_planner, but validate it here.
    raw_roads = [_road_key_from_any(r) for r in list(strategy_plan.get("roads_to_build", []) or [])]
    raw_roads = [r for r in raw_roads if r]
    if raw_roads:
        roads_to_build = [r for r in raw_roads if r not in owned]
        if roads_to_build and len(roads_to_build) <= MAX_AI_SETTLEMENT_ROAD_DISTANCE:
            first_road = roads_to_build[0]
            if (not legal_roads or first_road in legal_roads) and route_path_is_clear_for_player(game, player, raw_roads, target_id):
                scored = score_new_settlement_road_path(
                    game,
                    player,
                    dict(strategy_plan) | {
                        "route_all_roads": raw_roads,
                        "roads_to_build": roads_to_build,
                        "next_road": first_road,
                        "route_source": "strategy_direction_explicit_route",
                    },
                )
                if not scored.get("blocked"):
                    return scored

    # If strategy only supplies the settlement target, let outlook_logic discover short paths.
    paths = find_reachable_new_settlement_paths(
        game,
        player,
        target_ids=[target_id],
        max_distance=MAX_AI_SETTLEMENT_ROAD_DISTANCE,
        legal_road_candidates=legal_candidates,
    )
    scored_paths = [score_new_settlement_road_path(game, player, path) for path in paths]
    scored_paths = [p for p in scored_paths if not p.get("blocked") and p.get("roads_to_build")]
    if not scored_paths:
        return {}
    scored_paths.sort(key=lambda p: (float(p.get("route_score", float("-inf"))), -int(p.get("roads_remaining", 99))), reverse=True)
    best = dict(scored_paths[0])
    best["route_source"] = best.get("route_source") or "outlook_logic_discovered_route"
    return best


def choose_best_ai_road_candidate(
    game: Any,
    player: Any,
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return the concrete scanner candidate matching the planned next road."""
    plan = build_ai_road_plan(game, player, candidates)
    if not plan:
        return {}
    next_road = _road_key_from_any(plan.get("next_road") or (list(plan.get("roads_to_build", []) or [None])[0]))
    if not next_road:
        return {}
    for candidate in list(candidates or []):
        if not isinstance(candidate, Mapping):
            continue
        if _road_key_from_any(candidate) == next_road:
            out = dict(candidate)
            out["route_step"] = 1
            out["route_steps_total"] = len(list(plan.get("roads_to_build", []) or []))
            out["route_target_id"] = plan.get("target_settlement_id")
            out["route_target_label"] = plan.get("target_label")
            out["route_score"] = plan.get("route_score")
            out["route_risk"] = plan.get("route_risk")
            out["strategic_reason"] = plan.get("strategy_reason")
            out["ai_road_plan"] = plan
            return out
    return {}


def should_suppress_ai_strategic_road_choice(
    game: Any,
    choice: Mapping[str, Any],
    *,
    player: Optional[Any] = None,
) -> bool:
    """Return True when a Build-road choice has no valid settlement route."""
    if not isinstance(choice, Mapping):
        return False
    if str(choice.get("action", "") or "") != BUILD_ROAD:
        return False
    player = player if player is not None else getattr(game, "get_current_player", lambda: None)()
    if not ai_road_guard_applies(game, player):
        return False
    candidates = [dict(c) for c in list(choice.get("candidates", []) or []) if isinstance(c, Mapping)]
    return not bool(build_ai_road_plan(game, player, candidates))


def road_allowed_for_ai(game: Any, player: Any, road: Any) -> bool:
    """Last-moment execution guard for stale road plan items."""
    if not ai_road_guard_applies(game, player):
        return True
    wanted = _road_key_from_any(road)
    if not wanted:
        return False
    plan = build_ai_road_plan(game, player, [{"road_id": list(wanted)}])
    if not plan:
        return False
    next_road = _road_key_from_any(plan.get("next_road") or (list(plan.get("roads_to_build", []) or [None])[0]))
    return bool(next_road and next_road == wanted)


def ai_road_block_reason(game: Any, player: Any, candidates: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
    """Return a short explanation when a legal AI road is suppressed."""
    if player is None:
        return "AI road guard: no current player."
    strategy_plan = strategy_new_settlement_route_plan(game, player)
    if not strategy_plan:
        return "AI road guard: no strategy-approved new-settlement target; do not build a generic legal road."
    target = _as_int(strategy_plan.get("target_settlement_id"))
    if target is None:
        return "AI road guard: new-settlement strategy has no target intersection."
    if not future_settlement_target_is_open(game, player, target):
        return f"AI road guard: target new_settle@{target} is no longer buildable/open."
    plan = build_ai_road_plan(game, player, candidates)
    if not plan:
        return f"AI road guard: no legal low-risk next road matches the strategy route to new_settle@{target}."
    return "AI road guard: route is allowed."
