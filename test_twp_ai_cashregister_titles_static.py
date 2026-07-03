from pathlib import Path


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "core" / "game.py").exists() and (p / "gui" / "gui_trade_player_panel.py").exists():
            return p
    raise RuntimeError("Could not find project/update root containing core/game.py and gui/gui_trade_player_panel.py")


ROOT = find_root(Path(__file__).resolve())
game_text = (ROOT / "core" / "game.py").read_text(encoding="utf-8")
panel_text = (ROOT / "gui" / "gui_trade_player_panel.py").read_text(encoding="utf-8")

# In the AI TwP execution path, TwP_Found should no longer be played before execution.
marker = "def _execute_ai_twp_support"
start = game_text.find(marker)
assert start >= 0, "Could not find _execute_ai_twp_support"
end = game_text.find("def ", start + len(marker))
block = game_text[start:end if end >= 0 else len(game_text)]
assert "_play_twp_found_sound()" not in block, "AI TwP execution path still plays TwP_Found"
assert "execute_twp_trade_from_dict" in block, "AI TwP execution path no longer executes TwP trade"
assert "DEAL" in game_text, "Game sound mapping should still include DEAL/CashRegister"

# Both outgoing and incoming TwP panel headers should use the full title.
assert panel_text.count('render("Trade with Player"') == 2, "Expected two Trade with Player panel titles"
assert 'render("TwP"' not in panel_text, "Short TwP title still appears in a panel header"
assert 'Font.NORMAL.value["bold"]' in panel_text, "TwP title should use normal bold font like TwB"

print("TwP AI CashRegister/title static smoke test passed.")
