from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

constants = (ROOT / "gui" / "gui_constants.py").read_text(encoding="utf-8")
gui_hp = (ROOT / "gui" / "gui_human_player.py").read_text(encoding="utf-8")
event_handler = (ROOT / "gui" / "event_handler.py").read_text(encoding="utf-8")

# TwP Mode buttons must align vertically with the four Buy buttons below them.
for name, x in {
    "twp_mode_red": 140,
    "twp_mode_ai": 190,
    "twp_mode_auto": 240,
    "edit_twp_auto": 290,
}.items():
    assert f'"{name}": pygame.Rect({x}, HUMAN_BUTTON_ROW_Y["twp_mode"] - 5, 40, 40)' in constants

for name, x in {
    "buy_city": 140,
    "buy_settlement": 190,
    "buy_road": 240,
    "buy_dcard": 290,
}.items():
    assert f'"{name}": pygame.Rect({x}, HUMAN_BUTTON_ROW_Y["buy"], 40, 40)' in constants

# Fallback rectangles must stay aligned too, for tests or older constants.
for text in [
    '"twp_mode_red": pygame.Rect(140, 215, 40, 40)',
    '"twp_mode_ai": pygame.Rect(190, 215, 40, 40)',
    '"twp_mode_auto": pygame.Rect(240, 215, 40, 40)',
    '"edit_twp_auto": pygame.Rect(290, 215, 40, 40)',
]:
    assert text in gui_hp
    assert text in event_handler

# Inactive TwP Mode row clicks outside Execution should play ERROR instead of falling through silently.
assert 'TWP_MODE_RECTS = (' in event_handler
assert 'game.phase != "Execution"' in event_handler
assert 'self._play_sound("ERROR")' in event_handler

# Active Execution buttons should still play BUTTON; inactive Auto placeholder should be routed to ERROR.
assert '(TWP_MODE_RED_RECT, "twp_mode_red", "red")' in event_handler
assert '(TWP_MODE_AI_RECT, "twp_mode_ai", "ai")' in event_handler
assert '(TWP_MODE_AUTO_RECT, "twp_mode_auto", "auto")' in event_handler
assert 'self._play_sound("BUTTON")' in event_handler
assert 'game.gui.check_button(button_name)' in event_handler

print("TwP mode button alignment/sound static smoke test passed.")
