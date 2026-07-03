"""Smoke test for Human Buy City/Settlement guidance animation queue kinds.

This test intentionally loads gui/gui_human_buy_guidance.py directly instead of
importing the full gui package.  That keeps the test lightweight and avoids
starting the whole Pygame/Catan stack.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    if (here / "gui" / "gui_human_buy_guidance.py").exists():
        return here
    if (here.parent / "gui" / "gui_human_buy_guidance.py").exists():
        return here.parent
    raise FileNotFoundError("Could not find gui/gui_human_buy_guidance.py")


def _install_stubs() -> None:
    pygame = ModuleType("pygame")
    pygame.display = SimpleNamespace(update=lambda *args, **kwargs: None)
    pygame.mixer = SimpleNamespace(Sound=SimpleNamespace(play=lambda *args, **kwargs: None))
    sys.modules["pygame"] = pygame

    gui_pkg = ModuleType("gui")
    gui_pkg.__path__ = []
    sys.modules.setdefault("gui", gui_pkg)

    constants = ModuleType("gui.gui_constants")
    constants.COLORS = {
        "BLUE": (0, 0, 255),
        "GREEN": (0, 200, 0),
    }
    constants.POSITIONS = {"intersections": [(100 + i, 200 + i) for i in range(54)]}
    constants.IMAGES = {
        "OKY": {"default": object()},
        "NOK": {"default": object()},
    }
    constants.SOUNDS = {}
    constants.WIN = SimpleNamespace(blit=lambda *args, **kwargs: None)
    sys.modules["gui.gui_constants"] = constants


def _load_module():
    _install_stubs()
    root = _project_root()
    module_path = root / "gui" / "gui_human_buy_guidance.py"
    spec = importlib.util.spec_from_file_location("gui_human_buy_guidance_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gui_human_buy_guidance_under_test"] = module
    spec.loader.exec_module(module)
    return module


class MockGUI:
    def __init__(self) -> None:
        self.human_buy_guidance_state = None
        self.animate_queue_elements = []
        self.modes = []
        self.animations_enabled = False
        self.human_guidance = SimpleNamespace(confirm_center=None)
        self.animate_calls = 0
        self.guidance_texts = []

    def set_mode(self, name, active, source=None):
        if active and name not in self.modes:
            self.modes.append(name)
        if not active:
            self.modes = [x for x in self.modes if x != name]

    def draw_guidance_text(self, text, y_offset=0):
        self.guidance_texts.append((text, y_offset))

    def _animate_elements(self, board):
        self.animate_calls += 1

    def handle_confirmation_click(self, pos):
        return None


class MockGame:
    def __init__(self, player, gui, candidates):
        self.phase = "Execution"
        self.state = "ActionSelection"
        self.gui = gui
        self._player = player
        self.current_viable_action_scan = {"candidates": candidates}
        self.current_execution_choices = []
        self.board = SimpleNamespace(
            intersections=[SimpleNamespace(color="") for _ in range(54)]
        )

    def get_current_player(self):
        return self._player

    def refresh_viable_actions(self, reason):
        return None

    def _execution_cost_vector_for_action(self, action):
        return []

    def _can_player_pay_execution_cost(self, player, cost):
        return True

    def can_build_intersection_tf(self, target, player):
        return True



def _queue_kind(gui: MockGUI) -> str:
    assert len(gui.animate_queue_elements) == 1, gui.animate_queue_elements
    return gui.animate_queue_elements[0][3]


def test_single_settlement_candidate_uses_settlement_animation_kind():
    module = _load_module()
    player = SimpleNamespace(id=3, color="blue", settlements=[11])
    gui = MockGUI()
    game = MockGame(player, gui, {module.BUILD_SETTLEMENT: [{"target_id": 22}]})

    assert module.open_human_settlement_guidance(game) is True
    assert _queue_kind(gui) == "settlement"
    assert gui.animations_enabled is True
    assert gui.animate_calls >= 1

    # Confirmation view should keep the same board-object animation kind.
    gui.human_buy_guidance_state["selected_target"] = 22
    module.draw_human_buy_guidance(game)
    assert _queue_kind(gui) == "settlement"



def test_single_city_candidate_uses_city_animation_kind():
    module = _load_module()
    player = SimpleNamespace(id=3, color="blue", settlements=[11])
    gui = MockGUI()
    game = MockGame(player, gui, {module.BUILD_CITY: [{"target_id": 11}]})

    assert module.open_human_city_guidance(game) is True
    assert _queue_kind(gui) == "city"
    assert gui.animations_enabled is True
    assert gui.animate_calls >= 1

    # Confirmation view should keep the same board-object animation kind.
    gui.human_buy_guidance_state["selected_target"] = 11
    module.draw_human_buy_guidance(game)
    assert _queue_kind(gui) == "city"


if __name__ == "__main__":
    test_single_settlement_candidate_uses_settlement_animation_kind()
    test_single_city_candidate_uses_city_animation_kind()
    print("Human buy guidance animation smoke test passed.")
