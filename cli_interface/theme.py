"""Colours, log-level styles, spinner frames and the key hint text. Internal: not part of the public API."""
from __future__ import annotations

# One Half Dark palette — orange primary accent
_BG      = "#282c34"
_SURFACE = "#2c2f3a"
_PANEL   = "#353a45"
_FG      = "#dcdfe4"
_ORANGE  = "#d19a66"
_CYAN    = "#56b6c2"
_GREEN   = "#98c379"
_YELLOW  = "#e5c07b"
_RED     = "#e06c75"
_DIM_FG  = "#7a8194"

# Rich styles for DisplayPanel.log, keyed by level name (upper case).
LEVEL_STYLES: dict[str, str] = {
    "DEBUG":    f"dim {_CYAN}",
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    f"bold {_RED}",
    "CRITICAL": f"bold {_FG} on {_RED}",
}

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# The two-line key hint under the nav bar (Rich markup; framework-authored, so markup is safe here).
_HINT_TEXT = (
    f"  [{_ORANGE}]↑ ↓[/]  [{_FG}]navigate[/]"
    f"   [{_ORANGE}]Enter[/]  [{_FG}]select[/]"
    f"   [{_ORANGE}]Esc[/]  [{_FG}]back[/]"
    f"   [{_DIM_FG}]·[/]  type a shortcut + Enter\n"
    f"  [{_ORANGE}]q + Enter[/]  [{_FG}]quit[/]"
    f"   [{_ORANGE}]PgUp / PgDn[/]  [{_FG}]scroll output[/]"
    f"   [{_ORANGE}]Home / End[/]  [{_FG}]top / bottom[/]"
)
