"""Smoke test for Step 4 Human TwP_AI policy routing.

This test stays focused on the policy decision: TwP_AI treats the Human Player
as an AI-evaluated responder.  The proposal is assumed to be an existing core
TwP candidate, so it should not open the Manual incoming-offer panel.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "core" / "human_twp_policy.py"
if not POLICY_PATH.exists():
    ROOT = Path(__file__).resolve().parent
    POLICY_PATH = ROOT / "core" / "human_twp_policy.py"
if not POLICY_PATH.exists():
    ROOT = Path(__file__).resolve().parent.parent
    POLICY_PATH = ROOT / "core" / "human_twp_policy.py"

spec = importlib.util.spec_from_file_location("human_twp_policy_under_test", POLICY_PATH)
assert spec and spec.loader, f"Could not load {POLICY_PATH}"
policy = importlib.util.module_from_spec(spec)
sys.modules["human_twp_policy_under_test"] = policy
spec.loader.exec_module(policy)


def test_ai_mode_accepts_without_panel() -> None:
    game = SimpleNamespace(
        human_twp_mode="ai",
        human_twp_accepted_this_turn=set(),
        human_twp_declined_this_turn=set(),
        players=[
            SimpleNamespace(id=1, is_human=False),
            SimpleNamespace(id=3, is_human=True),
        ],
    )
    proposal = {
        "active_player_id": 1,
        "counterparty_id": 3,
        "active_player_is_human": False,
        "counterparty_is_human": True,
        "active_give_index": 2,
        "active_give_count": 1,
        "active_receive_index": 3,
        "active_receive_count": 1,
        "auto_executable": False,
    }

    decision = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert decision["status"] == "accepted_ai", decision
    assert decision["accepted"] is True, decision
    assert decision["requires_human_panel"] is False, decision
    assert "existing_ai_twp_candidate" in decision["reason"], decision


def test_manual_mode_still_requires_panel() -> None:
    game = SimpleNamespace(
        human_twp_mode="manual",
        human_twp_accepted_this_turn=set(),
        human_twp_declined_this_turn=set(),
        players=[SimpleNamespace(id=1, is_human=False), SimpleNamespace(id=3, is_human=True)],
    )
    proposal = {
        "active_player_id": 1,
        "counterparty_id": 3,
        "active_player_is_human": False,
        "counterparty_is_human": True,
        "active_give_index": 2,
        "active_give_count": 1,
        "active_receive_index": 3,
        "active_receive_count": 1,
    }
    decision = policy.resolve_incoming_human_twp_offer(game, proposal)
    assert decision["status"] == "pending_human_response", decision
    assert decision["requires_human_panel"] is True, decision


if __name__ == "__main__":
    test_ai_mode_accepts_without_panel()
    test_manual_mode_still_requires_panel()
    print("Human TwP_AI mode smoke test passed.")
