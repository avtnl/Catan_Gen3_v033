"""Smoke test for Step 5 TwP Auto rules editor storage and input flow."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import types
from types import SimpleNamespace

def _project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent,
        here.parent.parent,
        *here.parents,
    ]
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "core" / "human_twp_policy.py").exists() and (candidate / "gui" / "gui_twp_auto_rules_panel.py").exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate project root containing core/human_twp_policy.py "
        "and gui/gui_twp_auto_rules_panel.py. Run from catan_game_v033 or place "
        "this smoke test in catan_game_v033/tests/."
    )


ROOT = _project_root()

# ── lightweight pygame + gui constants stubs ────────────────────────────────
class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.width, self.height = int(x), int(y), int(w), int(h)
    @property
    def right(self):
        return self.x + self.width
    @property
    def bottom(self):
        return self.y + self.height
    @property
    def center(self):
        return (self.x + self.width // 2, self.y + self.height // 2)
    def collidepoint(self, pos):
        x, y = pos
        return self.x <= x < self.right and self.y <= y < self.bottom

class Surface:
    def __init__(self, size=(10, 10)):
        self.size = size
    def get_rect(self, **kwargs):
        rect = Rect(0, 0, self.size[0], self.size[1])
        if "center" in kwargs:
            cx, cy = kwargs["center"]
            rect.x = int(cx - rect.width // 2)
            rect.y = int(cy - rect.height // 2)
        return rect
    def blit(self, *_args, **_kwargs):
        return None

class FontFace:
    def render(self, text, _aa, _color):
        return Surface((max(12, len(str(text)) * 7), 16))

pygame_stub = types.ModuleType("pygame")
pygame_stub.Rect = Rect
pygame_stub.Surface = Surface
pygame_stub.K_ESCAPE = 27
pygame_stub.K_RETURN = 13
pygame_stub.K_KP_ENTER = 271
pygame_stub.K_BACKSPACE = 8
pygame_stub.draw = SimpleNamespace(rect=lambda *a, **k: None)
pygame_stub.mixer = SimpleNamespace(Sound=SimpleNamespace(play=lambda *a, **k: None))
sys.modules.setdefault("pygame", pygame_stub)

gui_pkg = types.ModuleType("gui")
gui_pkg.__path__ = []
sys.modules.setdefault("gui", gui_pkg)
constants = types.ModuleType("gui.gui_constants")
constants.WIN = Surface((1225, 800))
constants.COLORS = {
    "BLACK": (0, 0, 0), "WHITE": (255, 255, 255), "LGRAY": (210, 210, 210),
    "GRAY": (130, 130, 130), "GREEN": (0, 180, 0), "RED": (220, 0, 0),
    "YELLOW": (255, 235, 80),
}
constants.TRADE_BANK_PANEL_RECT = Rect(880, 430, 320, 260)
constants.SOUNDS = {}
constants.Font = SimpleNamespace(
    SMALL=SimpleNamespace(value={"regular": FontFace(), "bold": FontFace()}),
    NORMAL=SimpleNamespace(value={"regular": FontFace(), "bold": FontFace()}),
)
sys.modules["gui.gui_constants"] = constants

core_pkg = types.ModuleType("core")
core_pkg.__path__ = []
sys.modules.setdefault("core", core_pkg)
policy_path = ROOT / "core" / "human_twp_policy.py"
policy_spec = importlib.util.spec_from_file_location("core.human_twp_policy", policy_path)
assert policy_spec and policy_spec.loader
policy = importlib.util.module_from_spec(policy_spec)
sys.modules["core.human_twp_policy"] = policy
policy_spec.loader.exec_module(policy)

panel_path = ROOT / "gui" / "gui_twp_auto_rules_panel.py"
panel_spec = importlib.util.spec_from_file_location("gui.gui_twp_auto_rules_panel", panel_path)
assert panel_spec and panel_spec.loader
panel = importlib.util.module_from_spec(panel_spec)
sys.modules["gui.gui_twp_auto_rules_panel"] = panel
panel_spec.loader.exec_module(panel)

class MockGUI:
    def __init__(self):
        self.buttons = {}
    def set_button(self, name, value):
        self.buttons[name] = bool(value)


def _key_event(key, unicode=""):
    return SimpleNamespace(key=key, unicode=unicode)


def test_rules_panel_enter_ok_commit_and_duplicate_reject() -> None:
    game = SimpleNamespace(gui=MockGUI(), human_twp_auto_rules=["Wh->Wd"])
    panel.open_twp_auto_rules_panel(game)
    assert panel.is_twp_auto_rules_panel_active(game)

    # Type B->Sh and press Enter.
    for ch in "B->Sh":
        panel.handle_twp_auto_rules_key(game, _key_event(0, ch))
    panel.handle_twp_auto_rules_key(game, _key_event(pygame_stub.K_RETURN))
    state = game.gui.twp_auto_rules_panel_state
    assert "B->Sh" in state["working_rules"], state

    # Duplicate is rejected and not appended.
    state["input_text"] = "Wh->Wd"
    panel.handle_twp_auto_rules_key(game, _key_event(pygame_stub.K_RETURN))
    assert state["working_rules"].count("Wh->Wd") == 1, state

    panel.close_twp_auto_rules_panel(game, commit=True)
    assert game.human_twp_auto_rules == ["Wh->Wd", "B->Sh"], game.human_twp_auto_rules
    assert not panel.is_twp_auto_rules_panel_active(game)


def test_rules_panel_nok_cancels() -> None:
    game = SimpleNamespace(gui=MockGUI(), human_twp_auto_rules=["Wh->Wd"])
    panel.open_twp_auto_rules_panel(game)
    state = game.gui.twp_auto_rules_panel_state
    state["working_rules"].append("B->Sh")
    panel.close_twp_auto_rules_panel(game, commit=False)
    assert game.human_twp_auto_rules == ["Wh->Wd"], game.human_twp_auto_rules


if __name__ == "__main__":
    test_rules_panel_enter_ok_commit_and_duplicate_reject()
    test_rules_panel_nok_cancels()
    print("TwP Auto rules panel smoke test passed.")
