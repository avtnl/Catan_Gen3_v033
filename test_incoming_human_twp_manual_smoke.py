"""Smoke test for Manual-mode incoming AI→HP TwP routing.

This intentionally avoids importing the full Game class.  It validates the core
policy keys that make Step 3 safe: Manual mode blocks first, ACCEPT turns that
same proposal into an executable candidate, and DECLINE blocks that exact offer.
"""

from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

THIS_FILE = Path(__file__).resolve()

# Support both common locations:
#   catan_game_v033/test_incoming_human_twp_manual_smoke.py
#   catan_game_v033/tests/test_incoming_human_twp_manual_smoke.py
ROOT = None
for candidate in (THIS_FILE.parent, THIS_FILE.parent.parent):
    if (candidate / "core" / "human_twp_policy.py").exists():
        ROOT = candidate
        break
if ROOT is None:
    raise FileNotFoundError(
        "Could not find core/human_twp_policy.py. "
        "Run this test from the project root, or place it in the tests folder."
    )

POLICY_PATH = ROOT / "core" / "human_twp_policy.py"
spec = importlib.util.spec_from_file_location("human_twp_policy_under_test", POLICY_PATH)
assert spec is not None and spec.loader is not None
policy = importlib.util.module_from_spec(spec)
sys.modules["human_twp_policy_under_test"] = policy
spec.loader.exec_module(policy)


def proposal_dict():
    return {
        "active_player_id": 1,
        "counterparty_id": 3,
        "active_player_is_human": False,
        "counterparty_is_human": True,
        "active_give_index": 2,       # AI gives Wood
        "active_give_count": 1,
        "active_receive_index": 3,    # HP gives Brick
        "active_receive_count": 1,
        "auto_executable": False,
    }


def main() -> None:
    game = SimpleNamespace(
        players=[SimpleNamespace(id=1, is_human=False), SimpleNamespace(id=3, is_human=True)],
        human_twp_mode="manual",
        human_twp_accepted_this_turn=set(),
        human_twp_declined_this_turn=set(),
    )
    proposal = proposal_dict()

    first = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert first["status"] == "pending_human_response", first
    assert first["requires_human_panel"] is True, first

    key = policy.proposal_key(proposal)
    game.human_twp_accepted_this_turn.add(key)
    accepted = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert accepted["status"] == "accepted_manual", accepted
    assert accepted["accepted"] is True, accepted

    game.human_twp_accepted_this_turn.clear()
    game.human_twp_declined_this_turn.add(key)
    declined = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert declined["status"] == "rejected", declined
    assert declined["accepted"] is False, declined

    game.human_twp_mode = "red"
    red = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert red["status"] == "rejected", red

    game.human_twp_mode = "ai"
    ai = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert ai["status"] == "accepted_ai", ai
    assert ai["accepted"] is True, ai

    print("Incoming Human TwP manual routing smoke test passed.")


if __name__ == "__main__":
    main()
