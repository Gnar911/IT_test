"""Pattern parser for sender command sequences (priority/TTA scheduler tests).

IMPORTANT: Sender patterns use DIRECT CAN IDs (not ordinal indices like replay).
IDs can be decimal (100, 200) or hex (0x100, 0x200, 0xABC).

Pattern syntax:
    RA                  = RESUME_ALL (start all scheduled messages)
    PA                  = PAUSE_ALL (pause all, end session)
    R<ch>:<id>          = RESUME (single message), e.g., R0:100, R1:0x200
    P<ch>:<id>          = PAUSE (single message)
    A<ch>:<id>:<p>      = ADD message with direct CAN ID and period in ms,
                          e.g., A0:100:1, A1:0xABC:3
    RM<ch>:<id>         = REMOVE message
    UP<ch>:<id>:<p>     = UPDATE_PERIOD, e.g., UP0:100:0.01 (period in seconds)
    UD<ch>:<id>:<data>  = UPDATE_DATA, e.g., UD0:100:DEADBEEF
    RC<ch>              = REGISTER_CHANNEL, e.g., RC0, RC1
    UC<ch>              = UNREGISTER_CHANNEL
    CLR                 = CLEAR (reset all scheduled messages)
    X                   = EXIT
    <number>            = sleep duration in seconds, e.g., 0.1, 0.5, 1
    W<status>           = wait for status, e.g., WFINISHED, WACTIVE, WPAUSED

CAN ID notation:
    100             = 100 decimal
    0x100           = 256 decimal (0x100 hex)
    256:512:0xFF    = Mix decimal and hex: 256, 512, 255

Examples:
    "RC0_A0:100:1_A0:200:2_RA_1_PA"
        -> REGISTER_CHANNEL(0), ADD(ch=0, id=100, period_ms=1),
           ADD(ch=0, id=200, period_ms=2),
           RESUME_ALL, sleep 1s, PAUSE_ALL

    "RC0_A0:0x100:1_A0:0x200:3_RA_0.5_P0:0x100_PA"
        -> REGISTER_CHANNEL(0), ADD(ch=0, id=0x100, period_ms=1),
           ADD(ch=0, id=0x200, period_ms=3),
           RESUME_ALL, sleep 0.5s, PAUSE single msg 0x100, PAUSE_ALL

    "RC0_A0:100:1_RA_0.1_UP0:100:0.02_1_PA"
        -> Register ch 0, add msg 100 at 1ms, resume all, sleep 0.1s,
           update period to 20ms, sleep 1s, pause all

Note: Unlike replay patterns (F1=1st unique ID, F2=2nd unique ID),
sender patterns use direct IDs. You must know which CAN IDs you want to schedule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class SenderActionType(Enum):
    """Types of actions in a sender pattern."""
    REGISTER_CHANNEL = auto()
    UNREGISTER_CHANNEL = auto()
    ADD = auto()
    REMOVE = auto()
    RESUME = auto()
    RESUME_ALL = auto()
    PAUSE = auto()
    PAUSE_ALL = auto()
    UPDATE_PERIOD = auto()
    UPDATE_DATA = auto()
    CLEAR = auto()
    SLEEP = auto()
    WAIT_STATUS = auto()


@dataclass
class SenderPatternAction:
    """A single action parsed from a sender pattern string."""
    action_type: SenderActionType
    payload: Any = None

    def __repr__(self) -> str:
        if self.action_type == SenderActionType.SLEEP:
            return f"SLEEP({self.payload}s)"
        if self.action_type == SenderActionType.WAIT_STATUS:
            return f"WAIT({self.payload})"
        if self.action_type == SenderActionType.REGISTER_CHANNEL:
            return f"RC({self.payload})"
        if self.action_type == SenderActionType.UNREGISTER_CHANNEL:
            return f"UC({self.payload})"
        if self.action_type == SenderActionType.ADD:
            ch, can_id, period_s = self.payload or (None, None, None)
            return f"ADD(ch={ch}, id={hex(can_id) if can_id else 'None'}, period={period_s}s)"
        if self.action_type == SenderActionType.REMOVE:
            ch, can_id = self.payload or (None, None)
            return f"REMOVE(ch={ch}, id={hex(can_id) if can_id else 'None'})"
        if self.action_type == SenderActionType.RESUME:
            ch, can_id = self.payload or (None, None)
            return f"RESUME(ch={ch}, id={hex(can_id) if can_id else 'None'})"
        if self.action_type == SenderActionType.PAUSE:
            ch, can_id = self.payload or (None, None)
            return f"PAUSE(ch={ch}, id={hex(can_id) if can_id else 'None'})"
        if self.action_type == SenderActionType.UPDATE_PERIOD:
            ch, can_id, period = self.payload or (None, None, None)
            return f"UPDATE_PERIOD(ch={ch}, id={hex(can_id) if can_id else 'None'}, period={period}s)"
        if self.action_type == SenderActionType.UPDATE_DATA:
            ch, can_id, data = self.payload or (None, None, None)
            return f"UPDATE_DATA(ch={ch}, id={hex(can_id) if can_id else 'None'}, data={data})"
        return self.action_type.name


# Token patterns (order matters - more specific patterns first)
TOKEN_PATTERNS = [
    # Commands with ch:id:param format (supports 0x prefix for hex)
    (r"^UP(\d+):(0x[0-9A-Fa-f]+|\d+):([\d.]+)$", 
     lambda m: SenderPatternAction(
         SenderActionType.UPDATE_PERIOD, 
         (int(m.group(1)), int(m.group(2), 16 if m.group(2).startswith('0x') else 10), float(m.group(3)))
     )),
    (r"^UD(\d+):(0x[0-9A-Fa-f]+|\d+):([A-Fa-f0-9]+)$",
     lambda m: SenderPatternAction(
         SenderActionType.UPDATE_DATA,
         (int(m.group(1)), int(m.group(2), 16 if m.group(2).startswith('0x') else 10), m.group(3))
     )),
    (r"^A(\d+):(0x[0-9A-Fa-f]+|\d+):(\d+\.?\d*)$",
     lambda m: SenderPatternAction(
         SenderActionType.ADD,
         (
             int(m.group(1)),
             int(m.group(2), 16 if m.group(2).startswith('0x') else 10),
             float(m.group(3)) / 1000.0,
         )
     )),
    
    # Commands with ch:id format (supports 0x prefix for hex)
    (r"^RM(\d+):(0x[0-9A-Fa-f]+|\d+)$",
     lambda m: SenderPatternAction(
         SenderActionType.REMOVE,
         (int(m.group(1)), int(m.group(2), 16 if m.group(2).startswith('0x') else 10))
     )),
    (r"^R(\d+):(0x[0-9A-Fa-f]+|\d+)$",
     lambda m: SenderPatternAction(
         SenderActionType.RESUME,
         (int(m.group(1)), int(m.group(2), 16 if m.group(2).startswith('0x') else 10))
     )),
    (r"^P(\d+):(0x[0-9A-Fa-f]+|\d+)$",
     lambda m: SenderPatternAction(
         SenderActionType.PAUSE,
         (int(m.group(1)), int(m.group(2), 16 if m.group(2).startswith('0x') else 10))
     )),
    
    # Commands with channel only
    (r"^RC(\d+)$", lambda m: SenderPatternAction(SenderActionType.REGISTER_CHANNEL, int(m.group(1)))),
    (r"^UC(\d+)$", lambda m: SenderPatternAction(SenderActionType.UNREGISTER_CHANNEL, int(m.group(1)))),
    
    # Simple commands
    (r"^RA$", lambda m: SenderPatternAction(SenderActionType.RESUME_ALL)),
    (r"^PA$", lambda m: SenderPatternAction(SenderActionType.PAUSE_ALL)),
    (r"^CLR$", lambda m: SenderPatternAction(SenderActionType.CLEAR)),
    
    # Wait for status
    (r"^W([A-Z_]+)$", lambda m: SenderPatternAction(SenderActionType.WAIT_STATUS, m.group(1))),
    
    # Sleep (numeric value)
    (r"^(\d+\.?\d*)$", lambda m: SenderPatternAction(SenderActionType.SLEEP, float(m.group(1)))),
]


def parse_sender_pattern(pattern: str) -> list[SenderPatternAction]:
    """Parse a sender pattern string into a list of actions.
    
    Args:
        pattern: Pattern string like "RC0_A0:100:1_RA_1_PA"
        
    Returns:
        List of SenderPatternAction objects
        
    Raises:
        ValueError: If pattern contains invalid tokens
    """
    if not pattern or not pattern.strip():
        raise ValueError("Empty pattern")
    
    tokens = pattern.strip().split("_")
    actions: list[SenderPatternAction] = []
    
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
            raise ValueError(f"Invalid token in sender pattern: '{token}'")
    
    return actions


def sender_pattern_to_name(pattern: str) -> str:
    """Convert a sender pattern string to a compact canonical scenario name.

    The canonical form keeps the original compact grammar so folder names and
    analyzer inputs stay explicit, e.g.:
            RC0_A0:100:1_RA_0.5_PA
            A0:100:1_A0:200:2_RA_1_P0:100_1_PA
    """
    def _fmt_num(v: float) -> str:
        s = f"{float(v):.6f}".rstrip("0").rstrip(".")
        return s if s else "0"

    try:
        actions = parse_sender_pattern(pattern)
    except ValueError:
        return str(pattern or "").strip()

    tokens: list[str] = []
    for action in actions:
        if action.action_type == SenderActionType.REGISTER_CHANNEL:
            tokens.append(f"RC{action.payload}")
        elif action.action_type == SenderActionType.UNREGISTER_CHANNEL:
            tokens.append(f"UC{action.payload}")
        elif action.action_type == SenderActionType.ADD:
            ch, can_id, period_s = action.payload or (None, None, None)
            period_ms = _fmt_num(float(period_s or 0.0) * 1000.0)
            tokens.append(f"A{ch}:{hex(can_id) if can_id else '0'}:{period_ms}")
        elif action.action_type == SenderActionType.REMOVE:
            ch, can_id = action.payload or (None, None)
            tokens.append(f"RM{ch}:{hex(can_id) if can_id else '0'}")
        elif action.action_type == SenderActionType.RESUME:
            ch, can_id = action.payload or (None, None)
            tokens.append(f"R{ch}:{hex(can_id) if can_id else '0'}")
        elif action.action_type == SenderActionType.PAUSE:
            ch, can_id = action.payload or (None, None)
            tokens.append(f"P{ch}:{hex(can_id) if can_id else '0'}")
        elif action.action_type == SenderActionType.UPDATE_PERIOD:
            ch, can_id, period = action.payload or (None, None, None)
            tokens.append(f"UP{ch}:{hex(can_id) if can_id else '0'}:{_fmt_num(float(period or 0))}")
        elif action.action_type == SenderActionType.UPDATE_DATA:
            ch, can_id, data = action.payload or (None, None, None)
            tokens.append(f"UD{ch}:{hex(can_id) if can_id else '0'}:{data or '0'}")
        elif action.action_type == SenderActionType.RESUME_ALL:
            tokens.append("RA")
        elif action.action_type == SenderActionType.PAUSE_ALL:
            tokens.append("PA")
        elif action.action_type == SenderActionType.CLEAR:
            tokens.append("CLR")
        elif action.action_type == SenderActionType.SLEEP:
            tokens.append(_fmt_num(float(action.payload or 0.0)))
        elif action.action_type == SenderActionType.WAIT_STATUS:
            status = str(action.payload or "").upper()
            tokens.append(f"W{status}")

    return "_".join(tokens)


def validate_sender_pattern(pattern: str) -> tuple[bool, str]:
    """Validate a sender pattern string.
    
    Args:
        pattern: Pattern string to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        actions = parse_sender_pattern(pattern)
        if not actions:
            return False, "Pattern produced no actions"
        return True, ""
    except ValueError as e:
        return False, str(e)


# Common test patterns for parametrization (using DIRECT CAN IDs, not ordinals)
BASIC_SENDER_PATTERNS = [
    "RC0_A0:100:1_RA_0.1_PA",                      # Register ch0, add ID=100 at 1ms, resume all, pause
    "RC0_A0:100:1_A0:200:2_RA_0.5_PA",             # Register ch0, add ID=100 and 200, run 0.5s
    "RC0_A0:100:1_RA_0.1_P0:100_0.1_R0:100_PA",    # Single message pause/resume cycle
]

MIXED_COMMAND_PATTERNS = [
    "RC0_A0:0x100:1_A0:0x200:3_RA_0.2_PA",          # Using hex notation: 0x100=256, 0x200=512
    "RC0_A0:100:1_RA_0.1_UP0:100:0.02_0.1_PA",      # Update period of ID=100 to 20ms
    "RC0_A0:256:1_A0:512:3_RA_0.1_P0:256_0.1_PA",   # Decimal notation (256, 512 = 0x100, 0x200)
]

STRESS_SENDER_PATTERNS = [
    "RC0_A0:100:1_A0:200:2_A0:300:5_RA_1_PA",          # 3 direct CAN IDs, 1s run
    "RC0_A0:100:1_RA_0.05_P0:100_0.05_R0:100_0.05_PA", # Rapid pause/resume on ID=100
    "RC0_A0:100:1_A0:200:2_RA_0.5_RM0:100_0.3_PA",     # Remove ID=100 mid-session
]

CHANNEL_OPS_PATTERNS = [
    "RC0_RC1_A0:100:1_A1:200:3_RA_0.2_PA_UC0_UC1", # Multi-channel: ch0→ID100, ch1→ID200
    "RC0_A0:0x123:1_A0:0x456:3_RA_0.1_PA_UC0",     # Hex IDs: 0x123, 0x456
]

ALL_SENDER_PATTERNS = (
    BASIC_SENDER_PATTERNS + 
    MIXED_COMMAND_PATTERNS + 
    STRESS_SENDER_PATTERNS + 
    CHANNEL_OPS_PATTERNS
)