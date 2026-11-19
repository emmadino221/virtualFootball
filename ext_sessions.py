"""Per-licence extension sessions for the virtual football bot.

Each licence key has its own reported state and its own command queue, so one member's
extension never receives another member's Start, Stop or stake change, and the website
dashboard shows each member only their own session. Kept in memory: the extension reports
its full state every few seconds, so a restart repopulates it within one sync.
"""
import math
import threading
import time
import uuid

MODES = ("OU", "O25", "UN", "1X2", "GG", "NG")
COMMAND_TYPES = ("START", "STOP", "STAKE", "TP", "SL", "MODE", "RESET")
ONLINE_SECONDS = 15          # the extension syncs every 3 seconds
MAX_QUEUED = 20
DELIVERED_KEPT = 10
LIMITS = {"STAKE": (1, 1_000_000), "TP": (0, 100_000_000), "SL": (0, 100_000_000)}

# Fields the extension may report, with their types. Anything else is ignored.
NUMBER_FIELDS = ("baseStake", "takeProfit", "stopLoss", "totalProfit", "localLossStreak", "streakLoss",
                 "winStreak", "maxWinStreak", "maxLossStreakRec", "maxLossStreak", "maxStake", "minOdds")


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and abs(number) <= 1e12 else None


def _text(value, limit=40):
    return str(value)[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def clean_state(data):
    """Keep only known fields with sane types from what an extension reports."""
    state = {}
    if isinstance(data.get("botEnabled"), bool):
        state["botEnabled"] = data["botEnabled"]
    if data.get("bettingMode") in MODES:
        state["bettingMode"] = data["bettingMode"]
    for field in NUMBER_FIELDS:
        if field in data:
            number = _number(data[field])
            if number is not None:
                state[field] = number
    if "pendingBet" in data:
        bet = data["pendingBet"]
        state["pendingBet"] = None
        if isinstance(bet, dict) and _number(bet.get("stake")) is not None:
            state["pendingBet"] = {"stake": _number(bet.get("stake")), "week": _text(bet.get("week")),
                                   "mode": bet.get("mode") if bet.get("mode") in MODES else None}
    version = _text(data.get("extensionVersion"), 20)
    if version:
        state["extensionVersion"] = version
    return state


def validate_command(kind, value=None):
    """Return a clean command, or raise ValueError with a message for the user."""
    kind = str(kind or "").upper()
    if kind not in COMMAND_TYPES:
        raise ValueError("Unknown command.")
    command = {"type": kind}
    if kind in LIMITS:
        number = _number(value)
        low, high = LIMITS[kind]
        if number is None or not low <= number <= high:
            raise ValueError(f"Enter an amount from {low:,} to {high:,}.")
        command["value"] = round(number, 2)
    elif kind == "MODE":
        mode = str(value or "").upper()
        if mode not in MODES:
            raise ValueError("Choose a supported betting mode.")
        command["value"] = mode
    return command


class Sessions:
    def __init__(self, valid_keys, clock=time.time, extra_valid=None):
        self.valid_keys = set(valid_keys)
        # Keys issued from the website (licences.py) are checked here, including their expiry.
        self.extra_valid = extra_valid
        self.clock = clock
        self.lock = threading.Lock()
        self.states = {}       # key -> reported state plus lastSeen
        self.queues = {}       # key -> commands waiting for the next sync
        self.delivered = {}    # key -> recently delivered commands
        self.chat_keys = {}    # Telegram chat id -> keys whose extension registered that chat

    def valid(self, key):
        if not isinstance(key, str):
            return False
        return key in self.valid_keys or bool(self.extra_valid and self.extra_valid(key))

    def sync(self, key, data, chat_id=None):
        """Record an extension's report and hand over its queued commands."""
        with self.lock:
            state = self.states.setdefault(key, {})
            state.update(clean_state(data if isinstance(data, dict) else {}))
            state["lastSeen"] = self.clock()
            if chat_id:
                self.chat_keys.setdefault(chat_id, set()).add(key)
            commands = self.queues.pop(key, [])
            if commands:
                now = self.clock()
                done = [{**c, "deliveredAt": now} for c in commands]
                self.delivered[key] = (self.delivered.get(key, []) + done)[-DELIVERED_KEPT:]
            # The extension only reads type and value.
            return [{k: v for k, v in c.items() if k in ("type", "value")} for c in commands]

    def queue(self, key, kind, value=None, source="dashboard"):
        command = validate_command(kind, value)
        with self.lock:
            queue = self.queues.setdefault(key, [])
            # A newer Start/Stop, mode or amount replaces an undelivered one of the same type.
            queue[:] = [c for c in queue if c["type"] != command["type"]
                        and not ({c["type"], command["type"]} == {"START", "STOP"})]
            if len(queue) >= MAX_QUEUED:
                raise ValueError("Too many commands are waiting. Check that the extension is connected.")
            entry = {**command, "id": uuid.uuid4().hex[:12], "queuedAt": self.clock(), "source": source}
            queue.append(entry)
            return entry

    def keys_for_chat(self, chat_id, admin=False):
        """Extensions a Telegram chat controls: those that registered it, or every known one for an admin chat."""
        with self.lock:
            linked = set(self.chat_keys.get(chat_id, set()))
            if not linked and admin:
                linked = set(self.states)
            return sorted(linked)

    def status(self, key):
        with self.lock:
            state = dict(self.states.get(key, {}))
            last_seen = state.pop("lastSeen", None)
            return {
                "state": state,
                "lastSeen": last_seen,
                "online": last_seen is not None and self.clock() - last_seen < ONLINE_SECONDS,
                "pending": [dict(c) for c in self.queues.get(key, [])],
                "delivered": [dict(c) for c in self.delivered.get(key, [])][::-1],
            }
