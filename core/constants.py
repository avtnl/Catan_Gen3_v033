"""
Defines constants and utility functions for the Catan game.

This module centralizes game configuration, file paths, and utility functions used across
other modules to ensure consistency and ease of maintenance.

Key components:
    - File paths for logs and saved playboards.
    - Game configuration flags (e.g., human player, victory points).
    - Window dimensions and game data (e.g., resource costs, development cards).
    - Enumerations for resources.
    - Utility functions for calculations like intersection probability.

Dependencies:
    - os: For file path handling.
    - typing: For type hints.
    - enum: For resource enumeration.
"""
import os
from typing import Dict, List, Tuple
from enum import Enum

# File Paths
SAVE_PATH: str = os.path.join(
    os.path.expanduser("~"), "Documents", "Projecten", "Python", "Catan_Gen3", "Logs"
)

"""Directory path for saving game logs and playboards."""

# Game Configuration Flags
FNFREQ: str = "N"
"""Flag for frequency logging ('Y' or 'N')."""

NUM_PLAYERS: int = 4
"""Number of players in the game."""

HUMAN_PLAYER: bool = True
#HUMAN_PLAYER: bool = False
"""Whether human players are participating."""

INIT_HP: bool = False
"""Whether human player initialization has occurred."""

HP_ID: List[int] = [3]
#HP_ID: List[int] = []
"""List of human player IDs (for future multi-human support)."""

VICTORY: int = 10
"""Victory points required to win."""

GAME_MAX_ROUND: int = 50
"""Maximum number of game rounds."""

DICEROLL_SET_TF: bool = False
"""Whether to use a fixed dice roll sequence."""

NAME_DR_FILE: str = "DiceRolls_4_Players_13_Mar_2025_00_22_10.txt"
"""File name for dice roll sequence."""

NO_GUI_AT_ALL_TF: bool = False
"""Whether to disable GUI entirely."""

LOAD_PLAYBOARD: bool = True
"""Whether to load a saved playboard."""

SAVED_PLAYBOARD: str = "PlayBoard 08_Apr_2026_13_33_06.txt"
"""File name for saved playboard."""

LOAD_GAME: bool = False
#LOAD_GAME: bool = True
"""Whether to load a full saved game instead of starting from a fresh/current board state."""

#SAVED_GAME: str = "Saved_Game_23_Apr_2025_09_54_16_R9T1.txt"
SAVED_GAME: str = "Saved_Game_21_Jun_2026_18_20_16_R1T1.txt"
"""File name for a full saved game created by Game.save_game()."""

MG: bool = True
"""Flag for multiple game logging."""

MEM_TWP: bool = False
"""Whether to memorize trade-with-player rejections."""


# Expected-Hand (EH) data (algorithm_id=5)
ALGORITHM_ID_EXPECTED_HAND: int = 5
"""Initial placement algorithm id for Expected-Hand feasibility."""

EXPECTED_HAND_MAX_TURNS: float = 60.0
"""Maximum own turns searched by EH when estimating turns-to-afford."""

EXPECTED_HAND_STEP: float = 0.25
"""Search resolution in own turns for EH timing estimates."""

EXPECTED_HAND_CONFIDENCE_TARGET: float = 0.85
"""Optional confidence threshold for EH if confidence-gated timing is enabled."""

EXPECTED_HAND_REQUIRE_CONFIDENCE: bool = False
"""If True, EH only accepts a candidate once both affordability and confidence target are met."""

EXPECTED_HAND_ROLLS_PER_PLAYER_TURN: int = NUM_PLAYERS
"""Expected global dice rolls per own turn. In a 4-player game this is normally 4."""

EXPECTED_HAND_TARGET_EXTRA_ROADS: int = 1
"""EH initial-placement target is next settlement plus this many roads."""

EXPECTED_HAND_CONTINUOUS_TRADING: bool = True
"""Allow EH to use continuous expected surplus divided by trade rate as a timing heuristic."""

EXPECTED_HAND_USE_PORTS: bool = True
"""Allow EH to use current candidate ports when estimating trade rates."""

EXPECTED_HAND_STORE_PLAYER_DEBUG: bool = True
"""Store EH candidate diagnostics on the player object for later inspection/logging."""

EXPECTED_HAND_DEBUG_TOP_N: int = 20
"""Number of EH-ranked candidates written to MG debug logging."""

# Window Dimensions
WIN_WIDTH: int = 800
"""Game window width in pixels."""

WIN_HEIGHT: int = 600
"""Game window height in pixels."""


# Game Data
LIST_OF_DCARDS: List[str] = ["knight"] * 14 + ["victory_point"] * 5 + ["two_free_roads"] * 2 + ["year_of_plenty"] * 2 + ["monopoly"] * 2
"""List of development cards in the deck."""

RCARDS_FOR_CITY: List[int] = [2, 3, 0, 0, 0]
"""Resources needed for a city: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_SETTLEMENT: List[int] = [1, 0, 1, 1, 1]
"""Resources needed for a settlement: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_ROAD: List[int] = [0, 0, 1, 1, 0]
"""Resources needed for a road: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_DCARD: List[int] = [1, 1, 0, 0, 1]
"""Resources needed for a development card: [grain, ore, wood, brick, sheep]."""


# Resource Enumeration
class ResourceCard(Enum):
    """Enumeration of resource card types in Catan."""
   
    WHEAT = "Wheat"
    ORE = "Ore"
    WOOD = "Wood"
    BRICK = "Brick"
    SHEEP = "Sheep"


# Order used for lists, indices, dashboards, etc.
RESOURCE_ORDER: List[ResourceCard] = [
    ResourceCard.WHEAT,
    ResourceCard.ORE,
    ResourceCard.WOOD,
    ResourceCard.BRICK,
    ResourceCard.SHEEP,
]


# Tile terrain name -> resource card produced (used for production, initial placement, robber logic, etc.)
TERRAIN_TO_RESOURCE: Dict[str, ResourceCard] = {
    "Field":    ResourceCard.WHEAT,
    "Mountain": ResourceCard.ORE,
    "Forest":   ResourceCard.WOOD,
    "Hill":     ResourceCard.BRICK,
    "Pasture":  ResourceCard.SHEEP,
    # "Desert":   None    # ← no need to map (already filtered out)
}


# Optional: reverse mapping (useful for debugging / logging / UI)
RESOURCE_TO_TERRAIN: Dict[ResourceCard, str] = {
    v: k for k, v in TERRAIN_TO_RESOURCE.items()
}


# File Names
FILENAME_HELP: str = "Catan16Mar2026_v1"
"""Base filename for logs."""

FILENAME: str = f"{FILENAME_HELP}.txt"
"""Main log file."""

FILENAME_CS: str = f"{FILENAME_HELP}_CS.txt"
"""Change strategy log file."""

FILENAME_MG: str = f"{FILENAME_HELP}_MG.txt"
"""Multiple games log file."""

FILENAME_MG2: str = f"{FILENAME_HELP}_MG2.txt"
"""Secondary multiple games log file."""

FILENAME_MGLOG: str = f"{FILENAME_HELP}_MGlog.txt"
"""Log for games with NO_GUI_AT_ALL_TF=True."""

FILENAME_MGLOG2: str = f"{FILENAME_HELP}_MGlog2.txt"
"""Secondary log for games with NO_GUI_AT_ALL_TF=True."""

FILENAME_SUM: str = f"{FILENAME_HELP}_Sum.txt"
"""Summary log file."""

FILENAME_SPEC: str = f"{FILENAME_HELP}_Spec.txt"
"""Special log file."""

FILENAME_SPEC2: str = f"{FILENAME_HELP}_Spec2.txt"
"""Secondary special log file."""

FILENAME_LOG: str = f"{FILENAME_HELP}_Log.txt"
"""General log file."""

FILENAME_FREQ: str = f"{FILENAME_HELP}_Freq.txt"
"""Frequency log file."""

FILENAME_MAPPING: str = f"{FILENAME_HELP}_Mapping.txt"
"""Mapping log for distance and path maps."""

FILENAME_MINDMAP: str = f"{FILENAME_HELP}_MindMap.txt"
"""Mind map log file."""

FILENAME_MINDMAP2: str = f"{FILENAME_HELP}_MindMap2.txt"
"""Secondary mind map log file."""

FILENAME_FOUNDPATH: str = f"{FILENAME_HELP}_FoundPath.txt"
"""Found path log file."""

FILENAME_DATAMAP: str = f"{FILENAME_HELP}_DataMap.txt"
"""Data map log file."""


class PlayerColor(Enum):
    """Enumeration for player color mappings in game logic."""
    BLUE = (1, "Blue", (0, 0, 255))
    RED = (2, "Red", (255, 0, 0))
    WHITE = (3, "White", (255, 255, 255))
    ORANGE = (4, "Orange", (255, 165, 0))

    def __init__(self, code: int, color_name: str, rgb: Tuple[int, int, int]) -> None:
        """Initialize a PlayerColor instance.

        Args:
            code: Unique player ID (1-4).
            color_name: Name of the color (e.g., 'Blue').
            rgb: RGB tuple for the color.
        """
        self.code = code
        self.color_name = color_name
        self.rgb = rgb

REVERSE_COLOR_MAPPING: Dict[str, str] = {
    "Blue": "Orange",
    "Red": "White",
    "White": "Red",
    "Orange": "Blue"
}
"""Dictionary mapping player colors to their opposites for game logic."""


# Planning Phase
# BLOCKED_EMPTY: float = 0.2
BLOCKED_WEIGHT = 0.1
TOP_N = 15


# Utility Functions
def intersection_probability(dice_roll: int) -> int:
    """Calculate the probability of a dice roll for an intersection.

    Args:
        dice_roll: The sum of two dice (2-12).

    Returns:
        int: The probability value (dots) for the dice roll.

    Examples:
        >>> intersection_probability(6)
        5
        >>> intersection_probability(7)
        6
    """
    prob_map: Dict[int, int] = {2: 1, 12: 1, 3: 2, 11: 2, 4: 3, 10: 3, 5: 4, 9: 4, 6: 5, 8: 5, 7: 6}
    return prob_map.get(dice_roll, 0)


def get_rcard_costs() -> Dict[str, Dict[ResourceCard, int]]:
    """Generate a dictionary of resource costs for building actions.

    Args:
        None

    Returns:
        Dict[str, Dict[ResourceCard, int]]: A dictionary mapping building types to their resource costs.

    Examples:
        >>> costs = get_resource_costs()
        >>> costs["settlement"][ResourceCard.GRAIN]
        1
    """
    return {
        "settlement": {
            ResourceCard.WHEAT: RCARDS_FOR_SETTLEMENT[0],
            ResourceCard.ORE: RCARDS_FOR_SETTLEMENT[1],
            ResourceCard.WOOD: RCARDS_FOR_SETTLEMENT[2],
            ResourceCard.BRICK: RCARDS_FOR_SETTLEMENT[3],
            ResourceCard.SHEEP: RCARDS_FOR_SETTLEMENT[4]
        },
        "city": {
            ResourceCard.WHEAT: RCARDS_FOR_CITY[0],
            ResourceCard.ORE: RCARDS_FOR_CITY[1],
            ResourceCard.WOOD: RCARDS_FOR_CITY[2],
            ResourceCard.BRICK: RCARDS_FOR_CITY[3],
            ResourceCard.SHEEP: RCARDS_FOR_CITY[4]
        },
        "road": {
            ResourceCard.WHEAT: RCARDS_FOR_ROAD[0],
            ResourceCard.ORE: RCARDS_FOR_ROAD[1],
            ResourceCard.WOOD: RCARDS_FOR_ROAD[2],
            ResourceCard.BRICK: RCARDS_FOR_ROAD[3],
            ResourceCard.SHEEP: RCARDS_FOR_ROAD[4]
        },
        "development_card": {
            ResourceCard.WHEAT: RCARDS_FOR_DCARD[0],
            ResourceCard.ORE: RCARDS_FOR_DCARD[1],
            ResourceCard.WOOD: RCARDS_FOR_DCARD[2],
            ResourceCard.BRICK: RCARDS_FOR_DCARD[3],
            ResourceCard.SHEEP: RCARDS_FOR_DCARD[4]
        }
    }


# Cached resource costs
COSTS: Dict[str, Dict[ResourceCard, int]] = get_rcard_costs()
"""Cached dictionary of resource costs for building actions."""