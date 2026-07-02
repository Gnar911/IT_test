"""Pattern parser for replay command sequences.

Pattern syntax:
    ST          = START
    P           = PAUSE
    SP          = STOP
    R           = RESUME
    L           = SET_LOOP (enable)
    L0          = SET_LOOP (disable)
    SR<n>       = SET_REPEAT(<n>), e.g., SR2, SR5
    F<ids>      = SET_FILTER_MSG, e.g., F100:200:300 (filter CAN IDs 0x100, 0x200, 0x300)
    T<s>:<e>    = SET_TIME_SCOPE, e.g., T0.5:1 (start=50%, end=100% of source span)
    <number>    = sleep duration in seconds, e.g., 0.3, 1, 2.5
    W<status>   = wait for status, e.g., WFINISHED, WPAUSED, WSTOPPED
    X           = EXIT

Examples:
    "ST_0.3_P_1_R_WFINISHED"
        -> START, sleep 0.3s, PAUSE, sleep 1s, RESUME, wait FINISHED

    "ST_1_L_SR2_2_SP"
        -> START, sleep 1s, SET_LOOP(True), SET_REPEAT(2), sleep 2s, STOP

    "F100:200_T0.5:1.0_SR2_ST_WFINISHED"
        -> SET_FILTER_MSG([0x100,0x200]), SET_TIME_SCOPE(0.5,1.0), SET_REPEAT(2), START, wait FINISHED
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class ActionType(Enum):
    """Types of actions in a pattern."""
    START = auto()
    PAUSE = auto()
    STOP = auto()
    RESUME = auto()
    EXIT = auto()
    SET_LOOP = auto()
    SET_REPEAT = auto()
    SET_FILTER_MSG = auto()
    SET_TIME_SCOPE = auto()
    SLEEP = auto()
    WAIT_STATUS = auto()


@dataclass
class PatternAction:
    """A single action parsed from a pattern string."""
    action_type: ActionType
    payload: Any = None

    def __repr__(self) -> str:
        if self.action_type == ActionType.SLEEP:
            return f"SLEEP({self.payload}s)"
        if self.action_type == ActionType.WAIT_STATUS:
            return f"WAIT({self.payload})"
        if self.action_type == ActionType.SET_LOOP:
            return f"SET_LOOP({self.payload})"
        if self.action_type == ActionType.SET_REPEAT:
            return f"SET_REPEAT({self.payload})"
        if self.action_type == ActionType.SET_FILTER_MSG:
            ids = self.payload or []
            return f"SET_FILTER_MSG({','.join(hex(i) for i in ids)})"
        if self.action_type == ActionType.SET_TIME_SCOPE:
            start, end = self.payload or (None, None)
            return f"SET_TIME_SCOPE({start}:{end})"
        return self.action_type.name


# Token patterns (order matters - more specific patterns first)
TOKEN_PATTERNS = [
    # Commands with parameters
    (r"^SR(\d+)$", lambda m: PatternAction(ActionType.SET_REPEAT, int(m.group(1)))),
    (r"^L([01])$", lambda m: PatternAction(ActionType.SET_LOOP, m.group(1) == "1")),
    (r"^F([\dA-Fa-f:]+)$", lambda m: PatternAction(
        ActionType.SET_FILTER_MSG,
        [int(x, 16) if x.startswith("0x") or any(c in x.upper() for c in "ABCDEF") else int(x) 
         for x in m.group(1).split(":") if x]
    )),
    (r"^T([\d.]*):?([\d.]*)$", lambda m: PatternAction(
        ActionType.SET_TIME_SCOPE,
        (float(m.group(1)) if m.group(1) else None, float(m.group(2)) if m.group(2) else None)
    )),
    (r"^W([A-Z_]+)$", lambda m: PatternAction(ActionType.WAIT_STATUS, m.group(1))),
    
    # Simple commands
    (r"^ST$", lambda m: PatternAction(ActionType.START)),
    (r"^SP$", lambda m: PatternAction(ActionType.STOP)),
    (r"^P$", lambda m: PatternAction(ActionType.PAUSE)),
    (r"^R$", lambda m: PatternAction(ActionType.RESUME)),
    (r"^L$", lambda m: PatternAction(ActionType.SET_LOOP, True)),
    (r"^X$", lambda m: PatternAction(ActionType.EXIT)),
    
    # Sleep (numeric value)
    (r"^(\d+\.?\d*)$", lambda m: PatternAction(ActionType.SLEEP, float(m.group(1)))),
]


def parse_pattern(pattern: str) -> list[PatternAction]:
    """Parse a pattern string into a list of actions.
    
    Args:
        pattern: Pattern string like "ST_0.3_P_1_SP"
        
    Returns:
        List of PatternAction objects
        
    Raises:
        ValueError: If pattern contains invalid tokens
    """
    if not pattern or not pattern.strip():
        raise ValueError("Empty pattern")
    
    tokens = pattern.strip().split("_")
    actions: list[PatternAction] = []
    
    for token in tokens:
        token = token.strip()
        if not token:
            continue
            
        matched = False
        for regex, factory in TOKEN_PATTERNS:
            match = re.match(regex, token, re.IGNORECASE)
            if match:
                actions.append(factory(match))
                matched = True
                break
        
        if not matched:
            raise ValueError(f"Invalid token in pattern: '{token}'")
    
    return actions


def pattern_to_name(pattern: str) -> str:
    """Convert a pattern string to a compact canonical scenario name.

    The canonical form keeps the original compact grammar so folder names and
    analyzer inputs stay explicit, e.g.:
      L_ST_1_P_0.5_R_2_SP
      T0.5:1.5_ST_WFINISHED
    """
    def _fmt_num(v: float) -> str:
        s = f"{float(v):.6f}".rstrip("0").rstrip(".")
        return s if s else "0"

    try:
        actions = parse_pattern(pattern)
    except ValueError:
        return str(pattern or "").strip()

    tokens: list[str] = []
    for action in actions:
        if action.action_type == ActionType.START:
            tokens.append("ST")
        elif action.action_type == ActionType.PAUSE:
            tokens.append("P")
        elif action.action_type == ActionType.STOP:
            tokens.append("SP")
        elif action.action_type == ActionType.RESUME:
            tokens.append("R")
        elif action.action_type == ActionType.EXIT:
            tokens.append("X")
        elif action.action_type == ActionType.SLEEP:
            tokens.append(_fmt_num(float(action.payload or 0.0)))
        elif action.action_type == ActionType.WAIT_STATUS:
            status = str(action.payload or "").upper()
            if status == "FINISH":
                status = "FINISHED"
            tokens.append(f"W{status}")
        elif action.action_type == ActionType.SET_LOOP:
            enabled = bool(action.payload) if action.payload is not None else True
            tokens.append("L" if enabled else "L0")
        elif action.action_type == ActionType.SET_REPEAT:
            tokens.append(f"SR{int(action.payload or 1)}")
        elif action.action_type == ActionType.SET_FILTER_MSG:
            ids = [int(v) for v in (action.payload or [])]
            tokens.append("F" + ":".join(str(v) for v in ids))
        elif action.action_type == ActionType.SET_TIME_SCOPE:
            start, end = action.payload or (None, None)
            s = "" if start is None else _fmt_num(float(start))
            e = "" if end is None else _fmt_num(float(end))
            tokens.append(f"T{s}:{e}")

    return "_".join(tokens)


def validate_pattern(pattern: str) -> tuple[bool, str]:
    """Validate a pattern string.
    
    Args:
        pattern: Pattern string to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        actions = parse_pattern(pattern)
        if not actions:
            return False, "Pattern produced no actions"
        return True, ""
    except ValueError as e:
        return False, str(e)


# Common test patterns for parametrization
BASIC_PATTERNS = [
    "ST_WFINISHED",                          # Simple start and wait
    "ST_0.3_SP",                             # Start, brief run, stop
    "ST_0.5_P_1_R_WFINISHED",                # Pause/resume flow
    "ST_0.3_P_0.5_SP",                       # Pause then stop
    "L_ST_2_SP",                             # Loop mode with timed stop
    "SR2_ST_WFINISHED",                      # Repeat 2 cycles
    "SR3_ST_WFINISHED",                      # Repeat 3 cycles
]

COMBO_PATTERNS = [
    "L_SR2_ST_3_SP",                         # Loop + repeat + timed stop
    "L_ST_1_P_1_R_2_SP",                     # Loop + pause/resume + stop
    "SR2_ST_0.5_P_1_R_WFINISHED",            # Repeat + pause/resume
]

FILTER_SCOPE_PATTERNS = [
    "F100_ST_WFINISHED",                     # Filter single ID
    "F100:200:300_ST_WFINISHED",             # Filter multiple IDs
    "T0.5:1.5_ST_WFINISHED",                 # Time scope
    "F100_T0.5:1.5_ST_WFINISHED",            # Filter + scope
    "F100_T0.5:1.5_SR2_ST_WFINISHED",        # Filter + scope + repeat
]

STRESS_PATTERNS = [
    "L_ST_10_SP",                            # 10 second loop run
    "SR5_ST_WFINISHED",                      # 5 repeat cycles
    "L_ST_1_P_0.5_R_1_P_0.5_R_2_SP",         # Multiple pause/resume
]

ALL_PATTERNS = BASIC_PATTERNS + COMBO_PATTERNS + FILTER_SCOPE_PATTERNS