"""
Main entry point for the Catan game.

Updated for the modular Execution-phase flow:
- InitialPlacement still starts exactly as before.
- Execution turn scans are triggered by Game.begin_execution_turn() / Game.advance_turn().
- GUI buttons are refreshed every loop so Roll Dices / End Turn state can change.
- Closing the window no longer runs the "game over" celebration by accident.
"""
from datetime import datetime
import pygame

from core.game import Game
from gui.gui import GUI
from gui.gui_human_player import GUIHumanPlayer
from gui.gui_constants import WIN, COLORS, POSITIONS, initialize_sounds
from core.initial_placement_phase_manager import InitialPlacement
from gui.event_handler import EventHandler


def _ensure_execution_scan(game: Game) -> None:
    """
    Safety hook: if the game is already in Execution and no scan has been
    created yet, create one.

    In the updated game.py this normally happens from advance_turn(), but this
    helper makes main.py robust after loading/transition edge cases.
    """
    if game.phase != "Execution":
        return

    if getattr(game, "current_viable_action_scan", None) is None:
        try:
            game.refresh_viable_actions("main_loop_ensure_execution_scan")
        except Exception as exc:
            print(f"Could not refresh viable actions from main.py: {exc}")


def _render_runtime_gui(game: Game, gui: GUI, gui_hp: GUIHumanPlayer) -> None:
    """
    Refresh round/turn, scoreboard and button panel.

    This is intentionally light: it does not redraw the full board every frame,
    because the current GUI uses animation queues for highlights.
    """
    gui.update_round_turn(game, special=False)
    gui.update_scoreboard(game)
    try:
        gui.draw_execution_debug_panel(game)
    except Exception:
        pass
    gui_hp.show_buttons_HP(game, analysis_tf=False)


def _run_game_over_animation(game: Game, gui: GUI) -> None:
    """Run final animation only for a real game-over state, not for window close."""
    print("Game over – running final animation sequence")

    gui.animate_queue_elements = []

    for inter in game.board.intersections:
        if inter and inter.occupied_tf:
            pos = POSITIONS["intersections"].get(inter.id)
            if pos:
                kind = "settlement" if inter.face == "Settlement" else "city"
                gui.animate_queue_elements.append(
                    (pos, COLORS[inter.color.upper()], 20, kind)
                )

    for road in game.board.roads:
        if road and road.occupied_tf:
            start = POSITIONS["intersections"].get(road.id[0])
            end = POSITIONS["intersections"].get(road.id[1])
            if start and end:
                mid = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
                gui.animate_queue_elements.append(
                    (mid, COLORS[road.color.upper()], 20, "road")
                )

    if gui.animate_queue_elements:
        gui._animate_elements(game.board)

    WIN.fill(COLORS["LGRAY"])
    gui.display_fresh_board(game.board, scoreboard_tf=True)
    gui.update_scoreboard(game)
    gui.update_round_turn(game, special=False)
    game.gui.human_guidance.draw()
    pygame.display.update()
    pygame.time.wait(2000)


def main():
    """Run the main game loop."""
    pygame.init()
    initialize_sounds()
    clock = pygame.time.Clock()

    today = datetime.now().strftime("%Y%m%d")

    # Initialize game
    game = Game(
        sequence_number=1,
        id_=today,
        phase="InitialPlacement",
        state="None",
        state_1="0",
        state_2="0",
        myplayers=None,
        board_name="Base_Random",
    )
    game.ip = InitialPlacement(game)

    # Initialize GUI & handler
    gui = GUI(round_number=game.round, turn=game.turn, game=game)
    game.gui = gui
    gui_hp = GUIHumanPlayer()
    event_handler = EventHandler()

    # Initial render
    WIN.fill(COLORS["LGRAY"])
    gui.display_fresh_board(game.board, scoreboard_tf=True)
    gui.update_round_turn(game, special=True)
    gui.update_scoreboard(game)
    try:
        gui.draw_execution_debug_panel(game)
    except Exception:
        pass
    gui_hp.show_buttons_HP(game, analysis_tf=False)
    pygame.display.update()

    # Start initial placement sequence.
    # The updated Game.advance_turn() starts Execution scanning once setup ends.
    game.ip.run()
    _ensure_execution_scan(game)
    _render_runtime_gui(game, gui, gui_hp)

    running = True
    user_quit = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                user_quit = True
                running = False
                break

            if event.type == pygame.KEYDOWN:
                handled = False
                if hasattr(event_handler, "handle_keydown"):
                    handled = event_handler.handle_keydown(event, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

            if event.type == pygame.MOUSEWHEEL:
                handled = False
                if hasattr(event_handler, "handle_mousewheel"):
                    handled = event_handler.handle_mousewheel(event, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

            if event.type == pygame.MOUSEBUTTONDOWN:
                handled = event_handler.handle_click(event.pos, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

        if not running:
            break

        if game.game_over:
            running = False
            break

        _ensure_execution_scan(game)

        # Dynamic overlays
        game.gui.human_guidance.draw()

        # Continuous animation of last placement / selected options.
        game.gui.animate_continuous()

        # Keep buttons aligned with scan/state transitions.
        # This is important after Roll Dices, robber movement, steal choice,
        # and normal ActionSelection rescans.
        gui_hp.show_buttons_HP(game, analysis_tf=False)
        try:
            gui.draw_execution_debug_panel(game)
        except Exception:
            pass

        pygame.display.update()
        clock.tick(60)

    if game.game_over and not user_quit:
        _run_game_over_animation(game, gui)

    pygame.quit()


if __name__ == "__main__":
    main()
