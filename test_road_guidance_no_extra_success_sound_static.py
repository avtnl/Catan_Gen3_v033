from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == 'tests' else Path(__file__).resolve().parent
path = ROOT / 'gui' / 'gui_human_road_guidance.py'
text = path.read_text(encoding='utf-8')

success_marker = 'if isinstance(result, Mapping) and bool(result.get("ok")):'
idx = text.index(success_marker)
block = text[idx: idx + 450]
assert '_play_sound(gui, "BUTTON")' not in block, 'Road success path still plays extra BUTTON sound'
assert 'close_human_road_guidance(game, redraw=False)' in block
assert '_refresh_after_build(game)' in block
print('Road guidance no-extra-success-sound static smoke test passed.')
