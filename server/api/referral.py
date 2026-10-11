"""Referral codes and free processing credits.

A referral program is two questions - who invited whom, and what it was worth -
and everything else here exists to answer them without letting either be
faked:

  * an account is one owner string (`u:<sub>` or a device id), the same
    identity the jobs and history already hang off;
  * a code is that owner's, generated once and looked up by its own row;
  * a redemption is keyed by the REFEREE, so a phone can only ever cash one
    code - a conditional insert, not a check-then-write, because two taps on a
    flaky connection are the normal way a check-then-write loses;
  * credits are integers on the owner's row, added with `ADD` so two
    redemptions racing cannot read the same balance and write back the same
    number.

The logic is storage-agnostic on purpose: `handler.py` passes a DynamoDB
adapter, `local_server.py` passes the in-memory one below, and both therefore
referee identically. That parity is the whole reason this is a module and not
two copies - the feedback clip route is the thing that drifts when it is not.

Credits are only SPENT when `REQUIRE_CREDITS=1`. Left off - the default - the
program still grants and displays a balance but never refuses a clip, so
turning it on is a deployment decision rather than a surprise regression for
phones already in the field.
"""
from __future__ import annotations

import os
import secrets
import threading
from typing import Any

# No O/0/I/1: a code is meant to be read aloud or typed off a screenshot, and
# every one of those glyph pairs is a support ticket.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 8

# A clause-shaped row id scheme. One table, no GSI: `acct#` the owner's
# balance and code, `code#` the reverse lookup, `ref#` one redemption.
ACCT = "acct#"
CODE = "code#"
REF = "ref#"


def config() -> dict[str, Any]:
    """The knobs, read at call time so a test can move them without an import."""
    return {
        "starting": int(os.environ.get("STARTING_CREDITS", "3")),
        "reward": int(os.environ.get("REFERRAL_REWARD", "3")),
        "welcome": int(os.environ.get("WELCOME_CREDITS", "1")),
        "required": os.environ.get("REQUIRE_CREDITS", "0") == "1",
    }


def normalize(code: str) -> str:
    """Uppercase and drop anything not alphanumeric, so `ab-12 34` works."""
    return "".join(c for c in (code or "").upper() if c.isalnum())


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


class MemoryStore:
    """The interface, in a dict. Used by the local server and by tests."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._rows.get(key)
            return dict(row) if row else None

    def put_new(self, item: dict) -> bool:
        with self._lock:
            if item["id"] in self._rows:
                return False
            self._rows[item["id"]] = dict(item)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._rows.pop(key, None)

    def bump(self, key: str, adds: dict[str, int],
             init: dict[str, Any]) -> dict:
        with self._lock:
            row = self._rows.setdefault(key, {"id": key})
            for name, value in init.items():
                row.setdefault(name, value)
            for name, value in adds.items():
                row[name] = int(row.get(name, 0)) + value
            return dict(row)


def _account(store, owner: str) -> dict | None:
    return store.get(ACCT + owner)


def ensure(store, owner: str) -> dict:
    """The owner's row, created with a starting balance and a code if new."""
    row = _account(store, owner)
    if row:
        return row
    cfg = config()
    for _ in range(6):
        code = new_code()
        row = {"id": ACCT + owner, "owner": owner, "code": code,
               "credits": cfg["starting"], "referrals": 0, "earned": 0}
        if not store.put_new(row):
            # Someone else created it between the read and here. Theirs wins.
            return _account(store, owner) or row
        if store.put_new({"id": CODE + code, "owner": owner, "code": code}):
            return row
        # 32^8 makes this branch a formality, but a formality that would
        # otherwise leave an orphaned account pointing at someone else's code.
        store.delete(ACCT + owner)
    raise RuntimeError("could not allocate a unique referral code")


def status(store, owner: str) -> dict:
    """What the invite screen needs: the code, the balance, the tally."""
    cfg = config()
    row = ensure(store, owner)
    return {
        "code": row.get("code", ""),
        "credits": int(row.get("credits", 0)),
        "referrals": int(row.get("referrals", 0)),
        "earned": int(row.get("earned", 0)),
        "reward": cfg["reward"],
        "welcome": cfg["welcome"],
        "required": cfg["required"],
    }


def redeem(store, owner: str, raw_code: str) -> tuple[int, dict]:
    """Cash a code. One redemption per owner, ever."""
    cfg = config()
    code = normalize(raw_code)
    if not code:
        return 400, {"error": "a referral code is required"}
    mine = ensure(store, owner)
    if normalize(mine.get("code", "")) == code:
        return 400, {"error": "that is your own code"}
    referrer_row = store.get(CODE + code)
    if not referrer_row:
        return 404, {"error": "that code is not recognised"}
    referrer = referrer_row.get("owner") or ""
    if not referrer or referrer == owner:
        return 400, {"error": "that is your own code"}
    record = {"id": REF + owner, "referrer": referrer, "referee": owner,
              "code": code, "reward": cfg["reward"]}
    if not store.put_new(record):
        return 409, {"error": "you have already redeemed a code"}
    # The referrer earns; the referee gets a welcome so a first clip is free
    # even where REQUIRE_CREDITS is on.
    store.bump(ACCT + referrer,
               {"credits": cfg["reward"], "referrals": 1,
                "earned": cfg["reward"]},
               {"credits": cfg["starting"], "referrals": 0, "earned": 0,
                "owner": referrer})
    row = store.bump(ACCT + owner, {"credits": cfg["welcome"]},
                     {"referrals": 0, "earned": 0,
                      "credits": cfg["starting"], "owner": owner})
    out = status(store, owner)
    out["redeemed"] = True
    out["rewarded"] = cfg["reward"]
    _ = row
    return 200, out


def charge(store, owner: str) -> tuple[bool, int]:
    """Take one credit for a clip, if the deployment charges for clips.

    Returns (allowed, balance). When `REQUIRE_CREDITS` is off this only reads
    the balance - the program is live but nothing is refused.
    """
    cfg = config()
    row = ensure(store, owner)
    balance = int(row.get("credits", 0))
    if not cfg["required"]:
        return True, balance
    if balance < 1:
        return False, balance
    row = store.bump(ACCT + owner, {"credits": -1},
                     {"credits": cfg["starting"], "referrals": 0,
                      "earned": 0, "owner": owner})
    return True, int(row.get("credits", 0))
