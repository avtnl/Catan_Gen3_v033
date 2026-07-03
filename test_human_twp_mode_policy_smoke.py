"""Smoke test for Step 1/2 Human TwP Mode policy.

Run from the project root with either:
    python tests/test_human_twp_mode_policy_smoke.py
or copy this file to the root and run it directly.

The test imports core/human_twp_policy.py by file path, so it does not trigger
core/__init__.py or the full pygame/game stack.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _project_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name == "tests":
        return here.parent.parent
    return here.parent


def _load_policy_module():
    path = _project_root() / "core" / "human_twp_policy.py"
    spec = importlib.util.spec_from_file_location("human_twp_policy_under_test", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    policy = _load_policy_module()

    game = SimpleNamespace(
        human_twp_mode="manual",
        human_twp_auto_rules=[],
        players=[
            SimpleNamespace(id=1, is_human=False),
            SimpleNamespace(id=2, is_human=False),
            SimpleNamespace(id=3, is_human=True),
            SimpleNamespace(id=4, is_human=False),
        ],
    )
    proposal_to_human = {
        "active_player_id": 1,
        "counterparty_id": 3,
        "active_player_is_human": False,
        "counterparty_is_human": True,
        "auto_executable": False,
    }
    proposal_ai_to_ai = {
        "active_player_id": 1,
        "counterparty_id": 2,
        "active_player_is_human": False,
        "counterparty_is_human": False,
        "auto_executable": True,
    }

    assert policy.get_human_twp_mode(game) == "manual"
    assert policy.resolve_incoming_human_twp_offer(game, proposal_to_human)["status"] == "pending_human_response"

    assert policy.toggle_human_twp_mode(game, "red") == "red"
    red = policy.resolve_incoming_human_twp_offer(game, proposal_to_human)
    assert red["status"] == "rejected"
    assert red["reason"] == "human_twp_red_mode_rejects_incoming_offer"

    assert policy.toggle_human_twp_mode(game, "red") == "manual"
    assert policy.toggle_human_twp_mode(game, "ai") == "ai"
    ai = policy.resolve_incoming_human_twp_offer(game, proposal_to_human)
    assert ai["status"] == "accepted_ai"
    assert ai["accepted"] is True

    assert policy.toggle_human_twp_mode(game, "auto") == "auto"
    auto = policy.resolve_incoming_human_twp_offer(game, proposal_to_human)
    assert auto["status"] == "rejected"
    assert auto["reason"] == "human_twp_auto_mode_has_no_rules_yet"

    normal = policy.resolve_incoming_human_twp_offer(game, proposal_ai_to_ai)
    assert normal["status"] == "not_human_involved"
    assert normal["accepted"] is True

    print("Human TwP Mode policy smoke test passed.")


if __name__ == "__main__":
    main()
