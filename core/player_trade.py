"""core/player_trade.py

Trade-with-Player (TwP) planner and executor for Catan Gen3.

Version 1+
---------
Supported proposal shapes:

* 1:1 normal trade
* 2:1 tempting trade: active player gives 2 of one resource for 1 needed resource
* 1:2 scarcity-premium trade: active player gives 1 scarce resource for 2 abundant
  counterparty resources

The module is deliberately independent from GUI code.  It can be used in three
ways:

* Diagnostics: ``make_twp_offer_candidates(game, player)`` returns candidate
  dictionaries for viable_action_scanner / reports / a future TwP panel.
* AI-vs-AI automation: ``find_and_execute_best_ai_to_ai_trade(...)`` executes
  the best automatically acceptable deal.
* Human interactions: ``evaluate_twp_offer(...)`` can be called when a human
  proposes/receives a TwP deal; it returns accept/reject/counter-style data
  without mutating cards unless ``execute_twp_trade`` is called.

Resource order is the existing project order:

    [Wheat, Ore, Wood, Brick, Sheep]

No ``ANY`` resource is stored in the core vectors.  That can be a GUI layer later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from math import isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # Normal project imports.
    from core.constants import ResourceCard  # type: ignore
except Exception:  # pragma: no cover - keeps standalone editing/testing possible.
    class ResourceCard:  # type: ignore[no-redef]
        WHEAT = "Wheat"
        ORE = "Ore"
        WOOD = "Wood"
        BRICK = "Brick"
        SHEEP = "Sheep"

try:
    from core.board import pips_from_tile_value  # type: ignore
except Exception:  # pragma: no cover
    def pips_from_tile_value(value: int) -> float:
        try:
            value = int(value)
        except Exception:
            return 0.0
        if not (2 <= value <= 12):
            return 0.0
        return float(6 - abs(7 - value))

try:
    from core.resource_time_estimator import (  # type: ignore
        get_player_production_pips,
        get_player_resource_cards_vector,
        get_player_trade_rates,
    )
except Exception:  # pragma: no cover
    get_player_production_pips = None  # type: ignore[assignment]
    get_player_resource_cards_vector = None  # type: ignore[assignment]
    get_player_trade_rates = None  # type: ignore[assignment]


RESOURCE_NAMES: Tuple[str, str, str, str, str] = (
    "Wheat",
    "Ore",
    "Wood",
    "Brick",
    "Sheep",
)
RESOURCE_ABBR: Tuple[str, str, str, str, str] = ("W", "O", "Wd", "B", "Sh")
RESOURCECARD_ATTRS: Tuple[str, str, str, str, str] = (
    "WHEAT",
    "ORE",
    "WOOD",
    "BRICK",
    "SHEEP",
)

# Existing game/action cost order: [Wheat, Ore, Wood, Brick, Sheep].
COST_ROAD: Tuple[int, int, int, int, int] = (0, 0, 1, 1, 0)
COST_SETTLEMENT: Tuple[int, int, int, int, int] = (1, 0, 1, 1, 1)
COST_CITY: Tuple[int, int, int, int, int] = (2, 3, 0, 0, 0)
COST_DCARD: Tuple[int, int, int, int, int] = (1, 1, 0, 0, 1)

TRADE_NORMAL_1_FOR_1 = "normal_1_for_1"
TRADE_TEMPTING_2_FOR_1 = "tempting_2_for_1"
TRADE_SCARCITY_PREMIUM_1_FOR_2 = "scarcity_premium_1_for_2"

SUPPORTED_TWP_QUANTITY_PATTERNS: Tuple[Tuple[int, int, str], ...] = (
    (1, 1, TRADE_NORMAL_1_FOR_1),
    (2, 1, TRADE_TEMPTING_2_FOR_1),
    (1, 2, TRADE_SCARCITY_PREMIUM_1_FOR_2),
)

# Conservative defaults.  The brick example discussed earlier had total_pips=11
# and should count as scarce; therefore <= 11 is the default scarce threshold.
DEFAULT_SCARCE_TOTAL_PIPS_MAX: float = 11.0
DEFAULT_SCARCE_PLAYERS_WITH_ACCESS_MAX: int = 2
DEFAULT_ABUNDANT_PLAYER_PIPS_MIN: float = 4.0
DEFAULT_ABUNDANT_HAND_MIN: int = 4
DEFAULT_MAX_PROPOSALS: int = 20

MIN_ACTIVE_SCORE_BY_TRADE_TYPE: Dict[str, float] = {
    TRADE_NORMAL_1_FOR_1: 0.20,
    TRADE_TEMPTING_2_FOR_1: 0.35,
    TRADE_SCARCITY_PREMIUM_1_FOR_2: 0.50,
}
MIN_COUNTERPARTY_SCORE_BY_TRADE_TYPE: Dict[str, float] = {
    TRADE_NORMAL_1_FOR_1: -0.05,
    TRADE_TEMPTING_2_FOR_1: -0.05,
    TRADE_SCARCITY_PREMIUM_1_FOR_2: -0.10,
}

_EPS: float = 1e-9


@dataclass(frozen=True)
class ResourceMarket:
    """Board/player resource scarcity context used by scarcity-premium trades."""

    board_total_pips: Tuple[float, float, float, float, float]
    players_with_access: Tuple[int, int, int, int, int]
    max_player_pips: Tuple[float, float, float, float, float]
    scarce: Tuple[bool, bool, bool, bool, bool]
    abundant_for_players: Dict[int, Tuple[bool, bool, bool, bool, bool]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "resource_order": list(RESOURCE_NAMES),
            "board_total_pips": list(self.board_total_pips),
            "players_with_access": list(self.players_with_access),
            "max_player_pips": list(self.max_player_pips),
            "scarce": list(self.scarce),
            "scarce_named": {
                RESOURCE_NAMES[i]: bool(self.scarce[i]) for i in range(5)
            },
            "abundant_for_players": {
                int(pid): {
                    RESOURCE_NAMES[i]: bool(flags[i]) for i in range(5)
                }
                for pid, flags in self.abundant_for_players.items()
            },
        }


@dataclass(frozen=True)
class TradeProfile:
    """One player's current TwP appetite and card-position profile."""

    player_id: int
    player_color: str
    is_human: bool
    hand: Tuple[int, int, int, int, int]
    trade_rates: Tuple[int, int, int, int, int]
    production_pips: Tuple[float, float, float, float, float]
    primary_action: str
    primary_cost: Tuple[int, int, int, int, int]
    primary_missing: Tuple[int, int, int, int, int]
    clear_surplus: Tuple[int, int, int, int, int]
    protected_resource_vector: Tuple[int, int, int, int, int]
    bottleneck_resource_vector: Tuple[int, int, int, int, int]
    offer_appetite: Tuple[int, int, int, int, int]
    accept_appetite: Tuple[int, int, int, int, int]
    offer_number: Tuple[int, int, int, int, int]
    accept_number: Tuple[int, int, int, int, int]
    reasons: Dict[str, List[str]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["resource_order"] = list(RESOURCE_NAMES)
        data["hand_named"] = _named(self.hand)
        data["trade_rates_named"] = _named(self.trade_rates)
        data["production_pips_named"] = _named(self.production_pips)
        data["primary_cost_named"] = _named(self.primary_cost)
        data["primary_missing_named"] = _named(self.primary_missing)
        data["clear_surplus_named"] = _named(self.clear_surplus)
        data["protected_resource_named"] = _named(self.protected_resource_vector)
        data["bottleneck_resource_named"] = _named(self.bottleneck_resource_vector)
        data["offer_appetite_named"] = _named(self.offer_appetite)
        data["accept_appetite_named"] = _named(self.accept_appetite)
        return data


@dataclass(frozen=True)
class TradeProposal:
    """Concrete active-player proposal against one counterparty."""

    active_player_id: int
    counterparty_id: int
    active_player_is_human: bool
    counterparty_is_human: bool
    trade_type: str
    active_give_index: int
    active_give_count: int
    active_receive_index: int
    active_receive_count: int
    active_score: float
    counterparty_score: float
    total_score: float
    active_gain_vector: Tuple[int, int, int, int, int]
    counterparty_gain_vector: Tuple[int, int, int, int, int]
    active_offer_appetite: int
    active_accept_appetite: int
    counterparty_offer_appetite: int
    counterparty_accept_appetite: int
    requires_human_confirmation: bool
    auto_executable: bool
    status: str = "candidate"
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    market_snapshot: Mapping[str, Any] = field(default_factory=dict)

    @property
    def description(self) -> str:
        return (
            f"P{self.active_player_id} gives {self.active_give_count} "
            f"{RESOURCE_NAMES[self.active_give_index]} for "
            f"{self.active_receive_count} {RESOURCE_NAMES[self.active_receive_index]} "
            f"from P{self.counterparty_id}"
        )

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["description"] = self.description
        data["resource_order"] = list(RESOURCE_NAMES)
        data["active_give_resource"] = RESOURCE_NAMES[self.active_give_index]
        data["active_receive_resource"] = RESOURCE_NAMES[self.active_receive_index]
        data["active_gain_named"] = _named(self.active_gain_vector)
        data["counterparty_gain_named"] = _named(self.counterparty_gain_vector)
        data["legacy_short_text"] = _format_short_trade(self)
        return data


@dataclass(frozen=True)
class TradeDecision:
    """Result of evaluating or executing one TwP proposal."""

    accepted: bool
    executed: bool
    proposal: Optional[TradeProposal]
    reason: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "executed": self.executed,
            "proposal": self.proposal.as_dict() if self.proposal else None,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def make_twp_offer_candidates(
    game: Any,
    player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
    include_human_counterparties: bool = True,
) -> List[Dict[str, Any]]:
    """Return JSON-friendly TwP proposal candidates for scanner/report use.

    This is the safest integration point for ``viable_action_scanner``: it does
    not mutate cards and it does not require a GUI.
    """

    active = _resolve_player(game, player)
    if active is None:
        return []
    proposals = find_twp_proposals(
        game,
        active,
        max_candidates=max_candidates,
        include_human_counterparties=include_human_counterparties,
    )
    return [proposal.as_dict() for proposal in proposals]


def find_twp_proposals(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
    include_human_counterparties: bool = True,
    market: Optional[ResourceMarket] = None,
) -> List[TradeProposal]:
    """Generate and score Version-1+ TwP proposals for the active player."""

    active = _resolve_player(game, active_player)
    if active is None:
        return []

    board = getattr(game, "board", None)
    market = market or build_resource_market(game, board=board)
    active_profile = build_trade_profile(game, active, market=market)

    proposals: List[TradeProposal] = []
    active_id = _player_id(active)
    for counterparty in list(getattr(game, "players", []) or []):
        if counterparty is None or _player_id(counterparty) == active_id:
            continue
        if (not include_human_counterparties) and bool(getattr(counterparty, "is_human", False)):
            continue
        counter_profile = build_trade_profile(game, counterparty, market=market)
        proposals.extend(_generate_pair_proposals(active_profile, counter_profile, market, game=game))

    proposals = [p for p in proposals if p.status == "candidate"]
    proposals = [
        p for p in proposals
        if not _is_inverse_of_recent_accepted_twp(game, p)[0]
    ]
    proposals.sort(
        key=lambda p: (
            -p.total_score,
            p.requires_human_confirmation,
            p.trade_type,
            p.counterparty_id,
            p.active_give_index,
            p.active_receive_index,
            p.active_give_count,
            p.active_receive_count,
        )
    )
    return proposals[: max(0, int(max_candidates))]


def choose_best_twp_proposal(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    ai_only: bool = False,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
) -> Optional[TradeProposal]:
    """Return the highest-scoring proposal, optionally requiring AI-vs-AI."""

    proposals = find_twp_proposals(
        game,
        active_player,
        max_candidates=max_candidates,
        include_human_counterparties=not ai_only,
    )
    if ai_only:
        proposals = [p for p in proposals if p.auto_executable]
    return proposals[0] if proposals else None


def evaluate_twp_offer(
    game: Any,
    *,
    active_player: Any,
    counterparty: Any,
    active_give_index: int,
    active_give_count: int,
    active_receive_index: int,
    active_receive_count: int,
) -> TradeDecision:
    """Evaluate a concrete offer without executing it.

    This is useful when the future TwP panel submits a human-created offer.
    """

    market = build_resource_market(game, board=getattr(game, "board", None))
    active_profile = build_trade_profile(game, active_player, market=market)
    counter_profile = build_trade_profile(game, counterparty, market=market)
    trade_type = _classify_quantity_pattern(active_give_count, active_receive_count)
    if trade_type is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason=(
                "Unsupported TwP shape for Version 1+: only 1:1, 2:1, and "
                "guarded 1:2 trades are supported."
            ),
        )
    proposal = _build_proposal(
        active=active_profile,
        counter=counter_profile,
        give_idx=int(active_give_index),
        give_count=int(active_give_count),
        receive_idx=int(active_receive_index),
        receive_count=int(active_receive_count),
        trade_type=trade_type,
        market=market,
        game=game,
    )
    if proposal is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason="Offer fails card availability, appetite, or scarcity/abundance guard rails.",
        )

    inverse_blocked, inverse_reason = _is_inverse_of_recent_accepted_twp(game, proposal)
    if inverse_blocked:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=proposal,
            reason=inverse_reason,
        )

    return TradeDecision(
        accepted=True,
        executed=False,
        proposal=proposal,
        reason="Offer is acceptable according to the Version-1+ TwP scoring rules.",
    )


def trade_proposal_from_dict(data: Mapping[str, Any]) -> TradeProposal:
    """Rebuild a TradeProposal from its JSON-friendly dictionary form.

    Game stores the chosen TwP candidate in ``current_best_now_action`` as a
    dictionary so it can be displayed in the Execution Debug panel.  Continue
    should execute that exact frozen proposal rather than re-selecting a possibly
    different trade at click time.
    """

    if not isinstance(data, Mapping):
        raise TypeError("TradeProposal data must be a mapping")

    tuple_fields = {
        "active_gain_vector",
        "counterparty_gain_vector",
        "reasons",
    }
    kwargs: Dict[str, Any] = {}
    valid_names = {f.name for f in fields(TradeProposal)}
    for name in valid_names:
        if name not in data:
            continue
        value = data[name]
        if name in tuple_fields and not isinstance(value, tuple):
            value = tuple(value or [])
        kwargs[name] = value

    # field(default=...) values are not filled when we manually call the
    # dataclass constructor through kwargs, so provide the stable defaults here.
    kwargs.setdefault("status", "candidate")
    kwargs.setdefault("reasons", tuple())
    kwargs.setdefault("market_snapshot", {})

    return TradeProposal(**kwargs)  # type: ignore[arg-type]


def execute_twp_trade_from_dict(
    game: Any,
    proposal_data: Mapping[str, Any],
    *,
    require_human_confirmation: bool = True,
) -> TradeDecision:
    """Execute a TwP proposal previously returned by ``proposal.as_dict()``."""

    try:
        proposal = trade_proposal_from_dict(proposal_data)
    except Exception as exc:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason=f"Invalid TwP proposal dictionary: {exc}",
        )
    return execute_twp_trade(
        game,
        proposal,
        require_human_confirmation=require_human_confirmation,
    )


def execute_twp_trade(
    game: Any,
    proposal: TradeProposal,
    *,
    require_human_confirmation: bool = True,
) -> TradeDecision:
    """Execute a concrete TwP proposal by mutating both players' resource cards.

    Human-involved trades are not executed when ``require_human_confirmation`` is
    true.  The GUI/panel should call this again after confirmation.
    """

    if proposal is None:
        return TradeDecision(False, False, None, "No proposal supplied.")
    if require_human_confirmation and proposal.requires_human_confirmation:
        return TradeDecision(
            accepted=True,
            executed=False,
            proposal=proposal,
            reason="Human confirmation required before executing this TwP deal.",
        )

    inverse_blocked, inverse_reason = _is_inverse_of_recent_accepted_twp(game, proposal)
    if inverse_blocked:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=proposal,
            reason=inverse_reason,
        )

    active = _player_by_id(game, proposal.active_player_id)
    counter = _player_by_id(game, proposal.counterparty_id)
    if active is None or counter is None:
        return TradeDecision(False, False, proposal, "Active player or counterparty not found.")

    if not _has_cards(active, proposal.active_give_index, proposal.active_give_count):
        return TradeDecision(False, False, proposal, "Active player no longer has the offered cards.")
    if not _has_cards(counter, proposal.active_receive_index, proposal.active_receive_count):
        return TradeDecision(False, False, proposal, "Counterparty no longer has the requested cards.")

    _add_resource(active, proposal.active_give_index, -proposal.active_give_count)
    _add_resource(counter, proposal.active_give_index, proposal.active_give_count)
    _add_resource(counter, proposal.active_receive_index, -proposal.active_receive_count)
    _add_resource(active, proposal.active_receive_index, proposal.active_receive_count)

    _sync_number_of_rcards(active)
    _sync_number_of_rcards(counter)
    _record_twp_turn_details(game, active, counter, proposal)
    _play_twp_success_sound(game, proposal)

    return TradeDecision(
        accepted=True,
        executed=True,
        proposal=proposal,
        reason=f"Executed TwP: {proposal.description}.",
    )



# ──────────────────────────────────────────────────────────────────────────────
# Human TwP wildcard panel support
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HumanTwPOption:
    """Concrete option produced from one human TwP wildcard request.

    The human/proposer always receives ``counterparty_gives`` and gives
    ``proposer_gives``.  Wildcards never enter the resource vectors; they are
    expanded here into ordinary [Wheat, Ore, Wood, Brick, Sheep] vectors.
    """

    proposer_id: int
    counterparty_id: int
    proposer_gives: Tuple[int, int, int, int, int]
    counterparty_gives: Tuple[int, int, int, int, int]
    score: float = 0.0
    reason: str = ""

    @property
    def description(self) -> str:
        return (
            f"P{self.proposer_id}: {_format_vector_amounts(self.proposer_gives)}"
            f" -> {_format_vector_amounts(self.counterparty_gives)} with P{self.counterparty_id}"
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposer_id": int(self.proposer_id),
            "counterparty_id": int(self.counterparty_id),
            "proposer_gives": list(self.proposer_gives),
            "counterparty_gives": list(self.counterparty_gives),
            "human_gives": list(self.proposer_gives),
            "human_receives": list(self.counterparty_gives),
            "score": round(float(self.score), 4),
            "reason": str(self.reason or ""),
            "description": self.description,
            "resource_order": list(RESOURCE_NAMES),
        }


def find_human_twp_responder_options(
    game: Any,
    *,
    proposer_id: Optional[int] = None,
    offer_exact: Optional[Sequence[Any]] = None,
    offer_wildcard_count: int = 0,
    offer_wildcard_allowed: Optional[Sequence[Any]] = None,
    request_exact: Optional[Sequence[Any]] = None,
    request_wildcard_count: int = 0,
    request_wildcard_allowed: Optional[Sequence[Any]] = None,
    include_human_counterparties: bool = False,
    max_options_per_counterparty: int = 3,
    max_total_options: int = 12,
) -> Dict[str, Any]:
    """Expand a Human TwP wildcard request and find willing AI counterparties.

    Semantics of ``?`` follow the Layer 4 design:

    * If ``?`` is on the human-offer side, the opponent chooses which allowed
      resource the human pays.  The option exists only when the human has that
      concrete card combination.
    * If ``?`` is on the request side, the opponent chooses which allowed
      resource it gives.  The option exists only when the opponent has that
      concrete card combination.
    * When multiple opponents/options are possible, the GUI shows all options and
      the human chooses one or NOK.

    HP-to-HP confirmation is intentionally out of scope for this Layer 4A/4B
    update, so human counterparties are skipped by default.
    """

    proposer = _player_by_id(game, int(proposer_id)) if proposer_id is not None else _resolve_player(game, None)
    if proposer is None:
        return {"ok": False, "reason": "proposer_not_found", "options": [], "resource_order": list(RESOURCE_NAMES)}

    proposer_id_int = _player_id(proposer)
    offer_vec = _list5_int(offer_exact, default=0)
    request_vec = _list5_int(request_exact, default=0)
    offer_wc = max(0, int(offer_wildcard_count or 0))
    request_wc = max(0, int(request_wildcard_count or 0))
    offer_allowed = _allowed_indices_from_flags(offer_wildcard_allowed)
    request_allowed = _allowed_indices_from_flags(request_wildcard_allowed)

    if sum(offer_vec) + offer_wc <= 0:
        return {"ok": False, "reason": "nothing_offered", "options": [], "resource_order": list(RESOURCE_NAMES)}
    if sum(request_vec) + request_wc <= 0:
        return {"ok": False, "reason": "nothing_requested", "options": [], "resource_order": list(RESOURCE_NAMES)}
    if offer_wc > 0 and not offer_allowed:
        return {"ok": False, "reason": "offer_wildcard_has_no_allowed_resources", "options": [], "resource_order": list(RESOURCE_NAMES)}
    if request_wc > 0 and not request_allowed:
        return {"ok": False, "reason": "request_wildcard_has_no_allowed_resources", "options": [], "resource_order": list(RESOURCE_NAMES)}

    proposer_hand = _get_hand(proposer)
    if not _vector_leq(offer_vec, proposer_hand):
        return {
            "ok": False,
            "reason": "proposer_lacks_exact_offer_cards",
            "options": [],
            "hand": list(proposer_hand),
            "offer_exact": list(offer_vec),
            "resource_order": list(RESOURCE_NAMES),
        }

    market = build_resource_market(game, board=getattr(game, "board", None))
    try:
        proposer_profile = build_trade_profile(game, proposer, market=market)
    except Exception:
        proposer_profile = None

    options: List[HumanTwPOption] = []
    skipped_human_counterparties: List[int] = []

    for counter in list(getattr(game, "players", []) or []):
        if counter is None:
            continue
        counter_id = _player_id(counter)
        if counter_id <= 0 or counter_id == proposer_id_int:
            continue
        if _player_is_human(counter) and not include_human_counterparties:
            skipped_human_counterparties.append(counter_id)
            continue

        counter_hand = _get_hand(counter)
        if not _vector_leq(request_vec, counter_hand):
            continue

        try:
            counter_profile = build_trade_profile(game, counter, market=market)
        except Exception:
            counter_profile = None

        human_remaining = [max(0, proposer_hand[i] - offer_vec[i]) for i in range(5)]
        counter_remaining = [max(0, counter_hand[i] - request_vec[i]) for i in range(5)]

        offer_combos = _wildcard_combo_vectors(
            offer_wc,
            offer_allowed,
            human_remaining,
            prefer_accept_profile=counter_profile,
            max_vectors=24,
            receives_from_human=True,
        )
        request_combos = _wildcard_combo_vectors(
            request_wc,
            request_allowed,
            counter_remaining,
            prefer_offer_profile=counter_profile,
            max_vectors=24,
            receives_from_human=False,
        )

        local: List[HumanTwPOption] = []
        for offer_extra in offer_combos:
            proposer_gives = _add_vectors5(offer_vec, offer_extra)
            if not _vector_leq(proposer_gives, proposer_hand):
                continue
            for request_extra in request_combos:
                counterparty_gives = _add_vectors5(request_vec, request_extra)
                if not _vector_leq(counterparty_gives, counter_hand):
                    continue
                if not any(proposer_gives) or not any(counterparty_gives):
                    continue
                if _same_positive_resource_on_both_sides(proposer_gives, counterparty_gives):
                    # Avoid confusing no-op/netted deals in the first UI layer.
                    continue

                willing, reason, score = _human_twp_counterparty_willingness(
                    counter_profile=counter_profile,
                    proposer_profile=proposer_profile,
                    proposer_gives=proposer_gives,
                    counterparty_gives=counterparty_gives,
                    offer_wildcard_count=offer_wc,
                    request_wildcard_count=request_wc,
                )
                if not willing:
                    continue
                local.append(
                    HumanTwPOption(
                        proposer_id=proposer_id_int,
                        counterparty_id=counter_id,
                        proposer_gives=_tuple5_int(proposer_gives),
                        counterparty_gives=_tuple5_int(counterparty_gives),
                        score=score,
                        reason=reason,
                    )
                )

        local.sort(key=lambda item: (-float(item.score), item.description))
        options.extend(local[:max(1, int(max_options_per_counterparty or 1))])

    # De-duplicate identical concrete options and keep the best scoring version.
    dedup: Dict[Tuple[int, Tuple[int, ...], Tuple[int, ...]], HumanTwPOption] = {}
    for option in options:
        key = (int(option.counterparty_id), tuple(option.proposer_gives), tuple(option.counterparty_gives))
        if key not in dedup or option.score > dedup[key].score:
            dedup[key] = option
    options = sorted(dedup.values(), key=lambda item: (-float(item.score), item.counterparty_id, item.description))
    options = options[:max(1, int(max_total_options or 1))]

    return {
        "ok": bool(options),
        "reason": "options_found" if options else "no_willing_counterparty",
        "options": [option.as_dict() for option in options],
        "skipped_human_counterparties": skipped_human_counterparties,
        "resource_order": list(RESOURCE_NAMES),
        "proposer_id": proposer_id_int,
        "offer_exact": list(offer_vec),
        "request_exact": list(request_vec),
        "offer_wildcard_count": offer_wc,
        "request_wildcard_count": request_wc,
    }


def execute_human_twp_vector_trade(
    game: Any,
    *,
    proposer_id: int,
    counterparty_id: int,
    proposer_gives: Sequence[Any],
    counterparty_gives: Sequence[Any],
    source: str = "human_twp_panel",
    reason: str = "human_trade_with_player",
) -> Dict[str, Any]:
    """Execute a concrete Human TwP vector trade after GUI confirmation."""

    proposer = _player_by_id(game, int(proposer_id))
    counter = _player_by_id(game, int(counterparty_id))
    give_vec = _list5_int(proposer_gives, default=0)
    receive_vec = _list5_int(counterparty_gives, default=0)
    result: Dict[str, Any] = {
        "ok": False,
        "action": "TwP",
        "proposer_id": int(proposer_id),
        "counterparty_id": int(counterparty_id),
        "proposer_gives": list(give_vec),
        "counterparty_gives": list(receive_vec),
        "reason": "",
    }

    if proposer is None or counter is None:
        result["reason"] = "proposer_or_counterparty_not_found"
        return result
    if not any(give_vec):
        result["reason"] = "nothing_offered"
        return result
    if not any(receive_vec):
        result["reason"] = "nothing_requested"
        return result
    if _same_positive_resource_on_both_sides(give_vec, receive_vec):
        result["reason"] = "same_resource_on_both_sides"
        return result
    if not _vector_leq(give_vec, _get_hand(proposer)):
        result["reason"] = "proposer_lacks_cards"
        return result
    if not _vector_leq(receive_vec, _get_hand(counter)):
        result["reason"] = "counterparty_lacks_cards"
        return result

    for idx in range(5):
        if give_vec[idx]:
            _add_resource(proposer, idx, -give_vec[idx])
            _add_resource(counter, idx, give_vec[idx])
        if receive_vec[idx]:
            _add_resource(counter, idx, -receive_vec[idx])
            _add_resource(proposer, idx, receive_vec[idx])

    _sync_number_of_rcards(proposer)
    _sync_number_of_rcards(counter)

    proposer_delta = [int(receive_vec[i]) - int(give_vec[i]) for i in range(5)]
    counter_delta = [-int(x) for x in proposer_delta]
    message = f"TwP {_format_vector_amounts(give_vec)} -> {_format_vector_amounts(receive_vec)} with P{int(counterparty_id)}"
    metadata = {
        "proposer_id": int(proposer_id),
        "counterparty_id": int(counterparty_id),
        "proposer_gives": list(give_vec),
        "counterparty_gives": list(receive_vec),
        "human_gives": list(give_vec),
        "human_receives": list(receive_vec),
        "resource_order": list(RESOURCE_NAMES),
        "description": message,
    }
    _record_human_twp_vector_turn_details(
        game,
        proposer,
        counter,
        proposer_delta=proposer_delta,
        counter_delta=counter_delta,
        message=message,
        metadata=metadata,
        source=source,
        reason=reason,
    )
    _play_twp_success_sound(game, None)

    result.update({
        "ok": True,
        "reason": "executed",
        "message": message,
        "proposer_delta": proposer_delta,
        "counterparty_delta": counter_delta,
    })
    return result


def _player_is_human(player: Any) -> bool:
    try:
        return bool(getattr(player, "is_human", False))
    except Exception:
        return False


def _allowed_indices_from_flags(flags: Optional[Sequence[Any]]) -> List[int]:
    if flags is None:
        return list(range(5))
    values = list(flags)
    if not values:
        return []
    out: List[int] = []
    for idx, value in enumerate(values[:5]):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on", RESOURCE_NAMES[idx].lower(), RESOURCE_ABBR[idx].lower()}:
                out.append(idx)
        elif bool(value):
            out.append(idx)
    return out


def _vector_leq(left: Sequence[Any], right: Sequence[Any]) -> bool:
    a = _list5_int(left, default=0)
    b = _list5_int(right, default=0)
    return all(a[i] <= b[i] for i in range(5))


def _add_vectors5(a: Sequence[Any], b: Sequence[Any]) -> List[int]:
    av = _list5_int(a, default=0)
    bv = _list5_int(b, default=0)
    return [av[i] + bv[i] for i in range(5)]


def _same_positive_resource_on_both_sides(a: Sequence[Any], b: Sequence[Any]) -> bool:
    av = _list5_int(a, default=0)
    bv = _list5_int(b, default=0)
    return any(av[i] > 0 and bv[i] > 0 for i in range(5))


def _wildcard_combo_vectors(
    count: int,
    allowed: Sequence[int],
    hand_remaining: Sequence[Any],
    *,
    prefer_accept_profile: Optional[TradeProfile] = None,
    prefer_offer_profile: Optional[TradeProfile] = None,
    max_vectors: int = 24,
    receives_from_human: bool = False,
) -> List[List[int]]:
    count = max(0, int(count or 0))
    if count <= 0:
        return [[0, 0, 0, 0, 0]]
    allowed_indices = [int(i) for i in allowed if 0 <= int(i) < 5]
    if not allowed_indices:
        return []
    remaining = _list5_int(hand_remaining, default=0)
    out: List[List[int]] = []

    def rec(start_idx: int, left: int, vector: List[int]) -> None:
        if len(out) >= max(1, int(max_vectors or 1)) * 4:
            return
        if left == 0:
            out.append(list(vector))
            return
        # Combinations with repetition: keep stable nondecreasing index order.
        for pos in range(start_idx, len(allowed_indices)):
            res_idx = allowed_indices[pos]
            if vector[res_idx] >= remaining[res_idx]:
                continue
            vector[res_idx] += 1
            rec(pos, left - 1, vector)
            vector[res_idx] -= 1

    rec(0, count, [0, 0, 0, 0, 0])

    def combo_score(vector: Sequence[int]) -> float:
        score = 0.0
        for i, amount in enumerate(_list5_int(vector, default=0)):
            if amount <= 0:
                continue
            if prefer_accept_profile is not None:
                appetite = int(prefer_accept_profile.accept_appetite[i] or 0)
                if appetite > 0:
                    score += amount * (8.0 - min(7.0, float(appetite)))
                elif receives_from_human:
                    score -= amount * 2.5
            if prefer_offer_profile is not None:
                appetite = int(prefer_offer_profile.offer_appetite[i] or 0)
                if appetite > 0:
                    score += amount * float(appetite)
                else:
                    score -= amount * 3.0
            # Prefer resources the owner can spare from actual hand volume.
            score += amount * min(2.0, float(remaining[i]) * 0.15)
        return score

    out.sort(key=lambda vec: (-combo_score(vec), tuple(vec)))
    return out[:max(1, int(max_vectors or 1))]


def _human_twp_counterparty_willingness(
    *,
    counter_profile: Optional[TradeProfile],
    proposer_profile: Optional[TradeProfile],
    proposer_gives: Sequence[Any],
    counterparty_gives: Sequence[Any],
    offer_wildcard_count: int,
    request_wildcard_count: int,
) -> Tuple[bool, str, float]:
    human_vec = _list5_int(proposer_gives, default=0)
    counter_vec = _list5_int(counterparty_gives, default=0)
    if counter_profile is None:
        # Conservative fallback: if the opponent can pay and receives at least as
        # many cards as it gives, consider it willing enough to show as option.
        score = float(sum(human_vec) - sum(counter_vec))
        return bool(sum(human_vec) >= sum(counter_vec)), "fallback quantity willingness", score

    receive_score = 0.0
    give_score = 0.0
    bad_give = []
    wanted_received = False
    for idx in range(5):
        if human_vec[idx] > 0:
            appetite = int(counter_profile.accept_appetite[idx] or 0)
            if appetite > 0:
                wanted_received = True
                receive_score += float(human_vec[idx]) * (8.0 - min(7.0, float(appetite)))
            else:
                receive_score += float(human_vec[idx]) * 0.25
        if counter_vec[idx] > 0:
            offer_appetite = int(counter_profile.offer_appetite[idx] or 0)
            if offer_appetite <= 0:
                bad_give.append(RESOURCE_NAMES[idx])
                give_score -= float(counter_vec[idx]) * 5.0
            else:
                give_score += float(counter_vec[idx]) * float(offer_appetite)

    quantity_bonus = 0.75 * (sum(human_vec) - sum(counter_vec))
    wildcard_bonus = 0.15 * (int(offer_wildcard_count or 0) + int(request_wildcard_count or 0))
    score = receive_score + give_score + quantity_bonus + wildcard_bonus

    if bad_give:
        return False, f"counterparty does not want to offer {', '.join(bad_give)}", score
    if not wanted_received and sum(human_vec) <= sum(counter_vec):
        return False, "counterparty does not want the offered cards enough", score
    if score < 0.25:
        return False, "counterparty score too low", score

    return True, "counterparty can choose wildcard resources and accepts concrete option", score


def _format_vector_amounts(values: Sequence[Any]) -> str:
    vec = _list5_int(values, default=0)
    parts = [f"{vec[i]}{RESOURCE_ABBR[i]}" for i in range(5) if vec[i] > 0]
    return "+".join(parts) if parts else "0"


def _record_human_twp_vector_turn_details(
    game: Any,
    proposer: Any,
    counter: Any,
    *,
    proposer_delta: Sequence[int],
    counter_delta: Sequence[int],
    message: str,
    metadata: Mapping[str, Any],
    source: str,
    reason: str,
) -> None:
    proposer_vec = _list5_int(proposer_delta, default=0) + [0]
    counter_vec = _list5_int(counter_delta, default=0) + [0]
    try:
        setattr(proposer, "turn_details_TwP", proposer_vec)
        setattr(proposer, "turn_details_last_TwPdeal", proposer_vec)
        setattr(counter, "turn_details_TwP", counter_vec)
        setattr(counter, "turn_details_last_TwPdeal", counter_vec)
    except Exception:
        pass

    myturn = getattr(game, "myturn", None)
    if myturn is not None:
        try:
            myturn.number_of_deals_offered = int(getattr(myturn, "number_of_deals_offered", 0) or 0) + 1
        except Exception:
            pass

    if hasattr(game, "record_turn_delta"):
        try:
            game.record_turn_delta(
                proposer,
                "TwP",
                resource_delta={RESOURCE_NAMES[i]: proposer_vec[i] for i in range(5) if proposer_vec[i]},
                event_type="trade_with_player",
                target_player_id=_player_id(counter),
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            game.record_turn_delta(
                counter,
                "TwP",
                resource_delta={RESOURCE_NAMES[i]: counter_vec[i] for i in range(5) if counter_vec[i]},
                event_type="trade_with_player",
                target_player_id=_player_id(proposer),
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            return
        except Exception:
            pass

    ledger = getattr(game, "turn_event_ledger", None)
    if ledger is not None and hasattr(ledger, "add_event"):
        try:
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=_player_id(proposer),
                event_type="TwP accepted",
                category="TwP",
                target_player_id=_player_id(counter),
                resource_delta={RESOURCE_NAMES[i]: proposer_vec[i] for i in range(5) if proposer_vec[i]},
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=_player_id(counter),
                event_type="TwP accepted",
                category="TwP",
                target_player_id=_player_id(proposer),
                resource_delta={RESOURCE_NAMES[i]: counter_vec[i] for i in range(5) if counter_vec[i]},
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
        except Exception:
            pass

def find_and_execute_best_ai_to_ai_trade(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
) -> TradeDecision:
    """Find and execute the best AI-vs-AI TwP trade for the active player."""

    proposal = choose_best_twp_proposal(
        game,
        active_player,
        ai_only=True,
        max_candidates=max_candidates,
    )
    if proposal is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason="No acceptable AI-vs-AI TwP proposal found.",
        )
    return execute_twp_trade(game, proposal, require_human_confirmation=False)


# ──────────────────────────────────────────────────────────────────────────────
# Profile and market construction
# ──────────────────────────────────────────────────────────────────────────────


def build_trade_profile(
    game: Any,
    player: Any,
    *,
    market: Optional[ResourceMarket] = None,
    primary_cost: Optional[Sequence[Any]] = None,
    primary_action: Optional[str] = None,
) -> TradeProfile:
    """Build appetite vectors from hand, production, current strategic direction."""

    board = getattr(game, "board", None)
    market = market or build_resource_market(game, board=board)
    hand = _tuple5_int(_get_hand(player))
    trade_rates = _tuple5_int(_get_trade_rates(board, player), default=4)
    production_pips = _tuple5_float(_get_production_pips(board, player))

    if primary_cost is None or primary_action is None:
        inferred_action, inferred_cost = _infer_primary_action_and_cost(player)
        primary_action = primary_action or inferred_action
        primary_cost = primary_cost or inferred_cost

    cost = _tuple5_int(primary_cost, default=0)
    missing = _tuple5_int([max(0, cost[i] - hand[i]) for i in range(5)], default=0)
    surplus = _tuple5_int([max(0, hand[i] - cost[i]) for i in range(5)], default=0)

    protected = _build_protected_resource_vector(
        player=player,
        primary_action=str(primary_action or "unknown"),
        primary_cost=cost,
        hand=hand,
        production_pips=production_pips,
        market=market,
    )
    bottleneck = _build_bottleneck_resource_vector(
        hand=hand,
        production_pips=production_pips,
        protected_resource_vector=protected,
        market=market,
    )

    offer = [0, 0, 0, 0, 0]
    accept = [0, 0, 0, 0, 0]
    offer_number = [1, 1, 1, 1, 1]
    accept_number = [1, 1, 1, 1, 1]
    reasons: Dict[str, List[str]] = {name: [] for name in RESOURCE_NAMES}

    for idx, name in enumerate(RESOURCE_NAMES):
        if hand[idx] > 0:
            if surplus[idx] >= max(1, trade_rates[idx]):
                offer[idx] = 6
                reasons[name].append("surplus reaches bank/port trade rate; only trade if better than TwB")
            elif surplus[idx] >= 1:
                offer[idx] = 2
                reasons[name].append("clear surplus above primary cost")
            elif hand[idx] >= 2 and production_pips[idx] >= DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
                offer[idx] = 4
                reasons[name].append("protected card, but production can probably replace it")
            elif bool(market.scarce[idx]) and hand[idx] >= 1:
                offer[idx] = 4
                reasons[name].append("scarce-card premium may justify offering exactly one")

        if hand[idx] > 0 and protected[idx] >= 4 and surplus[idx] <= 0:
            reasons[name].append("primary-target protected; only give away if an immediate primary action is unlocked")
        elif hand[idx] > 0 and bottleneck[idx] > 0:
            reasons[name].append("bottleneck protected; avoid offering unless it immediately unlocks the primary target")

        if missing[idx] > 0:
            accept[idx] = 1 if production_pips[idx] <= 2.0 else 2
            reasons[name].append("missing for primary action")
        elif bool(market.scarce[idx]) and production_pips[idx] <= 2.0:
            accept[idx] = 3
            reasons[name].append("scarce on board and this player has weak access")

    _add_on_the_fly_acceptance(hand, accept, reasons)

    return TradeProfile(
        player_id=_player_id(player),
        player_color=str(getattr(player, "color", "")),
        is_human=bool(getattr(player, "is_human", False)),
        hand=hand,
        trade_rates=trade_rates,
        production_pips=production_pips,
        primary_action=str(primary_action or "unknown"),
        primary_cost=cost,
        primary_missing=missing,
        clear_surplus=surplus,
        protected_resource_vector=_tuple5_int(protected, default=0),
        bottleneck_resource_vector=_tuple5_int(bottleneck, default=0),
        offer_appetite=_tuple5_int(offer, default=0),
        accept_appetite=_tuple5_int(accept, default=0),
        offer_number=_tuple5_int(offer_number, default=1),
        accept_number=_tuple5_int(accept_number, default=1),
        reasons={k: v for k, v in reasons.items() if v},
    )


def build_resource_market(
    game: Any,
    *,
    board: Optional[Any] = None,
    scarce_total_pips_max: float = DEFAULT_SCARCE_TOTAL_PIPS_MAX,
    scarce_players_with_access_max: int = DEFAULT_SCARCE_PLAYERS_WITH_ACCESS_MAX,
    abundant_player_pips_min: float = DEFAULT_ABUNDANT_PLAYER_PIPS_MIN,
    abundant_hand_min: int = DEFAULT_ABUNDANT_HAND_MIN,
) -> ResourceMarket:
    """Classify board-level scarcity and player-level abundance."""

    board = board if board is not None else getattr(game, "board", None)
    board_total = _tuple5_float(_board_resource_pips(board))

    player_pips_by_id: Dict[int, Tuple[float, float, float, float, float]] = {}
    abundant_for_players: Dict[int, Tuple[bool, bool, bool, bool, bool]] = {}
    players = list(getattr(game, "players", []) or [])

    for player in players:
        pid = _player_id(player)
        pips = _tuple5_float(_get_production_pips(board, player))
        hand = _tuple5_int(_get_hand(player))
        player_pips_by_id[pid] = pips
        abundant_for_players[pid] = tuple(
            bool(pips[i] >= abundant_player_pips_min or hand[i] >= abundant_hand_min)
            for i in range(5)
        )  # type: ignore[assignment]

    players_with_access = []
    max_player_pips = []
    scarce = []
    for idx in range(5):
        access_count = sum(1 for pips in player_pips_by_id.values() if pips[idx] > _EPS)
        max_pip = max([pips[idx] for pips in player_pips_by_id.values()] or [0.0])
        players_with_access.append(access_count)
        max_player_pips.append(max_pip)
        scarce.append(
            bool(
                board_total[idx] <= scarce_total_pips_max
                or access_count <= scarce_players_with_access_max
            )
        )

    return ResourceMarket(
        board_total_pips=_tuple5_float(board_total),
        players_with_access=_tuple5_int(players_with_access, default=0),
        max_player_pips=_tuple5_float(max_player_pips),
        scarce=tuple(bool(x) for x in scarce),  # type: ignore[arg-type]
        abundant_for_players=abundant_for_players,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Proposal generation and scoring
# ──────────────────────────────────────────────────────────────────────────────


def _generate_pair_proposals(
    active: TradeProfile,
    counter: TradeProfile,
    market: ResourceMarket,
    *,
    game: Optional[Any] = None,
) -> List[TradeProposal]:
    proposals: List[TradeProposal] = []
    for give_idx in range(5):
        for receive_idx in range(5):
            if give_idx == receive_idx:
                continue
            for give_count, receive_count, trade_type in SUPPORTED_TWP_QUANTITY_PATTERNS:
                proposal = _build_proposal(
                    active=active,
                    counter=counter,
                    give_idx=give_idx,
                    give_count=give_count,
                    receive_idx=receive_idx,
                    receive_count=receive_count,
                    trade_type=trade_type,
                    market=market,
                    game=game,
                )
                if proposal is not None:
                    proposals.append(proposal)
    return proposals


def _build_proposal(
    *,
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
    game: Optional[Any] = None,
) -> Optional[TradeProposal]:
    if not (0 <= give_idx < 5 and 0 <= receive_idx < 5):
        return None
    if give_idx == receive_idx:
        return None
    if active.hand[give_idx] < give_count:
        return None
    if counter.hand[receive_idx] < receive_count:
        return None

    guard_ok, guard_reasons = _quantity_guard_ok(
        active=active,
        counter=counter,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
    )
    if not guard_ok:
        return None

    strategy_ok, strategy_reasons = _active_strategy_guard_ok(
        game=game,
        active=active,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
    )
    if not strategy_ok:
        return None
    guard_reasons.extend(strategy_reasons)

    # Active gives ``give_idx`` and receives ``receive_idx``.
    # Counterparty gives ``receive_idx`` and receives ``give_idx``.
    if not _appetite_ok(active.offer_appetite[give_idx], trade_type=trade_type, side="offer"):
        return None
    if not _appetite_ok(active.accept_appetite[receive_idx], trade_type=trade_type, side="accept"):
        return None
    if not _appetite_ok(counter.offer_appetite[receive_idx], trade_type=trade_type, side="offer"):
        return None
    if not _appetite_ok(counter.accept_appetite[give_idx], trade_type=trade_type, side="accept"):
        return None

    active_score = _score_trade_for_profile(
        profile=active,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
        is_active=True,
    )
    counter_score = _score_trade_for_profile(
        profile=counter,
        give_idx=receive_idx,
        give_count=receive_count,
        receive_idx=give_idx,
        receive_count=give_count,
        trade_type=trade_type,
        market=market,
        is_active=False,
    )

    if active_score < MIN_ACTIVE_SCORE_BY_TRADE_TYPE[trade_type]:
        return None
    if counter_score < MIN_COUNTERPARTY_SCORE_BY_TRADE_TYPE[trade_type]:
        return None

    risk_penalty = _counterparty_victory_risk_penalty(counter.player_id, active.player_id, market)
    total_score = active_score + counter_score - risk_penalty

    active_gain = [0, 0, 0, 0, 0]
    counter_gain = [0, 0, 0, 0, 0]
    active_gain[give_idx] -= int(give_count)
    active_gain[receive_idx] += int(receive_count)
    counter_gain[give_idx] += int(give_count)
    counter_gain[receive_idx] -= int(receive_count)

    requires_human = bool(active.is_human or counter.is_human)
    reasons = tuple(guard_reasons + _proposal_reason_lines(active, counter, give_idx, receive_idx, trade_type))

    return TradeProposal(
        active_player_id=active.player_id,
        counterparty_id=counter.player_id,
        active_player_is_human=active.is_human,
        counterparty_is_human=counter.is_human,
        trade_type=trade_type,
        active_give_index=int(give_idx),
        active_give_count=int(give_count),
        active_receive_index=int(receive_idx),
        active_receive_count=int(receive_count),
        active_score=round(float(active_score), 4),
        counterparty_score=round(float(counter_score), 4),
        total_score=round(float(total_score), 4),
        active_gain_vector=_tuple5_int(active_gain, default=0),
        counterparty_gain_vector=_tuple5_int(counter_gain, default=0),
        active_offer_appetite=int(active.offer_appetite[give_idx]),
        active_accept_appetite=int(active.accept_appetite[receive_idx]),
        counterparty_offer_appetite=int(counter.offer_appetite[receive_idx]),
        counterparty_accept_appetite=int(counter.accept_appetite[give_idx]),
        requires_human_confirmation=requires_human,
        auto_executable=not requires_human,
        status="candidate",
        reasons=reasons,
        market_snapshot={
            "active_primary_action": active.primary_action,
            "counterparty_primary_action": counter.primary_action,
            "give_resource_scarce": bool(market.scarce[give_idx]),
            "active_give_protected": int(active.protected_resource_vector[give_idx]),
            "active_give_bottleneck": int(active.bottleneck_resource_vector[give_idx]),
            "active_receive_strategy_value": round(_resource_strategy_value(active, receive_idx, market), 3),
            "active_give_strategy_value": round(_resource_strategy_value(active, give_idx, market), 3),
            "receive_abundant_for_counterparty": bool(
                market.abundant_for_players.get(counter.player_id, (False,) * 5)[receive_idx]
            ),
        },

    )


def _active_strategy_guard_ok(
    *,
    game: Optional[Any],
    active: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
) -> Tuple[bool, List[str]]:
    """Return whether the active player should strategically offer this deal.

    This guard is intentionally stricter than card/appetite availability.  It
    prevents TwP chains where the AI trades away a bottleneck or a card it just
    acquired, unless the follow-up trade immediately unlocks the current primary
    target, especially an upgrade_city target.
    """

    reasons: List[str] = []
    before = list(active.hand)
    after = list(active.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return False, []

    before_missing = _weighted_missing_score(before, active.primary_cost, active.production_pips)
    after_missing = _weighted_missing_score(after, active.primary_cost, active.production_pips)
    completes_primary = bool(before_missing > _EPS and after_missing <= _EPS)
    primary_is_city = "city" in str(active.primary_action or "").lower()

    received_this_turn = _received_resource_counts_this_turn(game, active.player_id) if game is not None else [0, 0, 0, 0, 0]
    if received_this_turn[give_idx] > 0 and not completes_primary:
        return (
            False,
            [
                f"blocked: {RESOURCE_NAMES[give_idx]} was received by TwP earlier this turn; "
                "do not trade it away again unless it immediately completes the primary target"
            ],
        )
    if received_this_turn[give_idx] > 0 and completes_primary:
        reasons.append(
            f"exception: gives {RESOURCE_NAMES[give_idx]} received earlier this turn because it immediately completes {active.primary_action}"
        )

    # Bottleneck rule: for example Brick with weak/no Brick access is protected
    # even when city is the primary target.  It may be spent only to complete the
    # primary target immediately.
    if int(active.bottleneck_resource_vector[give_idx] or 0) > 0 and not completes_primary:
        return (
            False,
            [
                f"blocked: gives bottleneck {RESOURCE_NAMES[give_idx]} without immediately completing {active.primary_action}"
            ],
        )
    if int(active.bottleneck_resource_vector[give_idx] or 0) > 0 and completes_primary:
        reasons.append(
            f"exception: gives bottleneck {RESOURCE_NAMES[give_idx]} because trade immediately completes {active.primary_action}"
        )

    # Primary protected resources such as Wheat/Ore for a city target should not
    # be offered away unless the trade completes an even more immediate target.
    if int(active.protected_resource_vector[give_idx] or 0) >= 4 and not completes_primary:
        return (
            False,
            [
                f"blocked: gives primary protected {RESOURCE_NAMES[give_idx]} for {active.primary_action}"
            ],
        )

    receive_value = _resource_strategy_value(active, receive_idx, market) * float(receive_count)
    give_value = _resource_strategy_value(active, give_idx, market) * float(give_count)
    value_delta = receive_value - give_value

    if completes_primary:
        if primary_is_city:
            reasons.append("strategy fit: trade immediately unlocks city upgrade; allow strong exception")
        else:
            reasons.append(f"strategy fit: trade immediately completes {active.primary_action}")
        return True, reasons

    # The received resource must help the active strategy more than the given
    # resource hurts it.  This blocks examples like Brick -> Wood when Brick is
    # the expansion bottleneck and Wood access is already sufficient.
    if value_delta <= 0.10:
        return (
            False,
            [
                f"blocked: strategy value does not improve enough "
                f"({RESOURCE_NAMES[receive_idx]} value {receive_value:.2f} <= "
                f"{RESOURCE_NAMES[give_idx]} value {give_value:.2f})"
            ],
        )

    prior_active_trades = _accepted_twp_count_for_active_player_this_turn(game, active.player_id) if game is not None else 0
    if prior_active_trades >= 1 and value_delta < 1.25:
        return (
            False,
            [
                "blocked: second TwP in same turn requires a strong same-target improvement "
                f"or an immediate primary action; value_delta={value_delta:.2f}"
            ],
        )

    reasons.append(
        f"strategy fit: receives {RESOURCE_NAMES[receive_idx]} improves active target more than giving {RESOURCE_NAMES[give_idx]}"
    )
    return True, reasons


def _quantity_guard_ok(
    *,
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if trade_type == TRADE_NORMAL_1_FOR_1:
        reasons.append("normal 1:1 TwP")
        return True, reasons

    if trade_type == TRADE_TEMPTING_2_FOR_1:
        bank_rate = max(1, int(active.trade_rates[give_idx]))
        if bank_rate <= 2:
            return False, []
        if active.clear_surplus[give_idx] < 1 and active.hand[give_idx] < max(2, bank_rate - 1):
            return False, []
        reasons.append(
            f"tempting 2:1 TwP beats or approaches TwB for {RESOURCE_NAMES[give_idx]} "
            f"(bank rate {bank_rate}:1)"
        )
        return True, reasons

    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        if give_count != 1 or receive_count != 2:
            return False, []
        if not bool(market.scarce[give_idx]):
            return False, []
        abundant_flags = market.abundant_for_players.get(counter.player_id, (False,) * 5)
        if not bool(abundant_flags[receive_idx]):
            return False, []
        if counter.hand[receive_idx] < 2:
            return False, []
        reasons.append(
            f"scarcity premium: {RESOURCE_NAMES[give_idx]} is scarce on the playboard; "
            f"P{counter.player_id} has abundance of {RESOURCE_NAMES[receive_idx]}"
        )
        return True, reasons

    return False, []


def _score_trade_for_profile(
    *,
    profile: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
    is_active: bool,
) -> float:
    before = list(profile.hand)
    after = list(profile.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return -9999.0

    before_missing_score = _weighted_missing_score(before, profile.primary_cost, profile.production_pips)
    after_missing_score = _weighted_missing_score(after, profile.primary_cost, profile.production_pips)
    score = before_missing_score - after_missing_score

    # Make immediately completing the current primary cost attractive.
    if before_missing_score > _EPS and after_missing_score <= _EPS:
        score += 1.25

    # Appetite contributes, but does not replace timing/need logic.
    offer_appetite = int(profile.offer_appetite[give_idx] or 99)
    accept_appetite = int(profile.accept_appetite[receive_idx] or 99)
    score += max(0.0, (5.0 - min(offer_appetite, 5)) * 0.05)
    score += max(0.0, (5.0 - min(accept_appetite, 5)) * 0.08)

    completes_primary = before_missing_score > _EPS and after_missing_score <= _EPS

    # Strategy-fit nudges: receiving a high-value/primary resource should beat
    # giving away a low-value/secondary resource.  Giving away bottlenecks is
    # only tolerated when the trade immediately completes the primary target.
    value_delta = _resource_strategy_value(profile, receive_idx, market) * float(receive_count) - _resource_strategy_value(profile, give_idx, market) * float(give_count)
    score += 0.18 * value_delta

    # Guard against breaking a protected card in the main build target.
    if profile.primary_cost[give_idx] > 0 and before[give_idx] >= profile.primary_cost[give_idx] and after[give_idx] < profile.primary_cost[give_idx]:
        if completes_primary:
            score += 0.20
        elif profile.production_pips[give_idx] < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
            score -= 1.50
        else:
            score -= 0.55

    if profile.bottleneck_resource_vector[give_idx] > 0 and not completes_primary:
        score -= 1.25
    if profile.protected_resource_vector[give_idx] >= 4 and not completes_primary:
        score -= 0.90

    # Scarcity/abundance nudges.
    if market.scarce[receive_idx]:
        score += 0.25
    if market.scarce[give_idx] and trade_type != TRADE_SCARCITY_PREMIUM_1_FOR_2:
        score -= 0.30
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2 and is_active:
        # Active player is intentionally charging a premium for the scarce card.
        score += 0.35

    # Prefer player trade over bank when giving 2 for 1 and bank is 3:1/4:1.
    if trade_type == TRADE_TEMPTING_2_FOR_1 and is_active:
        bank_rate = max(1, int(profile.trade_rates[give_idx]))
        if int(give_count) < bank_rate:
            score += 0.30 * float(bank_rate - int(give_count))

    # Discard risk: reducing hand size above 7 is mildly useful; increasing it is risky.
    before_total = sum(before)
    after_total = sum(after)
    if before_total > 7 and after_total < before_total:
        score += 0.10 * float(before_total - after_total)
    if after_total > 7 and after_total > before_total:
        score -= 0.10 * float(after_total - before_total)

    return float(score)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: cost inference, vectors, resources, logging
# ──────────────────────────────────────────────────────────────────────────────



def _strategic_text(player: Any) -> str:
    """Return a lowercase text blob describing the player's current strategy."""

    parts: List[str] = []
    for attr in ("strategic_direction", "last_strategic_direction", "primary_strategy"):
        value = getattr(player, attr, None)
        if isinstance(value, Mapping):
            for key in (
                "target",
                "target_action",
                "supporting_action_type",
                "action_type",
                "preferred_action_type",
                "need_compact",
                "strategy_name",
                "label",
                "name",
            ):
                item = value.get(key)
                if item not in (None, ""):
                    parts.append(str(item).lower())
            tags = value.get("tags", [])
            if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
                parts.extend(str(t).lower() for t in tags)
        elif value not in (None, ""):
            parts.append(str(value).lower())
    return " ".join(parts)


def _build_protected_resource_vector(
    *,
    player: Any,
    primary_action: str,
    primary_cost: Sequence[int],
    hand: Sequence[int],
    production_pips: Sequence[float],
    market: ResourceMarket,
) -> Tuple[int, int, int, int, int]:
    """Build a 0..5 resource-protection vector for the active strategy.

    Scale:
        0 = not protected
        1 = light protection
        2 = protected
        3 = strong secondary/bottleneck protection
        4 = primary-target protected
        5 = immediate missing primary resource, especially with weak access
    """

    text = _strategic_text(player)
    action = str(primary_action or "").lower()
    protected = [0, 0, 0, 0, 0]

    for idx in range(5):
        if int(primary_cost[idx] or 0) > 0:
            protected[idx] = max(protected[idx], 4)
            if int(hand[idx] or 0) < int(primary_cost[idx] or 0):
                protected[idx] = max(protected[idx], 5 if float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)

    primary_is_city = "city" in action or "city" in text or "upgrade_city" in text or "upgrade city" in text
    if primary_is_city:
        # Wheat/Ore are the true primary target resources for city.  This makes
        # them more protected than Wood/Brick when upgrade_city@... is active.
        protected[0] = max(protected[0], 4)
        protected[1] = max(protected[1], 4)
        if int(hand[0] or 0) < COST_CITY[0]:
            protected[0] = max(protected[0], 5 if float(production_pips[0]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)
        if int(hand[1] or 0) < COST_CITY[1]:
            protected[1] = max(protected[1], 5 if float(production_pips[1]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)

    expansion_words = (
        "settlement",
        "new_settlement",
        "new settlement",
        "road",
        "longest road",
        "longest_road",
    )
    has_expansion_plan = any(word in text for word in expansion_words)
    if has_expansion_plan:
        # Even with city as primary target, Wood/Brick may be needed for the
        # next-settlement/road part of the strategy when the strategic text
        # actually mentions roads/settlements.  A pure city target should not
        # over-protect Wood/Brick.
        for idx in (2, 3):
            secondary = 2
            if bool(market.scarce[idx]) or float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
                secondary = 3
            if float(production_pips[idx]) <= _EPS and int(hand[idx] or 0) > 0:
                secondary = 4 if idx == 3 else 3
            protected[idx] = max(protected[idx], secondary)

    # Sheep is only strategically protected when DCard or settlement is a real
    # target.  It stays low for city-only targets so Sheep -> Brick remains valid
    # when Brick supports roads/new settlements.
    if "dcard" in text or "development" in text or "army" in text or "knight" in text:
        protected[4] = max(protected[4], 3)
    if "settlement" in text:
        protected[4] = max(protected[4], 2)

    return _tuple5_int(protected, default=0)


def _build_bottleneck_resource_vector(
    *,
    hand: Sequence[int],
    production_pips: Sequence[float],
    protected_resource_vector: Sequence[int],
    market: ResourceMarket,
) -> Tuple[int, int, int, int, int]:
    """Mark protected resources that are hard for this player to replace."""

    bottleneck = [0, 0, 0, 0, 0]
    for idx in range(5):
        if int(protected_resource_vector[idx] or 0) <= 0:
            continue
        weak_access = float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN
        no_access = float(production_pips[idx]) <= _EPS
        scarce = bool(market.scarce[idx])
        # Only strongly protected resources become hard bottlenecks.  A lightly
        # protected Sheep card for a possible later settlement should not block
        # a useful Sheep -> Brick road-support trade when there is no DCard
        # ambition.
        if int(protected_resource_vector[idx] or 0) < 3:
            continue
        if no_access and int(hand[idx] or 0) > 0:
            bottleneck[idx] = 2
        elif weak_access and (scarce or int(protected_resource_vector[idx] or 0) >= 3):
            bottleneck[idx] = 1
    return _tuple5_int(bottleneck, default=0)


def _resource_strategy_value(profile: TradeProfile, resource_idx: int, market: ResourceMarket) -> float:
    """Return how valuable one card of this resource is to the profile."""

    idx = int(resource_idx)
    value = 0.0
    value += 0.75 * float(profile.protected_resource_vector[idx])
    value += 1.05 * float(max(0, profile.primary_missing[idx]))
    if int(profile.bottleneck_resource_vector[idx] or 0) > 0:
        value += 1.40 * float(profile.bottleneck_resource_vector[idx])
    if bool(market.scarce[idx]):
        value += 0.35
    if float(profile.production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
        value += 0.45
    if float(profile.production_pips[idx]) <= _EPS:
        value += 0.45
    return float(value)


def _trade_completes_primary_action(
    profile: TradeProfile,
    *,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
) -> bool:
    before = list(profile.hand)
    after = list(profile.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return False
    return bool(
        _weighted_missing_score(before, profile.primary_cost, profile.production_pips) > _EPS
        and _weighted_missing_score(after, profile.primary_cost, profile.production_pips) <= _EPS
    )


def _received_resource_counts_this_turn(game: Optional[Any], player_id: int) -> List[int]:
    counts = [0, 0, 0, 0, 0]
    if game is None:
        return counts
    for record in _twp_memory_records(game):
        try:
            active_id = int(record.get("active_player_id"))
            counter_id = int(record.get("counterparty_id"))
            give_idx = int(record.get("active_give_index"))
            give_count = int(record.get("active_give_count"))
            receive_idx = int(record.get("active_receive_index"))
            receive_count = int(record.get("active_receive_count"))
        except Exception:
            continue
        if int(player_id) == active_id and 0 <= receive_idx < 5:
            counts[receive_idx] += max(0, receive_count)
        elif int(player_id) == counter_id and 0 <= give_idx < 5:
            counts[give_idx] += max(0, give_count)
    return counts


def _accepted_twp_count_for_active_player_this_turn(game: Optional[Any], player_id: int) -> int:
    if game is None:
        return 0
    count = 0
    for record in _twp_memory_records(game):
        try:
            if int(record.get("active_player_id")) == int(player_id):
                count += 1
        except Exception:
            pass
    return count


def _compact_vector(values: Sequence[Any]) -> str:
    parts = []
    for idx, value in enumerate(list(values)[:5]):
        try:
            number = int(value or 0)
        except Exception:
            number = 0
        if number:
            parts.append(f"{RESOURCE_ABBR[idx]}{number}")
    return " ".join(parts) if parts else "-"


def _infer_primary_action_and_cost(player: Any) -> Tuple[str, Tuple[int, int, int, int, int]]:
    text = _strategic_text(player)

    if "city" in text or "upgrade_city" in text or "upgrade city" in text:
        return "city", COST_CITY
    if "settlement" in text:
        return "settlement", COST_SETTLEMENT
    if "road" in text:
        return "road", COST_ROAD
    if "dcard" in text or "development" in text or "army" in text or "knight" in text:
        return "development_card", COST_DCARD

    # Conservative fallback order for execution phase.
    settlements = list(getattr(player, "settlements", []) or [])
    cities = set(getattr(player, "cities", []) or [])
    if any(s not in cities for s in settlements):
        return "city", COST_CITY
    return "settlement", COST_SETTLEMENT


def _add_on_the_fly_acceptance(hand: Sequence[int], accept: List[int], reasons: Dict[str, List[str]]) -> None:
    # Build Road on the fly: one of Wood/Brick is missing, the other is present.
    if hand[2] > 0 and hand[3] == 0 and (accept[3] == 0 or accept[3] > 3):
        accept[3] = 3
        reasons["Brick"].append("build road on the fly")
    if hand[2] == 0 and hand[3] > 0 and (accept[2] == 0 or accept[2] > 3):
        accept[2] = 3
        reasons["Wood"].append("build road on the fly")

    # Build DCard on the fly: two of the three cards are already available.
    dcard = COST_DCARD
    for idx in (0, 1, 4):
        have_other = sum(1 for j in (0, 1, 4) if j != idx and hand[j] >= dcard[j])
        if hand[idx] < dcard[idx] and have_other >= 2 and (accept[idx] == 0 or accept[idx] > 3):
            accept[idx] = 3
            reasons[RESOURCE_NAMES[idx]].append("build development card on the fly")


def _weighted_missing_score(
    hand: Sequence[int],
    cost: Sequence[int],
    production_pips: Sequence[float],
) -> float:
    score = 0.0
    for idx in range(5):
        missing = max(0.0, float(cost[idx]) - float(hand[idx]))
        if missing <= _EPS:
            continue
        # Missing a low-production resource is more painful.
        production_weight = 1.0 + max(0.0, 4.0 - float(production_pips[idx])) * 0.12
        score += missing * production_weight
    return score


def _appetite_ok(value: int, *, trade_type: str, side: str) -> bool:
    if int(value or 0) <= 0:
        return False
    if trade_type == TRADE_NORMAL_1_FOR_1:
        return int(value) <= 4
    if trade_type == TRADE_TEMPTING_2_FOR_1:
        return int(value) <= 6 if side == "offer" else int(value) <= 4
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        # Counterparty may give two abundant cards even when their offer appetite
        # is 6 (bank-trade surplus), because receiving one scarce card can be
        # better than holding bankable surplus.
        return int(value) <= 6 if side == "offer" else int(value) <= 5
    return False


def _proposal_reason_lines(
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    receive_idx: int,
    trade_type: str,
) -> List[str]:
    lines = [
        f"active primary action: {active.primary_action}",
        f"counterparty primary action: {counter.primary_action}",
        f"active wants {RESOURCE_NAMES[receive_idx]} appetite={active.accept_appetite[receive_idx]}",
        f"counterparty wants {RESOURCE_NAMES[give_idx]} appetite={counter.accept_appetite[give_idx]}",
        f"active protected vector: {_compact_vector(active.protected_resource_vector)}",
        f"active bottleneck vector: {_compact_vector(active.bottleneck_resource_vector)}",
    ]
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        lines.append("guarded reverse 2:1 allowed because offered card is scarce")
    return lines


def _counterparty_victory_risk_penalty(counterparty_id: int, active_player_id: int, market: ResourceMarket) -> float:
    # Placeholder hook.  VP/race-specific risk can be added here later without
    # changing the TradeProposal shape.
    _ = (counterparty_id, active_player_id, market)
    return 0.0


def _classify_quantity_pattern(give_count: int, receive_count: int) -> Optional[str]:
    for g, r, trade_type in SUPPORTED_TWP_QUANTITY_PATTERNS:
        if int(give_count) == g and int(receive_count) == r:
            return trade_type
    return None


def _resolve_player(game: Any, player: Optional[Any]) -> Optional[Any]:
    if player is not None:
        return player
    getter = getattr(game, "get_current_player", None)
    if callable(getter):
        try:
            resolved = getter()
            if resolved is not None:
                return resolved
        except Exception:
            pass
    current = getattr(game, "current_player", None)
    if current is not None:
        return current
    turn = _safe_int_or_none(getattr(game, "turn", None))
    if turn is not None:
        for candidate in list(getattr(game, "players", []) or []):
            if _player_id(candidate) == turn:
                return candidate
    return None


def _player_by_id(game: Any, player_id: int) -> Optional[Any]:
    for player in list(getattr(game, "players", []) or []):
        if _player_id(player) == int(player_id):
            return player
    return None


def _player_id(player: Any) -> int:
    value = _safe_int_or_none(getattr(player, "id", None))
    return int(value or 0)


def _get_hand(player: Any) -> List[int]:
    """Return the player's resource hand in [Wheat, Ore, Wood, Brick, Sheep].

    Prefer the project's resource-time helper in the real game, but do not let a
    harmless all-zero helper result hide explicit mock/player data.  This matters
    for smoke tests and for partially constructed GUI/test players.
    """

    if player is None:
        return [0, 0, 0, 0, 0]

    fallback: Optional[List[int]] = None

    rcards_in_hand = getattr(player, "rcards_in_hand", None)
    if callable(rcards_in_hand):
        try:
            result = rcards_in_hand()
            if isinstance(result, (list, tuple)) and result:
                fallback = _list5_int(result[0], default=0)
        except Exception:
            fallback = None

    if fallback is None:
        rcards = getattr(player, "rcards", {})
        if isinstance(rcards, Mapping):
            out: List[int] = []
            for idx in range(5):
                card = _resource_card(idx)
                # Accept both ResourceCard enum/string keys and plain resource-name keys.
                out.append(int(rcards.get(card, rcards.get(RESOURCE_NAMES[idx], 0)) or 0))
            fallback = _list5_int(out, default=0)

    if callable(get_player_resource_cards_vector):
        try:
            helper_vec = _list5_int(get_player_resource_cards_vector(player), default=0)  # type: ignore[misc]
            # In the real game this is normally the best source.  In lightweight
            # mocks it can return [0,0,0,0,0] because the mock lacks board/game
            # details.  Prefer explicit non-zero player data in that case.
            if any(helper_vec) or fallback is None or not any(fallback):
                return helper_vec
        except Exception:
            pass

    return fallback if fallback is not None else [0, 0, 0, 0, 0]


def _get_trade_rates(board: Any, player: Any) -> List[int]:
    if callable(get_player_trade_rates):
        try:
            return _list5_int(get_player_trade_rates(board, player), default=4)  # type: ignore[misc]
        except Exception:
            pass
    rcards_in_hand = getattr(player, "rcards_in_hand", None)
    if callable(rcards_in_hand):
        try:
            result = rcards_in_hand()
            if isinstance(result, (list, tuple)) and len(result) > 1:
                return _list5_int(result[1], default=4)
        except Exception:
            pass
    return _list5_int(getattr(player, "trade_rates", [4, 4, 4, 4, 4]), default=4)


def _get_production_pips(board: Any, player: Any) -> List[float]:
    """Return production pips in [Wheat, Ore, Wood, Brick, Sheep].

    The project helper is preferred for real game objects.  If it returns all
    zeros while the player exposes explicit production data, use the explicit
    data instead.  This keeps standalone tests meaningful and avoids classifying
    every resource as inaccessible.
    """

    fallback = _list5_float(getattr(player, "resource_production", [0, 0, 0, 0, 0]), default=0.0)

    method = getattr(player, "calculate_resource_production_probability", None)
    if callable(method):
        try:
            result = method(board)
            if isinstance(result, Mapping):
                out: List[float] = []
                for idx in range(5):
                    card = _resource_card(idx)
                    out.append(float(result.get(card, result.get(RESOURCE_NAMES[idx], 0.0)) or 0.0))
                method_vec = _list5_float(out)
                if any(method_vec):
                    fallback = method_vec
        except Exception:
            pass

    if callable(get_player_production_pips):
        try:
            helper_vec = _list5_float(get_player_production_pips(board, player), default=0.0)  # type: ignore[misc]
            if any(helper_vec) or not any(fallback):
                return helper_vec
        except Exception:
            pass

    return fallback


def _board_resource_pips(board: Any) -> List[float]:
    out = [0.0, 0.0, 0.0, 0.0, 0.0]
    if board is None:
        return out
    terrain_to_idx = {
        "field": 0,
        "wheat": 0,
        "grain": 0,
        "mountain": 1,
        "ore": 1,
        "forest": 2,
        "wood": 2,
        "lumber": 2,
        "hill": 3,
        "brick": 3,
        "pasture": 4,
        "sheep": 4,
        "wool": 4,
    }
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        kind = str(getattr(tile, "type", "") or "").strip().lower()
        idx = terrain_to_idx.get(kind)
        if idx is None:
            continue
        try:
            value = int(getattr(tile, "value", 0) or 0)
        except Exception:
            value = 0
        out[idx] += float(pips_from_tile_value(value))
    return out


def _resource_card(index: int) -> Any:
    attr = RESOURCECARD_ATTRS[int(index)]
    return getattr(ResourceCard, attr, RESOURCE_NAMES[int(index)])


def _has_cards(player: Any, resource_index: int, count: int) -> bool:
    hand = _get_hand(player)
    return int(hand[int(resource_index)]) >= int(count)


def _add_resource(player: Any, resource_index: int, amount: int) -> None:
    card = _resource_card(resource_index)
    if not hasattr(player, "rcards") or not isinstance(getattr(player, "rcards"), dict):
        player.rcards = { _resource_card(i): 0 for i in range(5) }
    current = int(player.rcards.get(card, 0) or 0)
    player.rcards[card] = max(0, current + int(amount))


def _sync_number_of_rcards(player: Any) -> None:
    try:
        player.number_of_rcards = int(sum(_get_hand(player)))
    except Exception:
        pass




def _play_twp_success_sound(game: Any, proposal: TradeProposal) -> None:
    """Best-effort sound hook after an executed TwP deal.

    Best design is to let the Game/GUI layer own sound playback.  The current
    Successful TwP deals should use the normal cash-register deal sound.
    Informational TwP-found / infobleep sounds are reserved for offers being
    discovered or shown, not for completed trades.

    Design rule: core TwP execution may request a sound, but sound failure must
    never roll back a completed resource-card trade.
    """

    _ = proposal  # reserved for future per-trade sounds/metadata

    # Correct GUI sound keys from gui.gui_constants.Sound.
    # DEAL is CashRegister.wav and is preferred for completed TwP trades.
    # STEAL is a compatibility fallback because it also maps to CashRegister.wav
    # in older gui_constants copies.  Do not fall back to TWPFOUND2/infobleep
    # here: those are informational sounds, not successful-deal sounds.
    sound_names = ("DEAL", "STEAL")

    # Preferred design: use Game's existing execution-action sound hook.  The
    # companion core/game.py maps TwP actions to DEAL.
    execution_sound = getattr(game, "_play_execution_action_sound", None)
    if callable(execution_sound):
        for action_name in ("TwP", "TwP - Make offer", "trade_with_player"):
            try:
                if execution_sound(action_name):
                    return
            except Exception:
                pass

    # Secondary design: the game or GUI layer may expose a direct play_sound API.
    # Try the canonical GUI keys first, while keeping the old "infobleep" string
    # as a compatibility fallback.
    for hook_name in ("play_sound", "playSound", "sound_play"):
        hook = getattr(game, hook_name, None)
        if callable(hook):
            for sound_name in sound_names:
                try:
                    hook(sound_name)
                    return
                except TypeError:
                    try:
                        hook(sound_name, event="twp_executed")
                        return
                    except Exception:
                        pass
                except Exception:
                    pass

    # Compatibility fallbacks: game.sounds["TWPFOUND2"], game.gui.sounds,
    # game.sound_manager.TWPFOUND2, etc.
    candidate_roots = [game]
    for attr in ("sound_manager", "sounds", "audio", "gui"):
        value = getattr(game, attr, None)
        if value is not None:
            candidate_roots.append(value)

    for root in candidate_roots:
        sound = None
        if isinstance(root, Mapping):
            for sound_name in sound_names:
                sound = root.get(sound_name)
                if sound is not None:
                    break
        else:
            for sound_name in sound_names:
                sound = getattr(root, sound_name, None)
                if sound is not None:
                    break

        if sound is None:
            continue

        try:
            if callable(sound):
                sound()
                return
            play = getattr(sound, "play", None)
            if callable(play):
                play()
                return
        except Exception:
            pass

    # Final project-specific fallback: import the GUI registry lazily.  This
    # keeps player_trade.py import-safe in non-GUI tests, but lets main.py play
    # the actual sound when pygame/gui_constants is available.
    try:
        from gui.gui_constants import SOUNDS, initialize_sounds  # type: ignore

        if not SOUNDS:
            try:
                initialize_sounds()
            except Exception:
                pass

        for sound_name in sound_names:
            sound = SOUNDS.get(sound_name)
            if sound is None:
                continue
            play = getattr(sound, "play", None)
            if callable(play):
                play()
                return
    except Exception:
        pass


def _current_twp_scope(game: Any) -> Tuple[Optional[int], Optional[int]]:
    """Return the current (round, turn) marker used for same-turn TwP memory."""

    return (
        _safe_int_or_none(getattr(game, "round", None)),
        _safe_int_or_none(getattr(game, "turn", None)),
    )


def _same_twp_scope(game: Any, record: Mapping[str, Any]) -> bool:
    """Return True when a memory record belongs to the current game round/turn.

    The inverse-trade guard is intentionally same-turn scoped.  A player may
    rationally trade the other way on a later turn after new dice rolls change
    hands and strategy.  The loop we want to prevent is the immediate ping-pong
    within the same active turn/Continue sequence.
    """

    current_round, current_turn = _current_twp_scope(game)
    record_round = _safe_int_or_none(record.get("round"))
    record_turn = _safe_int_or_none(record.get("turn"))
    if current_round is None or current_turn is None:
        return True
    if record_round is None or record_turn is None:
        return True
    return int(record_round) == int(current_round) and int(record_turn) == int(current_turn)


def _turn_details_object(game: Any) -> Any:
    """Return the current turn-details object when available."""

    return getattr(game, "turn_details", None)


def _normalise_twp_record_list(raw_records: Any) -> List[Mapping[str, Any]]:
    """Return mapping records from a dynamically stored TwP memory value."""

    if not isinstance(raw_records, list):
        return []
    return [record for record in raw_records if isinstance(record, Mapping)]


def _twp_memory_records(game: Any) -> List[Mapping[str, Any]]:
    """Return same-turn accepted TwP records.

    Architectural home: ``game.turn_details.accepted_twp_deal_memory``.  This
    is turn-scoped state, so it belongs with the rest of the per-turn event
    details rather than as a loose ``Game`` attribute.

    Compatibility fallback: older test doubles or partially loaded games may
    not have ``turn_details``.  In that case, the function still reads the
    legacy ``game.twp_accepted_deal_memory`` attribute if present.
    """

    records: List[Mapping[str, Any]] = []

    turn_details = _turn_details_object(game)
    if turn_details is not None:
        records.extend(_normalise_twp_record_list(getattr(turn_details, "accepted_twp_deal_memory", None)))

    # Read-only legacy/mock fallbacks.  New records are written to turn_details
    # when available; lightweight tests without turn_details use
    # game.accepted_twp_deal_memory, while earlier builds used
    # game.twp_accepted_deal_memory.
    records.extend(_normalise_twp_record_list(getattr(game, "accepted_twp_deal_memory", None)))
    records.extend(_normalise_twp_record_list(getattr(game, "twp_accepted_deal_memory", None)))

    seen = set()
    same_turn_records: List[Mapping[str, Any]] = []
    for record in records:
        if not _same_twp_scope(game, record):
            continue
        key = (
            _safe_int_or_none(record.get("round")),
            _safe_int_or_none(record.get("turn")),
            _safe_int_or_none(record.get("active_player_id")),
            _safe_int_or_none(record.get("counterparty_id")),
            _safe_int_or_none(record.get("active_give_index")),
            _safe_int_or_none(record.get("active_give_count")),
            _safe_int_or_none(record.get("active_receive_index")),
            _safe_int_or_none(record.get("active_receive_count")),
        )
        if key in seen:
            continue
        seen.add(key)
        same_turn_records.append(record)
    return same_turn_records


def _proposal_is_inverse_of_record(proposal: TradeProposal, record: Mapping[str, Any]) -> bool:
    """Return True when ``proposal`` would undo a previous accepted TwP deal."""

    try:
        record_active = int(record.get("active_player_id"))
        record_counter = int(record.get("counterparty_id"))
        record_give_idx = int(record.get("active_give_index"))
        record_give_count = int(record.get("active_give_count"))
        record_receive_idx = int(record.get("active_receive_index"))
        record_receive_count = int(record.get("active_receive_count"))
    except Exception:
        return False

    # Same active/counter pair: old active tries to give back what they received.
    same_direction_inverse = (
        int(proposal.active_player_id) == record_active
        and int(proposal.counterparty_id) == record_counter
        and int(proposal.active_give_index) == record_receive_idx
        and int(proposal.active_give_count) == record_receive_count
        and int(proposal.active_receive_index) == record_give_idx
        and int(proposal.active_receive_count) == record_give_count
    )
    if same_direction_inverse:
        return True

    # Swapped active/counter pair: old counter tries to undo the same transfer.
    swapped_direction_inverse = (
        int(proposal.active_player_id) == record_counter
        and int(proposal.counterparty_id) == record_active
        and int(proposal.active_give_index) == record_give_idx
        and int(proposal.active_give_count) == record_give_count
        and int(proposal.active_receive_index) == record_receive_idx
        and int(proposal.active_receive_count) == record_receive_count
    )
    return bool(swapped_direction_inverse)


def _is_inverse_of_recent_accepted_twp(game: Any, proposal: TradeProposal) -> Tuple[bool, str]:
    """Block immediate inverse TwP proposals within the same active turn.

    Example loop to prevent:
        P2: 1Wd -> 1B with P1
        P2: 1B  -> 1Wd with P1

    The guard is checked both while generating candidates and again immediately
    before execution, so a frozen/stale BEST NOW proposal cannot execute after a
    different TwP deal has changed the turn context.
    """

    for record in _twp_memory_records(game):
        if _proposal_is_inverse_of_record(proposal, record):
            try:
                previous = (
                    f"P{int(record.get('active_player_id'))}: "
                    f"{int(record.get('active_give_count'))}{RESOURCE_ABBR[int(record.get('active_give_index'))]}"
                    f"->{int(record.get('active_receive_count'))}{RESOURCE_ABBR[int(record.get('active_receive_index'))]} "
                    f"with P{int(record.get('counterparty_id'))}"
                )
            except Exception:
                previous = "previous accepted TwP"
            return (
                True,
                f"Blocked inverse TwP in same turn: {proposal.description} would undo {previous}.",
            )
    return False, ""


def _record_signature_from_record(record: Mapping[str, Any]) -> Tuple[Optional[int], ...]:
    """Return the canonical signature tuple for a TwP memory record."""

    return (
        _safe_int_or_none(record.get("active_player_id")),
        _safe_int_or_none(record.get("counterparty_id")),
        _safe_int_or_none(record.get("active_give_index")),
        _safe_int_or_none(record.get("active_give_count")),
        _safe_int_or_none(record.get("active_receive_index")),
        _safe_int_or_none(record.get("active_receive_count")),
    )


def _remember_accepted_twp_deal(game: Any, proposal: TradeProposal) -> None:
    """Store accepted TwP deal metadata used by the inverse-trade guard.

    Preferred storage is ``game.turn_details.accepted_twp_deal_memory`` because
    inverse-deal prevention is same-turn state.  When ``turn_details`` is not
    available, the function falls back to the legacy game-level attribute so
    standalone tests and lightweight mock games keep working.
    """

    try:
        current_round, current_turn = _current_twp_scope(game)
        record = {
            "round": current_round,
            "turn": current_turn,
            "active_player_id": int(proposal.active_player_id),
            "counterparty_id": int(proposal.counterparty_id),
            "active_give_index": int(proposal.active_give_index),
            "active_give_count": int(proposal.active_give_count),
            "active_receive_index": int(proposal.active_receive_index),
            "active_receive_count": int(proposal.active_receive_count),
            "trade_type": str(proposal.trade_type),
            "description": proposal.description,
            "legacy_short_text": _format_short_trade(proposal),
        }

        turn_details = _turn_details_object(game)
        owner = turn_details if turn_details is not None else game

        records = getattr(owner, "accepted_twp_deal_memory", None)
        if not isinstance(records, list):
            records = []
        records.append(record)

        # Keep the list small and remove records that are not from this turn.
        same_turn_records = [r for r in records if isinstance(r, Mapping) and _same_twp_scope(game, r)]
        same_turn_records = same_turn_records[-20:]
        setattr(owner, "accepted_twp_deal_memory", same_turn_records)

        # Store lightweight signatures too.  The current guard uses the record
        # list so it can produce readable debug reasons, but the signatures make
        # turn_details easy to inspect and future-proof for faster lookups.
        signatures = [_record_signature_from_record(r) for r in same_turn_records]
        setattr(owner, "accepted_twp_deal_signatures", signatures)

        # Keep one explicit last-deal pointer on turn_details when available;
        # otherwise use the legacy game object fallback.
        setattr(owner, "last_accepted_twp_deal", record)
        if turn_details is None:
            setattr(game, "twp_last_accepted_deal", record)
    except Exception:
        pass

def _record_twp_turn_details(game: Any, active: Any, counter: Any, proposal: TradeProposal) -> None:
    _remember_accepted_twp_deal(game, proposal)
    active_delta = list(proposal.active_gain_vector) + [0]
    counter_delta = list(proposal.counterparty_gain_vector) + [0]
    setattr(active, "turn_details_TwP", active_delta)
    setattr(active, "turn_details_last_TwPdeal", active_delta)
    setattr(counter, "turn_details_TwP", counter_delta)
    setattr(counter, "turn_details_last_TwPdeal", counter_delta)

    myturn = getattr(game, "myturn", None)
    if myturn is not None:
        try:
            myturn.number_of_deals_offered = int(getattr(myturn, "number_of_deals_offered", 0) or 0) + 1
        except Exception:
            pass

    ledger = getattr(game, "turn_event_ledger", None)
    if ledger is not None and hasattr(ledger, "add_event"):
        try:
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=proposal.active_player_id,
                event_type="TwP accepted",
                category="TwP",
                target_player_id=proposal.counterparty_id,
                resource_delta={RESOURCE_NAMES[i]: active_delta[i] for i in range(5)},
                public=True,
                source="core.player_trade.execute_twp_trade",
                reason=proposal.trade_type,
                message=proposal.description,
                metadata=proposal.as_dict(),
            )
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=proposal.counterparty_id,
                event_type="TwP accepted",
                category="TwP",
                target_player_id=proposal.active_player_id,
                resource_delta={RESOURCE_NAMES[i]: counter_delta[i] for i in range(5)},
                public=True,
                source="core.player_trade.execute_twp_trade",
                reason=proposal.trade_type,
                message=proposal.description,
                metadata=proposal.as_dict(),
            )
        except Exception:
            pass


def _format_short_trade(proposal: TradeProposal) -> str:
    return (
        f"P{proposal.active_player_id}: "
        f"{proposal.active_give_count}{RESOURCE_ABBR[proposal.active_give_index]}"
        f"->{proposal.active_receive_count}{RESOURCE_ABBR[proposal.active_receive_index]} "
        f"with P{proposal.counterparty_id}"
    )


def _named(values: Sequence[Any]) -> Dict[str, Any]:
    return {RESOURCE_NAMES[i]: values[i] for i in range(min(5, len(values)))}


def _safe_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if not isfinite(out):
            return default
        return out
    except Exception:
        return default


def _list5_int(values: Optional[Sequence[Any]], default: int = 0) -> List[int]:
    out = [int(round(_safe_float(v, float(default)))) for v in list(values or [])[:5]]
    out.extend([int(default)] * max(0, 5 - len(out)))
    return out


def _list5_float(values: Optional[Sequence[Any]], default: float = 0.0) -> List[float]:
    out = [_safe_float(v, default) for v in list(values or [])[:5]]
    out.extend([float(default)] * max(0, 5 - len(out)))
    return out


def _tuple5_int(values: Optional[Sequence[Any]], default: int = 0) -> Tuple[int, int, int, int, int]:
    vec = _list5_int(values, default=default)
    return int(vec[0]), int(vec[1]), int(vec[2]), int(vec[3]), int(vec[4])


def _tuple5_float(values: Optional[Sequence[Any]], default: float = 0.0) -> Tuple[float, float, float, float, float]:
    vec = _list5_float(values, default=default)
    return float(vec[0]), float(vec[1]), float(vec[2]), float(vec[3]), float(vec[4])
