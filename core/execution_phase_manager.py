"""core/execution_phase_manager.py

Slice A + Slice B execution-phase bridge for Catan.

This module is intentionally modest:

Slice A
    - call viable_action_scanner.scanning_viable_actions(...)
    - keep only the four buy/build action families for first execution debugging
    - store/print the viable buy/build choices

Slice B
    - read player.strategic_direction
    - translate the preferred supporting action into immediate action families
    - mark which viable buy/build choices are strategically actionable
    - keep broad strategy-summary/tags only as a fallback when no preferred
      supporting action is available

Important: this module does NOT execute builds/buys yet.
That belongs to Slice C, where Game should mutate the real state and revalidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from core.viable_action_scanner import (  # type: ignore
        BUY_DCARD,
        BUILD_CITY,
        BUILD_ROAD,
        BUILD_SETTLEMENT,
        scanning_viable_actions,
    )
except Exception:  # pragma: no cover - lets editors import this file standalone.
    BUY_DCARD = "Buy development_card"
    BUILD_CITY = "Build city"
    BUILD_SETTLEMENT = "Build settlement"
    BUILD_ROAD = "Build road"

    def scanning_viable_actions(*_: Any, **__: Any) -> Any:  # type: ignore
        raise ImportError("core.viable_action_scanner.scanning_viable_actions is required")


try:
    from core.player_trade import (  # type: ignore
        find_and_execute_best_ai_to_ai_trade,
        find_twp_proposals,
    )
except Exception:  # pragma: no cover - optional while TwP is being staged.
    find_and_execute_best_ai_to_ai_trade = None  # type: ignore[assignment]
    find_twp_proposals = None  # type: ignore[assignment]


# First baby execution scope.  TwP, TwB, and playing dcards are deliberately
# ignored here even if the scanner can detect them.
BUY_BUILD_ACTION_PRIORITY: Tuple[str, ...] = (
    BUILD_CITY,
    BUILD_SETTLEMENT,
    BUILD_ROAD,
    BUY_DCARD,
)


# Several report layers may use slightly different names.  Keep this tolerant so
# Slice B survives while Stage 4E / strategic_direction is still evolving.
_STRATEGIC_REMAINING_KEYS: Dict[str, Tuple[str, ...]] = {
    BUILD_CITY: (
        "remaining_city_upgrades",
        "remaining_cities_to_upgrade",
        "remaining_city_upgrades_to_build",
        "city_upgrades_remaining",
        "cities_to_upgrade_remaining",
    ),
    BUILD_SETTLEMENT: (
        "remaining_new_settlements",
        "remaining_settlements_to_build",
        "remaining_settlements",
        "new_settlements_remaining",
        "settlements_remaining",
    ),
    BUILD_ROAD: (
        "remaining_roads_to_build",
        "remaining_roads",
        "roads_to_build_remaining",
        "roads_remaining",
    ),
    BUY_DCARD: (
        "remaining_dev_cards_to_buy",
        "remaining_development_cards_to_buy",
        "remaining_dcards_to_buy",
        "development_cards_to_buy_remaining",
        "dcards_to_buy_remaining",
    ),
}

_STRATEGY_SUMMARY_KEYS: Dict[str, Tuple[str, ...]] = {
    BUILD_CITY: ("cities", "city_upgrades", "cities_to_build"),
    BUILD_SETTLEMENT: ("settlements", "new_settlements", "settlements_to_build"),
    BUILD_ROAD: ("roads", "roads_to_build"),
    BUY_DCARD: ("development_cards_to_buy", "dev_cards_to_buy", "dcards_to_buy"),
}

_SUPPORTING_ACTION_TO_EXECUTION_ACTIONS: Dict[str, Tuple[str, ...]] = {
    "city_upgrade": (BUILD_CITY,),
    "build_city": (BUILD_CITY,),
    "next_settlement": (BUILD_SETTLEMENT,),
    "new_settlement": (BUILD_SETTLEMENT, BUILD_ROAD),
    "build_settlement": (BUILD_SETTLEMENT,),
    "road": (BUILD_ROAD,),
    "build_road": (BUILD_ROAD,),
    "buy_dcard": (BUY_DCARD,),
    "buy_development_card": (BUY_DCARD,),
    "development_card": (BUY_DCARD,),
    "dcard": (BUY_DCARD,),
}


@dataclass
class StrategicNeed:
    """One action family requested by player.strategic_direction."""

    action: str
    source: str
    reason: str
    remaining_key: str = ""
    remaining_value: Optional[float] = None
    scan_viable: bool = False
    strategy_locked: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionChoice:
    """Slice A/B debug object for one buy/build action family."""

    action: str
    priority: int
    viable: bool
    strategic_needed: bool
    actionable: bool
    candidate_count: int
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    reason: str = ""
    strategic_reason: str = ""
    remaining_key: str = ""
    remaining_value: Optional[float] = None
    scan_viable: bool = False
    strategy_locked: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionPhaseManager:
    """Thin execution-phase orchestration layer for Slice A + Slice B.

    Ownership split:
        - Game mutates real state.
        - viable_action_scanner observes current legality.
        - ExecutionPhaseManager stores and filters scan results.

    This class deliberately does not call any build/buy mutation functions yet.
    """

    def __init__(self, game: Any, *, debug_print: Optional[bool] = None) -> None:
        self.game = game
        self.debug_print = bool(
            getattr(game, "execution_debug_print_tf", True)
            if debug_print is None
            else debug_print
        )

        self.last_scan: Any = None
        self.current_choices: List[ExecutionChoice] = []
        self.current_strategic_needs: List[Dict[str, Any]] = []
        self.current_actionable_choices: List[ExecutionChoice] = []
        self.last_report: Dict[str, Any] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Public API used by Game.refresh_viable_actions(...)
    # ──────────────────────────────────────────────────────────────────────

    def refresh_viable_actions(
        self,
        player: Optional[Any] = None,
        *,
        reason: str = "",
        include_candidates: bool = True,
        enforce_forced_action_lock: bool = True,
        allow_actions_before_roll: bool = False,
    ) -> Any:
        """Run the scanner and build Slice A/B execution-choice diagnostics."""

        player = self._resolve_player(player)

        scan = scanning_viable_actions(
            self.game,
            player,
            include_candidates=include_candidates,
            enforce_forced_action_lock=enforce_forced_action_lock,
            allow_actions_before_roll=allow_actions_before_roll,
        )

        self.last_scan = scan

        needs = action_families_from_player_strategic_direction(player)
        needs_by_action = {need.action: need for need in needs}

        self.current_choices = self._build_buy_build_choices(
            scan=scan,
            needs_by_action=needs_by_action,
        )
        self.current_strategic_needs = [need.as_dict() for need in needs]
        self.current_actionable_choices = [
            choice for choice in self.current_choices if choice.actionable
        ]

        self.last_report = self._build_report(
            scan=scan,
            player=player,
            reason=reason or str(getattr(self.game, "last_rescan_reason", "") or ""),
        )

        # Store directly on Game as a convenience for GUI/test/debug code.  Game
        # also mirrors these fields after this method returns; setting them here
        # keeps older callers working even when they call the manager directly.
        self._store_on_game()

        if self.debug_print:
            self.print_current_choices()

        return scan

    def buy_build_choices(self) -> List[Dict[str, Any]]:
        """Return all Slice-A buy/build choices as dictionaries."""
        return [choice.as_dict() for choice in self.current_choices]

    def actionable_choices(self) -> List[Dict[str, Any]]:
        """Return the Slice-B intersection: viable buy/build ∩ strategic needs."""
        return [choice.as_dict() for choice in self.current_actionable_choices]

    def player_trade_candidates(
        self,
        player: Optional[Any] = None,
        *,
        max_candidates: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return Version-1+ TwP candidates for the active player without mutating game."""
        if find_twp_proposals is None:
            return []
        resolved = self._resolve_player(player)
        return [
            proposal.as_dict()
            for proposal in find_twp_proposals(self.game, resolved, max_candidates=max_candidates)
        ]

    def auto_execute_ai_player_trade(
        self,
        player: Optional[Any] = None,
        *,
        max_candidates: int = 20,
    ) -> Dict[str, Any]:
        """Execute the best AI-vs-AI TwP deal when one is clearly acceptable."""
        if find_and_execute_best_ai_to_ai_trade is None:
            return {
                "accepted": False,
                "executed": False,
                "reason": "core.player_trade is unavailable",
            }
        resolved = self._resolve_player(player)
        decision = find_and_execute_best_ai_to_ai_trade(
            self.game,
            resolved,
            max_candidates=max_candidates,
        )
        return decision.as_dict()

    def print_current_choices(self) -> None:
        """Print compact Slice A/B diagnostics for terminal/debug runs."""

        scan = self.last_scan
        player_id = getattr(scan, "player_id", None)
        player_color = getattr(scan, "player_color", "")
        state = getattr(scan, "state", "")
        dice_value = getattr(scan, "dice_value", 0)
        forced = getattr(scan, "forced_action_mode", None)

        header = (
            f"[Slice A/B] P{player_id} {player_color} "
            f"state={state or '-'} dice={dice_value}"
        )
        if forced:
            header += f" forced={forced}"
        print(header)

        print("  Slice A viable buy/build:")
        for choice in self.current_choices:
            print(
                "   - "
                f"{choice.action}: {choice.viable} "
                f"candidates={choice.candidate_count}"
            )
            if not choice.viable and choice.blockers:
                print(f"     blocker: {choice.blockers[0]}")

        if self.current_strategic_needs:
            print("  Slice B strategic needs:")
            for need in self.current_strategic_needs:
                suffix = ""
                if need.get("remaining_key"):
                    suffix = f" ({need.get('remaining_key')}={need.get('remaining_value')})"
                print(f"   - {need.get('action')}{suffix}")
        else:
            print("  Slice B strategic needs: none found on player.strategic_direction")

        actionable = [choice.action for choice in self.current_actionable_choices]
        print(f"  Slice B actionable: {actionable if actionable else 'none'}")

    # ──────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_player(self, player: Optional[Any]) -> Optional[Any]:
        if player is not None:
            return player

        getter = getattr(self.game, "get_current_player", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass

        current = getattr(self.game, "current_player", None)
        if current is not None:
            return current

        turn = _safe_int_or_none(getattr(self.game, "turn", None))
        for candidate in list(getattr(self.game, "players", []) or []):
            if _safe_int_or_none(getattr(candidate, "id", None)) == turn:
                return candidate
        return None

    def _build_buy_build_choices(
        self,
        *,
        scan: Any,
        needs_by_action: Mapping[str, StrategicNeed],
    ) -> List[ExecutionChoice]:
        flags = dict(getattr(scan, "action_flags", {}) or {})
        candidates_by_action = dict(getattr(scan, "candidates", {}) or {})
        blockers_by_action = dict(getattr(scan, "blockers", {}) or {})

        strategic_lock_active = any(
            getattr(need, "source", "") == "supporting_action_type"
            for need in needs_by_action.values()
        )
        preferred_actions_text = ", ".join(
            action for action in BUY_BUILD_ACTION_PRIORITY if action in needs_by_action
        )

        choices: List[ExecutionChoice] = []
        for priority, action in enumerate(BUY_BUILD_ACTION_PRIORITY, start=1):
            scan_viable = bool(flags.get(action, False))
            candidates = _copy_dict_list(candidates_by_action.get(action, []) or [])
            blockers = [str(x) for x in list(blockers_by_action.get(action, []) or [])]
            need = needs_by_action.get(action)
            strategic_needed = need is not None
            strategy_locked = bool(strategic_lock_active and not strategic_needed)

            # In preferred-support mode, a legal action outside the preferred
            # supporting action is not executable as a strategic/actionable choice.
            # It is deliberately skipped, not invisible: scan_viable remains True
            # and strategy_locked=True lets Game emit a clear DBG line in the
            # Events/Twitter panel.
            viable = bool(scan_viable and not strategy_locked)
            actionable = bool(viable and strategic_needed)

            if strategy_locked and scan_viable:
                blockers = [
                    f"Strategic priority: preferred support is {preferred_actions_text or 'unknown'}"
                ] + blockers
                reason = (
                    "Legal in the raw scan, but deliberately skipped because "
                    "the current preferred supporting action points elsewhere."
                )
            elif actionable:
                reason = "Viable now and requested by player.strategic_direction."
            elif scan_viable and not strategic_needed:
                reason = "Viable now, but not requested by player.strategic_direction."
            elif strategic_needed and not scan_viable:
                reason = "Requested by player.strategic_direction, but not currently viable."
            else:
                reason = "Not currently viable and not requested by player.strategic_direction."

            choices.append(
                ExecutionChoice(
                    action=action,
                    priority=priority,
                    viable=viable,
                    strategic_needed=strategic_needed,
                    actionable=actionable,
                    candidate_count=len(candidates),
                    candidates=candidates,
                    blockers=blockers,
                    reason=reason,
                    strategic_reason=need.reason if need is not None else "",
                    remaining_key=need.remaining_key if need is not None else "",
                    remaining_value=need.remaining_value if need is not None else None,
                    scan_viable=scan_viable,
                    strategy_locked=strategy_locked,
                )
            )

        return choices

    def _build_report(self, *, scan: Any, player: Optional[Any], reason: str) -> Dict[str, Any]:
        return {
            "slice": "A+B",
            "reason": reason,
            "player_id": getattr(scan, "player_id", getattr(player, "id", None)),
            "player_color": getattr(scan, "player_color", getattr(player, "color", "")),
            "round": getattr(scan, "round_num", getattr(self.game, "round", None)),
            "turn": getattr(scan, "turn", getattr(self.game, "turn", None)),
            "phase": getattr(scan, "phase", getattr(self.game, "phase", "")),
            "state": getattr(scan, "state", getattr(self.game, "state", "")),
            "dice_value": getattr(scan, "dice_value", 0),
            "forced_action_mode": getattr(scan, "forced_action_mode", None),
            "scan_viable_actions": scan.viable_actions() if hasattr(scan, "viable_actions") else [],
            "strategic_needs": list(self.current_strategic_needs),
            "buy_build_choices": self.buy_build_choices(),
            "actionable": self.actionable_choices(),
            "chosen_action": None,
            "chosen_candidate": None,
            "success": None,
            "note": "Slice A/B only: no buy/build action is executed yet.",
        }

    def _store_on_game(self) -> None:
        try:
            self.game.current_execution_choices = self.buy_build_choices()
            self.game.current_strategic_needs = list(self.current_strategic_needs)
            self.game.current_actionable_choices = self.actionable_choices()
            self.game.last_execution_scan_report = dict(self.last_report)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Strategic-direction parsing
# ──────────────────────────────────────────────────────────────────────────────


def action_families_from_player_strategic_direction(player: Optional[Any]) -> List[StrategicNeed]:
    """Translate player.strategic_direction into immediate execution needs.

    Important Slice-C3 rule:
        When action_planner.py has persisted a preferred ``supporting_action_type``
        (for example ``city_upgrade``), that supporting action becomes the
        immediate strategic command.  Broad strategy-summary/tags remain useful
        fallback context, but they must not make unrelated legal actions
        actionable.

    This prevents this bad pattern:
        planner prefers city_upgrade, strategy text also mentions roads, scanner
        sees a legal road, and the AI incorrectly executes the road as
        "strategic".
    """

    if player is None:
        return []

    direction = getattr(player, "strategic_direction", None)
    if not isinstance(direction, Mapping) or not direction:
        return []

    # Preferred Stage-4E supporting action is the strongest signal and should
    # be interpreted first.  If present and recognized, return only those
    # immediate action families.
    preferred_needs = _preferred_supporting_action_needs(direction)
    if preferred_needs:
        return preferred_needs

    needs_by_action: Dict[str, StrategicNeed] = {}

    remaining = _mapping_or_empty(direction.get("remaining"))
    for action, keys in _STRATEGIC_REMAINING_KEYS.items():
        key, value = _first_positive_value(remaining, keys)
        if key:
            needs_by_action[action] = StrategicNeed(
                action=action,
                source="remaining",
                reason=f"strategic_direction.remaining.{key} is still positive",
                remaining_key=key,
                remaining_value=value,
            )

    # Fallback: strategy_summary often stores target counts, not remaining counts.
    # Compare against current player state where possible.
    strategy_summary = _mapping_or_empty(direction.get("strategy_summary"))
    _add_strategy_summary_needs(player, strategy_summary, needs_by_action)

    # Extra fallback for free-text/tags.  Keep this conservative and use it only
    # when there was no preferred supporting action.
    tags = [str(t).lower() for t in list(direction.get("tags", []) or [])]
    need_compact = str(direction.get("need_compact", "") or "").lower()
    reason = "strategic_direction tags/need_compact mention this family"
    if any("city" in t for t in tags) or "city" in need_compact:
        needs_by_action.setdefault(BUILD_CITY, StrategicNeed(BUILD_CITY, "tags", reason))
    if any("settlement" in t for t in tags) or "settlement" in need_compact:
        needs_by_action.setdefault(BUILD_SETTLEMENT, StrategicNeed(BUILD_SETTLEMENT, "tags", reason))
    if any("road" in t for t in tags) or "road" in need_compact:
        needs_by_action.setdefault(BUILD_ROAD, StrategicNeed(BUILD_ROAD, "tags", reason))
    if any("army" in t or "dcard" in t or "development" in t for t in tags):
        needs_by_action.setdefault(BUY_DCARD, StrategicNeed(BUY_DCARD, "tags", reason))
    if bool(strategy_summary.get("largest_army", False)):
        needs_by_action.setdefault(
            BUY_DCARD,
            StrategicNeed(
                BUY_DCARD,
                "strategy_summary",
                "strategy_summary.largest_army is true; buying dcards supports Largest Army",
            ),
        )

    return [needs_by_action[action] for action in BUY_BUILD_ACTION_PRIORITY if action in needs_by_action]


def _preferred_supporting_action_needs(direction: Mapping[str, Any]) -> List[StrategicNeed]:
    """Return strict immediate needs from preferred supporting_action_type."""

    supporting_action_type = str(direction.get("supporting_action_type", "") or "").strip()
    if not supporting_action_type:
        return []

    actions = _SUPPORTING_ACTION_TO_EXECUTION_ACTIONS.get(supporting_action_type, ())
    if not actions:
        return []

    target = direction.get("supporting_action_target_id")
    target_part = f" @{target}" if target not in (None, "") else ""
    reason = (
        f"preferred way_id is supported by action_type={supporting_action_type}{target_part}; "
        "strict preferred-support mode ignores broad strategy-summary/tags for immediate execution"
    )

    needs_by_action: Dict[str, StrategicNeed] = {}
    for action in actions:
        needs_by_action.setdefault(
            action,
            StrategicNeed(
                action=action,
                source="supporting_action_type",
                reason=reason,
            ),
        )

    return [needs_by_action[action] for action in BUY_BUILD_ACTION_PRIORITY if action in needs_by_action]

def _add_strategy_summary_needs(
    player: Any,
    strategy_summary: Mapping[str, Any],
    needs_by_action: Dict[str, StrategicNeed],
) -> None:
    if not strategy_summary:
        return

    current_cities = len(getattr(player, "cities", []) or [])
    current_settlements = len(getattr(player, "settlements", []) or [])
    current_roads = len(getattr(player, "roads", []) or [])

    current_by_action = {
        BUILD_CITY: current_cities,
        BUILD_SETTLEMENT: current_settlements,
        BUILD_ROAD: current_roads,
        BUY_DCARD: 0,
    }

    for action, keys in _STRATEGY_SUMMARY_KEYS.items():
        if action in needs_by_action:
            continue
        key, target_value = _first_positive_value(strategy_summary, keys)
        if not key:
            continue

        # For dcard summary the number is normally "cards to buy", already a
        # remaining-like count.  For pieces it is safer to treat it as a target.
        if action == BUY_DCARD:
            needs_by_action[action] = StrategicNeed(
                action=action,
                source="strategy_summary",
                reason=f"strategy_summary.{key} is positive",
                remaining_key=key,
                remaining_value=target_value,
            )
            continue

        current_count = float(current_by_action.get(action, 0))
        if target_value > current_count:
            needs_by_action[action] = StrategicNeed(
                action=action,
                source="strategy_summary",
                reason=(
                    f"strategy_summary.{key} target {target_value:g} is above "
                    f"current count {current_count:g}"
                ),
                remaining_key=key,
                remaining_value=target_value - current_count,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Small safe helpers
# ──────────────────────────────────────────────────────────────────────────────


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_positive_value(mapping: Mapping[str, Any], keys: Iterable[str]) -> Tuple[str, Optional[float]]:
    for key in keys:
        if key not in mapping:
            continue
        value = _safe_float_or_none(mapping.get(key))
        if value is not None and value > 0:
            return key, value
    return "", None


def _copy_dict_list(values: Sequence[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping):
            out.append(dict(value))
        else:
            out.append({"value": value})
    return out


def _safe_float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _safe_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None
