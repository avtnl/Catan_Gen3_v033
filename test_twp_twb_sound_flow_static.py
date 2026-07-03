from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

game_text = (ROOT / 'core' / 'game.py').read_text(encoding='utf-8')
player_trade_text = (ROOT / 'core' / 'player_trade.py').read_text(encoding='utf-8')
twb_panel_text = (ROOT / 'gui' / 'gui_trade_bank_panel.py').read_text(encoding='utf-8')

assert 'def _play_project_sound(self, *sound_names: str) -> bool:' in game_text
assert 'return self._play_project_sound("DEAL", "STEAL")' in game_text
assert 'def _play_twp_found_sound(self) -> bool:' in game_text
assert 'self._play_twp_found_sound()' in game_text
assert 'execute_twp_trade_from_dict(' in game_text

start = player_trade_text.index('def _play_twp_success_sound')
end = player_trade_text.index('def _current_twp_scope', start)
success_block = player_trade_text[start:end]
assert 'sound_names = ("DEAL", "STEAL")' in success_block
assert 'TWPFOUND2", "TWPFOUND"' not in success_block
assert 'if execution_sound(action_name):' in success_block

ok_start = twb_panel_text.index('if rects.get("ok") and rects["ok"].collidepoint(pos):')
ok_block = twb_panel_text[ok_start:ok_start + 500]
assert '_play_error_sound(game)' in ok_block
assert '_play_button_sound(game)' not in ok_block.split('if hasattr(game, "execute_trade_with_bank_vector_action")')[0]

print('TwP/TwB sound-flow static smoke test passed.')
