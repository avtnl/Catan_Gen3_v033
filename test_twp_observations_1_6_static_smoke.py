"""Static smoke checks for TwP / Execution UI observations 1-6.

This test is intentionally lightweight and path-independent.  It verifies the
small coordination changes that are hard to unit-test without a live pygame
screen and a full Catan board.
"""
from pathlib import Path


def _root() -> Path:
    here = Path(__file__).resolve()
    if (here.parent / "core").exists() and (here.parent / "gui").exists():
        return here.parent
    if (here.parent.parent / "core").exists() and (here.parent.parent / "gui").exists():
        return here.parent.parent
    return Path.cwd()


ROOT = _root()


def _read(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        raise AssertionError(f"Missing expected file: {path}")
    return path.read_text(encoding="utf-8")


def test_modal_continue_guard_present() -> None:
    text = _read("gui/gui_human_player.py")
    assert "def _modal_trade_or_rules_panel_active" in text
    assert "pending_human_twp_offer" in text
    assert "continue_active = False" in text


def test_twp_success_sound_is_deal() -> None:
    game_text = _read("core/game.py")
    assert 'return "DEAL"' in game_text
    assert "Successful TwP deals should sound like a completed trade" in game_text
    player_trade_text = _read("core/player_trade.py")
    assert 'sound_names = ("DEAL", "TWPFOUND2", "TWPFOUND", "infobleep")' in player_trade_text


def test_no_extra_success_beep_in_twp_and_buy_guidance() -> None:
    twp_text = _read("gui/gui_trade_player_panel.py")
    assert "Avoid a second info/button beep" in twp_text
    assert "Successful TwP execution already plays the CashRegister" in twp_text
    buy_text = _read("gui/gui_human_buy_guidance.py")
    assert "Do not add an extra button" in buy_text


def test_equal_twp_mode_border_thickness() -> None:
    text = _read("gui/gui_human_player.py")
    assert "pygame.draw.rect(WIN, border_color, rect, 2)" in text
    assert "3 if selected and active else 2" not in text


def test_execution_debug_redraw_restored() -> None:
    main_text = _read("main.py")
    event_text = _read("gui/event_handler.py")
    assert "gui.draw_execution_debug_panel(game)" in main_text
    assert "game.gui.draw_execution_debug_panel(game)" in event_text
    assert (ROOT / "gui" / "gui_execution_debug_panel.py").exists()


if __name__ == "__main__":
    test_modal_continue_guard_present()
    test_twp_success_sound_is_deal()
    test_no_extra_success_beep_in_twp_and_buy_guidance()
    test_equal_twp_mode_border_thickness()
    test_execution_debug_redraw_restored()
    print("TwP observations 1-6 static smoke test passed.")
