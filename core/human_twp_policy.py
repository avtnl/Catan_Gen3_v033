"""Human TwP incoming-offer policy helpers.

This module is intentionally GUI-free.  It stores and evaluates the Human
Player's policy for incoming AI→HP Trade-with-Player proposals.

Step 1/2/3 scope
----------------
Implemented now:
* mode state helpers: manual / red / ai / auto
* Red mode auto-rejection of AI→HP offers
* AI mode auto-acceptance using the normal TwP algorithm result
* Auto mode placeholder: no rules yet means reject human-involved offers
* Manual mode pending/accepted/declined routing for the incoming AI→HP offer panel

Later steps can add the Counter flow and the Auto rule parser without changing
GUI button wiring again.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

MODE_MANUAL = "manual"
MODE_RED = "red"
MODE_AI = "ai"
MODE_AUTO = "auto"
VALID_HUMAN_TWP_MODES = {MODE_MANUAL, MODE_RED, MODE_AI, MODE_AUTO}


def normalize_human_twp_mode(mode: Any) -> str:
    """Return a safe Human TwP mode string."""
    value = str(mode or MODE_MANUAL).strip().lower()
    if value in {"none", "off", "", "manual_mode"}:
        return MODE_MANUAL
    if value in {"twp_red", "red", "reject"}:
        return MODE_RED
    if value in {"twp_ai", "ai"}:
        return MODE_AI
    if value in {"twp_auto", "auto", "green", "rules"}:
        return MODE_AUTO
    return MODE_MANUAL


def get_human_twp_mode(game: Any) -> str:
    """Return the game-level Human TwP incoming-offer mode."""
    try:
        return normalize_human_twp_mode(getattr(game, "human_twp_mode", MODE_MANUAL))
    except Exception:
        return MODE_MANUAL


def set_human_twp_mode(game: Any, mode: Any) -> str:
    """Set and return the Human TwP mode.

    Red / AI / Auto are mutually exclusive because a single string stores the
    selected mode.  Manual means none of those three mode icons is active.
    """
    value = normalize_human_twp_mode(mode)
    try:
        setattr(game, "human_twp_mode", value)
        setattr(game, "last_human_twp_mode_change", {"mode": value})
    except Exception:
        pass
    return value


def toggle_human_twp_mode(game: Any, mode: Any) -> str:
    """Toggle Red/AI/Auto; clicking the active mode returns to Manual."""
    requested = normalize_human_twp_mode(mode)
    if requested == MODE_MANUAL:
        return set_human_twp_mode(game, MODE_MANUAL)
    current = get_human_twp_mode(game)
    if current == requested:
        return set_human_twp_mode(game, MODE_MANUAL)
    return set_human_twp_mode(game, requested)



# ─────────────────────────────────────────────────────────────────────────────
# TwP Auto rule storage + lightweight Step-5 validation
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_RULE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*#!,-> ")
_ALLOWED_RESOURCE_TOKENS = ("Wh", "Wd", "Sh", "O", "B")


def get_human_twp_auto_rules(game: Any) -> List[str]:
    """Return HP's raw TwP Auto rules as a normalized list of strings.

    Step 5 stores rule text only.  Semantic matching of these rules is reserved
    for Step 6, but keeping storage in core prevents the GUI from owning game
    state.
    """
    try:
        rules = list(getattr(game, "human_twp_auto_rules", []) or [])
    except Exception:
        rules = []
    cleaned: List[str] = []
    for rule in rules:
        text = normalize_twp_auto_rule_text(rule)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def set_human_twp_auto_rules(game: Any, rules: Sequence[Any]) -> List[str]:
    """Replace HP's raw TwP Auto rule list after lightweight validation.

    Invalid and duplicate rules are skipped.  The full rule parser/evaluator is
    intentionally not part of Step 5.
    """
    result: List[str] = []
    for rule in list(rules or []):
        checked = validate_twp_auto_rule(rule, existing_rules=result)
        if checked.get("ok"):
            result.append(str(checked.get("rule", "")))
    try:
        setattr(game, "human_twp_auto_rules", list(result))
        setattr(game, "last_human_twp_auto_rules_change", {"rules": list(result)})
    except Exception:
        pass
    return result


def add_human_twp_auto_rule(game: Any, raw_rule: Any) -> Dict[str, Any]:
    """Validate and append one HP TwP Auto rule if it is not a duplicate."""
    rules = get_human_twp_auto_rules(game)
    checked = validate_twp_auto_rule(raw_rule, existing_rules=rules)
    if not checked.get("ok"):
        return checked
    rules.append(str(checked.get("rule", "")))
    set_human_twp_auto_rules(game, rules)
    return {"ok": True, "rule": str(checked.get("rule", "")), "rules": list(rules)}


def delete_human_twp_auto_rule(game: Any, index: int) -> Dict[str, Any]:
    """Delete one HP TwP Auto rule by zero-based index."""
    rules = get_human_twp_auto_rules(game)
    try:
        idx = int(index)
    except Exception:
        return {"ok": False, "reason": "invalid_rule_index", "rules": list(rules)}
    if idx < 0 or idx >= len(rules):
        return {"ok": False, "reason": "rule_index_out_of_range", "rules": list(rules)}
    removed = rules.pop(idx)
    set_human_twp_auto_rules(game, rules)
    return {"ok": True, "removed": removed, "rules": list(rules)}


def normalize_twp_auto_rule_text(raw_rule: Any) -> str:
    """Return a compact raw-rule string used for display and duplicate checks."""
    text = str(raw_rule or "").strip()
    # Collapse spaces around the arrow and commas, but keep compact tokens such
    # as **!Wh,O unchanged.
    text = text.replace(" ", "")
    return text


def validate_twp_auto_rule(raw_rule: Any, *, existing_rules: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Lightweight Step-5 syntax validation for HP TwP Auto rules.

    This is intentionally conservative UI validation only:
    - exactly one ``->``
    - non-empty left and right sides
    - no duplicate rule text
    - only known resource tokens and rule symbols are used

    Full wildcard/identical/except semantics are Step 6.
    """
    rule = normalize_twp_auto_rule_text(raw_rule)
    if not rule:
        return {"ok": False, "reason": "empty_rule"}
    if rule.count("->") != 1:
        return {"ok": False, "reason": "rule_must_contain_exactly_one_arrow"}
    left, right = rule.split("->", 1)
    if not left or not right:
        return {"ok": False, "reason": "both_sides_required", "rule": rule}
    if any(ch not in _ALLOWED_RULE_CHARS for ch in rule):
        return {"ok": False, "reason": "unsupported_character", "rule": rule}
    if not _side_has_known_atoms(left) or not _side_has_known_atoms(right):
        return {"ok": False, "reason": "unknown_resource_token", "rule": rule}
    existing = {normalize_twp_auto_rule_text(x) for x in list(existing_rules or [])}
    if rule in existing:
        return {"ok": False, "reason": "duplicate_rule", "rule": rule}
    return {"ok": True, "rule": rule}


def _side_has_known_atoms(side: str) -> bool:
    """Return True when a lightweight rule side uses only known atoms.

    The accepted symbols are deliberately broad enough for the planned mini
    language: resource tokens (Wh/O/Wd/B/Sh), wildcards (*), identical markers
    (#), except markers (!), and comma-separated parts.
    """
    rest = str(side or "")
    for token in _ALLOWED_RESOURCE_TOKENS:
        rest = rest.replace(token, "")
    rest = rest.replace("*", "").replace("#", "").replace("!", "").replace(",", "")
    return rest == ""

def _player_by_id(game: Any, player_id: Any) -> Optional[Any]:
    try:
        wanted = int(player_id)
    except Exception:
        return None
    for player in list(getattr(game, "players", []) or []):
        try:
            if int(getattr(player, "id", 0) or 0) == wanted:
                return player
        except Exception:
            continue
    return None


def _proposal_mapping(proposal: Any) -> Mapping[str, Any]:
    if isinstance(proposal, Mapping):
        return proposal
    try:
        as_dict = getattr(proposal, "as_dict", None)
        if callable(as_dict):
            data = as_dict()
            if isinstance(data, Mapping):
                return data
    except Exception:
        pass
    return {}


def proposal_key(proposal: Any) -> tuple:
    """Return a stable key for a concrete TwP proposal within one AI turn.

    The key is deliberately resource/direction specific.  It lets Manual mode
    remember whether HP has accepted or declined this exact AI→HP proposal while
    still allowing a different proposal to be offered afterwards.
    """
    data = _proposal_mapping(proposal)
    try:
        return (
            int(data.get("active_player_id", 0) or 0),
            int(data.get("counterparty_id", 0) or 0),
            int(data.get("active_give_index", 0) or 0),
            int(data.get("active_give_count", 0) or 0),
            int(data.get("active_receive_index", 0) or 0),
            int(data.get("active_receive_count", 0) or 0),
        )
    except Exception:
        return (
            data.get("active_player_id"),
            data.get("counterparty_id"),
            data.get("active_give_index"),
            data.get("active_give_count"),
            data.get("active_receive_index"),
            data.get("active_receive_count"),
        )


def _turn_set(game: Any, attr_name: str) -> set:
    """Return a mutable per-turn proposal-key set on game."""
    try:
        value = getattr(game, attr_name, None)
        if not isinstance(value, set):
            value = set(value or [])
            setattr(game, attr_name, value)
        return value
    except Exception:
        return set()


def proposal_involves_human(game: Any, proposal: Any) -> bool:
    """Return True if either side of the TwP proposal is a human player."""
    data = _proposal_mapping(proposal)
    for key in ("active_player_is_human", "counterparty_is_human"):
        try:
            if bool(data.get(key)):
                return True
        except Exception:
            pass

    for key in ("active_player_id", "counterparty_id"):
        player = _player_by_id(game, data.get(key))
        try:
            if player is not None and bool(getattr(player, "is_human", False)):
                return True
        except Exception:
            pass
    return False


def resolve_incoming_human_twp_offer(game: Any, proposal: Any) -> Dict[str, Any]:
    """Resolve an incoming AI→HP TwP proposal against the current HP policy.

    Returned status values:
    * not_human_involved: normal AI-vs-AI proposal
    * rejected: Red mode or Auto mode with no matching rules
    * accepted_ai: AI mode says the existing TwP algorithm may accept for HP
    * accepted_auto: reserved for future HP auto-rules
    * pending_human_response: Manual mode, to be handled by the future popup
    """
    data = dict(_proposal_mapping(proposal))
    mode = get_human_twp_mode(game)
    involves_human = proposal_involves_human(game, proposal)
    result: Dict[str, Any] = {
        "ok": True,
        "mode": mode,
        "involves_human": bool(involves_human),
        "status": "not_human_involved",
        "accepted": False,
        "requires_human_panel": False,
        "reason": "not_human_involved",
        "proposal": data,
    }
    if not involves_human:
        result["accepted"] = bool(data.get("auto_executable", True))
        return result

    if mode == MODE_RED:
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": "human_twp_red_mode_rejects_incoming_offer",
        })
        return result

    if mode == MODE_AI:
        # The proposal reached this function only after core.player_trade built a
        # normal candidate with the same AI guard rails used for AI counterparties
        # (card availability, protected/bottleneck resources, same-turn locks and
        # strategy-fit scoring).  TwP_AI therefore means: include HP in the
        # ordinary candidate pool without opening the Manual-mode panel.
        result.update({
            "status": "accepted_ai",
            "accepted": True,
            "requires_human_panel": False,
            "reason": "human_twp_ai_mode_accepts_existing_ai_twp_candidate",
        })
        return result

    if mode == MODE_AUTO:
        # The rule parser/editor is a later step.  Until rules exist, Auto mode is
        # intentionally conservative: accept none of the HP-involved offers.
        rules = list(getattr(game, "human_twp_auto_rules", []) or [])
        if not rules:
            result.update({
                "status": "rejected",
                "accepted": False,
                "requires_human_panel": False,
                "reason": "human_twp_auto_mode_has_no_rules_yet",
            })
            return result
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": "human_twp_auto_rule_matching_not_implemented_yet",
        })
        return result

    key = proposal_key(proposal)
    accepted = _turn_set(game, "human_twp_accepted_this_turn")
    declined = _turn_set(game, "human_twp_declined_this_turn")

    if key in accepted:
        result.update({
            "status": "accepted_manual",
            "accepted": True,
            "requires_human_panel": False,
            "reason": "human_twp_manual_mode_hp_accepted_this_offer",
            "proposal_key": key,
        })
        return result

    if key in declined:
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": "human_twp_manual_mode_hp_declined_this_offer",
            "proposal_key": key,
        })
        return result

    result.update({
        "status": "pending_human_response",
        "accepted": False,
        "requires_human_panel": True,
        "reason": "human_twp_manual_mode_requires_incoming_offer_panel",
        "proposal_key": key,
    })
    return result
