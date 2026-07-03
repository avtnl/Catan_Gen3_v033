"""Small standalone smoke test for Layer 4 Human TwP wildcard expansion."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.player_trade import (  # noqa: E402
    execute_human_twp_vector_trade,
    find_human_twp_responder_options,
)


class MockPlayer:
    def __init__(self, player_id: int, hand: list[int], *, human: bool = False) -> None:
        self.id = player_id
        self.is_human = human
        self.color = f"P{player_id}"
        self.rcards = {
            "Wheat": hand[0],
            "Ore": hand[1],
            "Wood": hand[2],
            "Brick": hand[3],
            "Sheep": hand[4],
        }
        self.resource_production = [3, 3, 3, 3, 3]
        self.settlements = []
        self.cities = []

    def rcards_in_hand(self):
        return [
            [self.rcards["Wheat"], self.rcards["Ore"], self.rcards["Wood"], self.rcards["Brick"], self.rcards["Sheep"]],
            [4, 4, 4, 4, 4],
        ]


class MockGame:
    def __init__(self) -> None:
        self.players = [
            MockPlayer(1, [1, 2, 0, 0, 1], human=True),
            MockPlayer(2, [0, 0, 2, 1, 1]),
            MockPlayer(3, [0, 0, 1, 3, 0]),
        ]
        self.turn = 1
        self.round = 1
        self.phase = "Execution"
        self.state = "ActionSelection"
        self.board = None

    def get_current_player(self):
        return self.players[0]

    def record_turn_delta(self, *args, **kwargs):
        return {"ok": True}

    def _play_execution_action_sound(self, *args, **kwargs):
        return None


def main() -> None:
    game = MockGame()

    # Human offers 1? for 1Wd. Opponent chooses the ? concrete resource.
    result = find_human_twp_responder_options(
        game,
        proposer_id=1,
        offer_exact=[0, 0, 0, 0, 0],
        offer_wildcard_count=1,
        offer_wildcard_allowed=[True, True, False, True, True],
        request_exact=[0, 0, 1, 0, 0],
        request_wildcard_count=0,
        request_wildcard_allowed=[True, True, True, True, True],
    )
    assert result["ok"], result
    assert result["options"], result
    chosen = result["options"][0]
    assert chosen["counterparty_gives"] == [0, 0, 1, 0, 0], chosen
    assert sum(chosen["proposer_gives"]) == 1, chosen

    executed = execute_human_twp_vector_trade(
        game,
        proposer_id=chosen["proposer_id"],
        counterparty_id=chosen["counterparty_id"],
        proposer_gives=chosen["proposer_gives"],
        counterparty_gives=chosen["counterparty_gives"],
    )
    assert executed["ok"], executed
    print("Human TwP wildcard smoke test passed.")


if __name__ == "__main__":
    main()
