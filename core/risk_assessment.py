"""core/risk_assessment.py

Small, conservative risk helpers for AI road/new-settlement planning.

This module deliberately does not execute game actions.  It answers questions
such as: can an opponent block this path, touch this target, or race us to the
same new-settlement spot?
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from core.outlook_logic import (
        _normalise_road_key,
        board_road_map,
        future_settlement_target_is_open,
        intersection_has_opponent_structure,
        road_is_empty_or_owned_by_player,
    )
except Exception:  # pragma: no cover - editor/test fallback
    def _normalise_road_key(road: Any) -> Tuple[int, int]:  # type: ignore[misc]
        try:
            a, b = list(road)[:2]
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return ()  # type: ignore[return-value]

    def board_road_map(board: Any) -> Dict[Tuple[int, int], Any]:
        return {}

    def future_settlement_target_is_open(*_: Any, **__: Any) -> bool:
        return False

    def intersection_has_opponent_structure(*_: Any, **__: Any) -> bool:
        return False

    def road_is_empty_or_owned_by_player(*_: Any, **__: Any) -> bool:
        return False


RiskTuple = Tuple[str, float]


def _player_colors(player: Any) -> set[str]:
    colors = {str(getattr(player, "color", ""))}
    color2 = getattr(player, "color2", None)
    if color2:
        colors.add(str(color2))
    return colors


def _target_neighbors(game: Any, target_id: int) -> set[int]:
    try:
        inter = game.board.intersections[int(target_id)]
        return {int(x) for x in list(getattr(inter, "three_intersection_ids", []) or [])}
    except Exception:
        return set()


def opponent_settlement_race_risk(game: Any, player: Any, target_id: int) -> Dict[str, Any]:
    """Return a conservative opponent-race assessment for a target.

    This is intentionally cheap for Version 1.  Later it can call the full
    Expected-Hand estimator for each opponent.  Current logic catches the most
    important board risks:
    - opponent already has a road touching the target;
    - opponent has a road one edge away from the target;
    - target is no longer open/buildable.
    """
    reasons: List[str] = []
    try:
        target = int(target_id)
    except Exception:
        return {"risk_level": "blocked", "risk_score": 99.0, "risk_class": 3, "reasons": ["invalid target"]}

    if not future_settlement_target_is_open(game, player, target):
        return {
            "risk_level": "blocked",
            "risk_score": 99.0,
            "risk_class": 3,
            "opponent_can_block": True,
            "opponent_can_settle_first": True,
            "contested_by": [],
            "reasons": [f"target new_settle@{target} is not open/buildable"],
        }

    own_colors = _player_colors(player)
    target_neighbors = _target_neighbors(game, target)
    contested_by: set[str] = set()
    risk_class = 0

    try:
        for road in list(getattr(game.board, "roads", []) or []):
            road_key = _normalise_road_key(getattr(road, "id", None))
            if not road_key or not bool(getattr(road, "occupied_tf", False)):
                continue
            color = str(getattr(road, "color", ""))
            if color in own_colors:
                continue
            if target in road_key:
                contested_by.add(color)
                risk_class = max(risk_class, 2)
                reasons.append(f"opponent road {road_key} already touches target")
                continue
            if any(endpoint in target_neighbors for endpoint in road_key):
                contested_by.add(color)
                risk_class = max(risk_class, 1)
                reasons.append(f"opponent road {road_key} is near target")
    except Exception:
        pass

    risk_level = "low"
    risk_score = 0.0
    if risk_class == 1:
        risk_level = "medium"
        risk_score = 20.0
    elif risk_class >= 2:
        risk_level = "high"
        risk_score = 45.0

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "risk_class": risk_class,
        "opponent_can_block": risk_class >= 1,
        "opponent_can_settle_first": risk_class >= 2,
        "contested_by": sorted(contested_by),
        "reasons": reasons or ["no nearby opponent road pressure detected"],
    }


def assess_new_settlement_path_risk(game: Any, player: Any, target_id: int, path_roads: Sequence[Any]) -> Dict[str, Any]:
    """Assess risk for one path toward a new-settlement target."""
    reasons: List[str] = []
    try:
        target = int(target_id)
    except Exception:
        return {"risk_level": "blocked", "risk_score": 99.0, "risk_class": 3, "reasons": ["invalid target"]}

    # Hard block if any road is unavailable or any intermediate node is blocked.
    normalized_roads: List[Tuple[int, int]] = []
    for raw in list(path_roads or []):
        key = _normalise_road_key(raw)
        if not key:
            return {"risk_level": "blocked", "risk_score": 99.0, "risk_class": 3, "reasons": ["invalid road in path"]}
        normalized_roads.append(key)
        if not road_is_empty_or_owned_by_player(game, player, key):
            return {
                "risk_level": "blocked",
                "risk_score": 99.0,
                "risk_class": 3,
                "opponent_can_block": True,
                "opponent_can_settle_first": False,
                "contested_by": [],
                "reasons": [f"road {key} is already occupied by another player"],
            }
        for endpoint in key:
            if int(endpoint) == target:
                continue
            if intersection_has_opponent_structure(game, player, int(endpoint)):
                return {
                    "risk_level": "blocked",
                    "risk_score": 99.0,
                    "risk_class": 3,
                    "opponent_can_block": True,
                    "opponent_can_settle_first": False,
                    "contested_by": [],
                    "reasons": [f"opponent structure blocks intermediate intersection {endpoint}"],
                }

    race = opponent_settlement_race_risk(game, player, target)
    reasons.extend(list(race.get("reasons", []) or []))

    # One extra soft penalty for long/chokepoint-ish routes.
    length_penalty = max(0, len(normalized_roads) - 1) * 5.0
    risk_score = float(race.get("risk_score", 0.0) or 0.0) + length_penalty
    risk_class = int(race.get("risk_class", 0) or 0)
    if length_penalty >= 10.0 and risk_class < 2:
        risk_class = max(risk_class, 1)
        reasons.append("longer route has more blocking exposure")

    risk_level = "low"
    if risk_class == 1:
        risk_level = "medium"
    elif risk_class == 2:
        risk_level = "high"
    elif risk_class >= 3:
        risk_level = "blocked"

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "risk_class": risk_class,
        "opponent_can_block": bool(race.get("opponent_can_block", False)),
        "opponent_can_settle_first": bool(race.get("opponent_can_settle_first", False)),
        "contested_by": list(race.get("contested_by", []) or []),
        "reasons": reasons or ["path risk is low"],
    }
