"""Smoke test for the Human TwP panel opponent-selection flow.

Scenario:
    - Human player is P3.
    - P3 offers 2 Wheat for 1 Ore.
    - P1, P2, and P4 are all willing to accept.
    - The panel exposes clickable/pulsing opponent entries.
    - P3 selects one opponent and sees OKY / OKN.
    - OKN cancels back to selection.
    - OKY executes the selected concrete trade and closes the panel.

The test prefers real pygame.  If pygame is unavailable in a lightweight test
environment, it installs a tiny pygame stub that is sufficient for exercising
the panel state machine and click routing.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

THIS_FILE = Path(__file__).resolve()

# Support both layouts:
#   catan_game_v033/test_twp_panel_ui_smoke.py
#   catan_game_v033/tests/test_twp_panel_ui_smoke.py
# The first smoke-test package assumed the second layout only.
def _find_project_root(start: Path) -> Path:
    for candidate in (start.parent, start.parent.parent):
        if (candidate / "gui" / "gui_trade_player_panel.py").exists():
            return candidate
    # Fallback for generated-package runs where the panel file is bundled next
    # to this smoke test under ../gui.
    return start.parent.parent


ROOT = _find_project_root(THIS_FILE)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_pygame_stub() -> Any:
    pygame = types.ModuleType("pygame")

    class Rect:
        def __init__(self, x: int, y: int, w: int, h: int) -> None:
            self.x = int(x)
            self.y = int(y)
            self.width = int(w)
            self.height = int(h)

        @property
        def right(self) -> int:
            return self.x + self.width

        @property
        def bottom(self) -> int:
            return self.y + self.height

        @property
        def center(self) -> Tuple[int, int]:
            return (self.x + self.width // 2, self.y + self.height // 2)

        def collidepoint(self, pos: Tuple[int, int]) -> bool:
            px, py = pos
            return self.x <= int(px) < self.right and self.y <= int(py) < self.bottom

    class Surface:
        def __init__(self, size: Tuple[int, int] = (1, 1)) -> None:
            self.size = size

        def get_rect(self, **kwargs: Any) -> Rect:
            rect = Rect(0, 0, self.size[0], self.size[1])
            if "center" in kwargs:
                cx, cy = kwargs["center"]
                rect.x = int(cx) - rect.width // 2
                rect.y = int(cy) - rect.height // 2
            return rect

        def blit(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Draw:
        @staticmethod
        def rect(*_args: Any, **_kwargs: Any) -> None:
            return None

        @staticmethod
        def circle(*_args: Any, **_kwargs: Any) -> None:
            return None

    class _FontObject:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.bold = False

        def set_bold(self, bold: bool) -> None:
            self.bold = bool(bold)

        def render(self, text: str, *_args: Any, **_kwargs: Any) -> Surface:
            return Surface((max(1, len(str(text)) * 7), 16))

    class _FontModule:
        @staticmethod
        def init() -> None:
            return None

        @staticmethod
        def Font(*args: Any, **kwargs: Any) -> _FontObject:
            return _FontObject(*args, **kwargs)

    class _Display:
        @staticmethod
        def set_mode(size: Tuple[int, int]) -> Surface:
            return Surface(size)

    class _Time:
        _ticks = 1000

        @classmethod
        def get_ticks(cls) -> int:
            cls._ticks += 16
            return cls._ticks

    class _Sound:
        @staticmethod
        def play(_sound: Any) -> None:
            return None

    class _Mixer:
        Sound = _Sound

    def init() -> None:
        return None

    pygame.Rect = Rect
    pygame.Surface = Surface
    pygame.draw = _Draw()
    pygame.font = _FontModule()
    pygame.display = _Display()
    pygame.time = _Time()
    pygame.mixer = _Mixer()
    pygame.init = init
    sys.modules["pygame"] = pygame
    return pygame


try:
    import pygame  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - fallback for non-GUI CI environments
    pygame = _install_pygame_stub()  # type: ignore

pygame.init()
try:
    pygame.font.init()
except Exception:
    pass
WIN = pygame.display.set_mode((1200, 800))


class _FontFace:
    def __init__(self, size: int, bold: bool = False) -> None:
        self._font = pygame.font.Font(None, size)
        try:
            self._font.set_bold(bold)
        except Exception:
            pass

    def render(self, text: str, antialias: bool, color: Any) -> Any:
        return self._font.render(str(text), antialias, color)


class _FontMember:
    def __init__(self, size: int) -> None:
        self.value = {
            "regular": _FontFace(size, False),
            "bold": _FontFace(size, True),
        }


class Font:
    SMALL = _FontMember(18)
    LARGE = _FontMember(24)


COLORS: Dict[str, Any] = {
    "BLACK": (0, 0, 0),
    "WHITE": (255, 255, 255),
    "GRAY": (130, 130, 130),
    "LGRAY": (210, 210, 210),
    "GREEN": (0, 180, 0),
    "RED": (220, 0, 0),
    "DRED": (180, 0, 0),
    "YELLOW": (255, 235, 80),
    "BLUE": (40, 90, 230),
    "ORANGE": (230, 135, 35),
}

# Stub gui.gui_constants before importing the panel.  The panel is the unit
# under test; assets/sounds/full GUI constants are intentionally avoided.
gui_pkg = types.ModuleType("gui")
gui_pkg.__path__ = [str(ROOT / "gui")]
sys.modules["gui"] = gui_pkg
constants = types.ModuleType("gui.gui_constants")
constants.WIN = WIN
constants.COLORS = COLORS
constants.Font = Font
constants.TRADE_BANK_PANEL_RECT = pygame.Rect(870, 445, 320, 250)
constants.SOUNDS = {}
constants.SCREEN_HEIGHT = 800
sys.modules["gui.gui_constants"] = constants

from gui.gui_trade_player_panel import (  # noqa: E402
    draw_trade_player_panel,
    handle_trade_player_panel_click,
    open_trade_player_panel,
)


class MockGUI:
    def __init__(self) -> None:
        self.twp_panel_state: Dict[str, Any] = {}
        self.buttons: Dict[str, bool] = {}

    def set_button(self, name: str, active: bool) -> None:
        self.buttons[name] = bool(active)


class MockPlayer:
    def __init__(self, player_id: int, hand: List[int], color: str, *, human: bool = False) -> None:
        self.id = player_id
        self.color = color
        self.color2 = color
        self.is_human = human
        self.rcards = {
            "Wheat": hand[0],
            "Ore": hand[1],
            "Wood": hand[2],
            "Brick": hand[3],
            "Sheep": hand[4],
        }

    def rcards_in_hand(self):
        return [
            [self.rcards["Wheat"], self.rcards["Ore"], self.rcards["Wood"], self.rcards["Brick"], self.rcards["Sheep"]],
            [4, 4, 4, 4, 4],
        ]


class MockGame:
    def __init__(self) -> None:
        self.gui = MockGUI()
        self.players = [
            MockPlayer(1, [0, 2, 0, 0, 0], "BLUE"),
            MockPlayer(2, [0, 2, 0, 0, 0], "RED"),
            MockPlayer(3, [2, 0, 0, 0, 0], "WHITE", human=True),
            MockPlayer(4, [0, 2, 0, 0, 0], "ORANGE"),
        ]
        self.turn = 3
        self.executed_options: List[Dict[str, Any]] = []

    def get_current_player(self) -> MockPlayer:
        return self.players[2]

    def find_human_twp_responder_options(self, **kwargs: Any) -> Dict[str, Any]:
        assert kwargs["offer_exact"] == [2, 0, 0, 0, 0], kwargs
        assert kwargs["request_exact"] == [0, 1, 0, 0, 0], kwargs
        options = []
        for counterparty_id in (1, 2, 4):
            options.append(
                {
                    "proposer_id": 3,
                    "counterparty_id": counterparty_id,
                    "proposer_gives": [2, 0, 0, 0, 0],
                    "counterparty_gives": [0, 1, 0, 0, 0],
                    "score": 1.0,
                    "description": f"P3 gives 2Wh for 1O from P{counterparty_id}",
                    "reason": "smoke-test willing opponent",
                }
            )
        return {"ok": True, "options": options}

    def execute_human_twp_selected_option(self, option: Dict[str, Any]) -> Dict[str, Any]:
        self.executed_options.append(dict(option))
        return {"ok": True, "executed": True}


def _click(game: MockGame, rect_key: str) -> None:
    state = game.gui.twp_panel_state
    rect = state["rects"].get(rect_key)
    assert rect is not None, f"missing rect {rect_key}; have {sorted(state['rects'])}"
    handled = handle_trade_player_panel_click(game, rect.center)
    assert handled, rect_key


def test_human_twp_panel_opponent_confirm_flow() -> None:
    game = MockGame()

    open_trade_player_panel(game)
    draw_trade_player_panel(game)

    # Compose: P3 offers 2 Wheat and wants 1 Ore.
    _click(game, "offer_plus_0")
    _click(game, "offer_plus_0")
    _click(game, "request_plus_1")
    _click(game, "ok")  # FIND

    assert game.gui.twp_panel_state["stage"] == "choose"
    assert len(game.gui.twp_panel_state["options"]) == 3

    draw_trade_player_panel(game)

    # All three opponents are willing, so the panel should expose clickable
    # opponent hit boxes. Visually these rows are drawn with pulsing circles.
    for player_id in (1, 2, 4):
        assert f"opponent_{player_id}" in game.gui.twp_panel_state["rects"]

    # First select P2 and press OKN; this should not execute a trade.
    _click(game, "opponent_2")
    assert game.gui.twp_panel_state["stage"] == "confirm"
    draw_trade_player_panel(game)
    assert "oky" in game.gui.twp_panel_state["rects"]
    assert "okn" in game.gui.twp_panel_state["rects"]
    _click(game, "okn")
    assert game.gui.twp_panel_state["stage"] == "choose"
    assert game.executed_options == []

    # Select P4 and press OKY; the selected concrete trade executes and the
    # panel closes. This is the natural end of the OKY branch.
    draw_trade_player_panel(game)
    _click(game, "opponent_4")
    draw_trade_player_panel(game)
    _click(game, "oky")
    assert len(game.executed_options) == 1
    assert game.executed_options[0]["counterparty_id"] == 4
    assert game.gui.twp_panel_state["active"] is False


def main() -> None:
    test_human_twp_panel_opponent_confirm_flow()
    print("Human TwP panel UI smoke test passed.")


if __name__ == "__main__":
    main()
