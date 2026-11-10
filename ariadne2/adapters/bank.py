"""His bank, read-only: balances, what's coming up, and the numbers for her plans.

Through SimpleFIN Bridge (simplefin.org): he makes a setup token on the Bridge
and pastes it in Settings > Models > Bank; it's claimed once for an Access URL
(read-only by design: SimpleFIN has no way to move money, and neither does she),
kept like his API keys in a 0600 file and never shown or logged. Data comes in
once a day (the Bridge refreshes daily and asks for 24 requests a day or fewer),
at a random minute, overlapping the last fetch by five days.

Everything stays on this machine (~/.local/share/ariadne2/bank/): accounts, every
transaction seen (so the history outgrows SimpleFIN's 90-day window), his own
bills, and what she's noticed. Recurring bills and paydays are found in the
history (same payee, a steady weekly, fortnightly or monthly rhythm); he can add
his own and tell her a found one isn't a bill. From those, the widget shows what
comes out over the next weeks, what's safe to spend before payday, and warns
when a bill would take the balance below zero; her verbs give the same and a
forecast for "can I afford this".
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import os
import random
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .base import Adapter, AdapterError, Verb

log = logging.getLogger("ariadne2.adapters.bank")

SYNC_EVERY = 24 * 3600          # the Bridge refreshes once a day
OVERLAP = 5 * 86400             # each fetch re-reads the last five days (late postings)
FIRST = 90 * 86400              # the first: as far back as SimpleFIN goes per request
MIN_REFRESH = 3600              # his "refresh" at most hourly: the Bridge disables over-eager tokens
SOON_DAYS = 3                   # a bill this close is announced (bill_soon)
HTTP_TIMEOUT = 30
# Bridge sits behind Cloudflare, which turns Python's own User-Agent away
# with a 403 (error 1010) that looks just like a used token.
AGENT = "ariadne2 (+https://github.com/nonmenacingsheep/ariadne)"
DEBT = re.compile(r"credit|card|visa|mastercard|amex|discover|loan|mortgage|line of credit", re.I)
KINDS = (("savings", re.compile(r"saving|money market|\bshare\b(?! draft)", re.I)),
         ("checking", re.compile(r"checking|chequing|share draft|spending", re.I)),
         ("credit", re.compile(r"credit|card|visa|mastercard|amex|discover", re.I)),
         ("loan", re.compile(r"loan|mortgage", re.I)))
# A subscription (a service, by name) vs a bill (rent, power, phone): the widget
# lists them apart. Anything else charging the same small amount monthly counts
# as a subscription too.
SUBS = re.compile(r"netflix|hulu|disney|spotify|youtube|crunchyroll|webtoon|discord|nitro|microsoft|xbox|"
                  r"playstation|nintendo|apple\.com|icloud|instagra|patreon|twitch|prime video|amazon prime|"
                  r"audible|kindle|anthropic|claude|openai|chatgpt|midjourney|github|adobe|dropbox|rocket money|"
                  r"lifetime|a\+e|paramount|peacock|hbo|funimation|pandora|tidal|duolingo|vpn|proton|google one",
                  re.I)
BILLS = re.compile(r"\brent\b|electric|power|energy|water|sewer|utilit|insurance|geico|progressive|state farm|"
                   r"verizon|at&t|t-mobile|tmobile|mint mobile|comcast|xfinity|spectrum|internet|loan|mortgage|"
                   r"tuition|daycare|child ?care", re.I)
# Money moved between his own accounts (round-ups, overdraft cover, to savings):
# neither spending nor a bill.
INTERNAL = re.compile(r"\btransfer (to|from) (s(xx)?\d|savings|checking|share)|change it", re.I)


class BankError(Exception):
    """Plain English, safe to show him."""


# ---- SimpleFIN --------------------------------------------------------------------

def _blocked(e: urllib.error.HTTPError) -> bool:
    """Cloudflare's own refusal, not SimpleFIN's: the request never reached it."""
    try:
        return b"error code: 10" in (e.read(64) or b"")
    except Exception:
        return False


def claim(token: str, opener=urllib.request.urlopen) -> str:
    """A setup token (base64 of a one-time claim URL) -> the Access URL."""
    try:
        url = base64.b64decode(token.strip() + "=" * (-len(token.strip()) % 4)).decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError):
        raise BankError("that doesn't look like a SimpleFIN setup token")
    if not url.startswith("https://"):
        raise BankError("that doesn't look like a SimpleFIN setup token")
    req = urllib.request.Request(url, data=b"", method="POST", headers={"Content-Length": "0", "User-Agent": AGENT})
    try:
        with opener(req, timeout=HTTP_TIMEOUT) as r:
            access = r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        if _blocked(e):
            raise BankError("SimpleFIN's firewall turned the request away (the token wasn't used; try again later)")
        if e.code == 403:
            raise BankError("SimpleFIN says that setup token was already used or doesn't exist. If you didn't "
                            "use it yourself, someone else may have: disable it at bridge.simplefin.org.")
        raise BankError(f"SimpleFIN refused the token ({e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BankError(f"couldn't reach SimpleFIN ({e.__class__.__name__})")
    if not access.startswith("https://"):
        raise BankError("SimpleFIN didn't hand back an access link")
    return access


def fetch(access: str, start: float | None = None, end: float | None = None,
          opener=urllib.request.urlopen) -> dict:
    """GET {root}/accounts (protocol version 2), the credentials in the Access URL sent as Basic auth."""
    p = urllib.parse.urlsplit(access)
    if p.scheme != "https" or not p.hostname:
        raise BankError("the saved SimpleFIN link is broken; connect the bank again")
    host = p.hostname + (f":{p.port}" if p.port else "")
    params = [("version", "2"), ("pending", "1")]
    if start is not None:
        params.append(("start-date", str(int(start))))
    if end is not None:
        params.append(("end-date", str(int(end))))
    url = urllib.parse.urlunsplit(("https", host, p.path.rstrip("/") + "/accounts", urllib.parse.urlencode(params), ""))
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    if p.username:
        cred = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
        req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())
    try:
        with opener(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if _blocked(e):
            raise BankError("SimpleFIN's firewall turned the request away; trying again later")
        if e.code == 403:
            raise BankError("SimpleFIN turned the saved access down (revoked, or the token was disabled). "
                            "Connect the bank again in Settings.")
        if e.code == 402:
            raise BankError("SimpleFIN says payment is needed on your Bridge account")
        raise BankError(f"SimpleFIN said {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BankError(f"couldn't reach SimpleFIN ({e.__class__.__name__})")
    except ValueError:
        raise BankError("SimpleFIN sent something that wasn't JSON")


# ---- the sums ---------------------------------------------------------------------

def _num(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _day(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(float(ts)).date()


_NOISE = re.compile(r"\b(pos|ach|debit|credit|purchase|payment|pmt|recurring|card|online|web|www|com|inc|llc|"
                    r"co|corp|ltd|des|id|indn|ppd|ccd|web id|xx+|ref|trans|transaction)\b")


def payee(desc: str) -> str:
    """A transaction's payee as a key: 'NETFLIX.COM 866-579-7172 CA' -> 'netflix'."""
    s = (desc or "").lower()
    s = re.sub(r"[#*@/\\]|\d+", " ", s)
    s = _NOISE.sub(" ", s)
    words = re.findall(r"[a-z&']{2,}", s)
    while len(words) > 1 and len(words[-1]) == 2:      # a trailing state code: '... ca'
        words.pop()
    return " ".join(words[:3])


_LEAD = re.compile(r"^(ach withdrawal company:|online banking (withdrawal|deposit)|payment to|"
                   r"pos (purchase|debit)|debit card purchase|recurring payment)\s*", re.I)


def nice(desc: str) -> str:
    """A description fit to show: 'Discord* Nitromo ***X 444 DE Haro Street' -> 'Discord Nitromo'."""
    s = re.split(r"\s\*{2,}|\s\d+\s|\s\d{3,}|\s{2,}|\s(?:entry|indn|des|id):", (desc or "").strip(), flags=re.I)[0]
    s = _LEAD.sub("", s).replace("*", " ")                          # (above: the card digits and address after)
    s = re.sub(r"\s+", " ", re.sub(r"\b(\d+|X+\d*)\b", " ", s)).strip(" -:")
    return (s if len(s) >= 3 else payee(desc).title() or (desc or "")[:32])[:32]


def kind(name: str) -> str:
    """An account's kind from its name: savings, checking, credit, loan, or account."""
    return next((k for k, rx in KINDS if rx.search(name or "")), "account")


def _per_month(it: dict) -> float:
    return abs(it["amount"]) * {"weekly": 52 / 12, "biweekly": 26 / 12}.get(it.get("every"), 1.0)


def _months(d: dt.date, n: int, day: int) -> dt.date:
    """d moved n months on, on `day` (or the month's last day)."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(day, last))


def _step(d: dt.date, every: str, day: int) -> dt.date:
    return _months(d, 1, day) if every == "monthly" else d + dt.timedelta(days={"weekly": 7, "biweekly": 14}[every])


def recurring(txns: list[dict], today: dt.date) -> list[dict]:
    """Bills and paydays found in the history: the same payee, the same sign, at a
    steady weekly, fortnightly or monthly rhythm, still going (a stopped one, its
    next date well past, is dropped)."""
    groups: dict[tuple, list] = {}
    for t in txns:
        if t.get("pending") or not t.get("posted") or INTERNAL.search(t.get("description", "")):
            continue
        k = payee(t.get("description", ""))
        amt = _num(t.get("amount"))
        if not k or abs(amt) < 0.01:
            continue
        groups.setdefault((k, amt > 0), []).append((_day(t["posted"]), amt, t.get("description", "")))
    out = []
    for (k, income), rows in groups.items():
        rows.sort()
        days = sorted({d for d, _, _ in rows})
        if len(days) < 2:
            continue
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        med = statistics.median(gaps)
        if 6 <= med <= 8 and len(days) >= 3:
            every, tol = "weekly", 2
        elif 12 <= med <= 16:
            every, tol = "biweekly", 3
        elif 26 <= med <= 35:
            every, tol = "monthly", 4
        else:
            continue
        if sum(abs(g - med) <= tol for g in gaps) < max(1, round(len(gaps) * 0.6)):
            continue                                # not steady enough to call it a rhythm
        recent = [abs(a) for _, a, _ in rows[-3:]]
        desc = rows[-1][2]
        named = SUBS.search(desc) or BILLS.search(desc)
        spread = [abs(a) for _, a, _ in rows[-4:]]
        if not income and not named and max(spread) > 1.5 * min(spread):
            continue                                # a regular place he spends varying sums: not a bill
        amount = statistics.median(recent)
        nxt, day = days[-1], days[-1].day
        while nxt <= today - dt.timedelta(days=1):
            nxt = _step(nxt, every, day)
        late = (nxt - _step(days[-1], every, day)).days
        if late > tol + 7:                          # several periods missed: it stopped
            continue
        sub = not income and not BILLS.search(desc) and (
            bool(SUBS.search(desc)) or (every == "monthly" and amount < 60 and max(recent) - min(recent) < 0.5))
        out.append({"key": k, "name": nice(desc), "amount": round(amount if income else -amount, 2),
                    "kind": "income" if income else "subscription" if sub else "bill",
                    "every": every, "next": nxt.isoformat(), "last": days[-1].isoformat(), "seen": len(days),
                    "variable": (max(recent) - min(recent)) > 0.15 * max(recent), "income": income,
                    "source": "found"})
    # A service seen once lately (new, or billed unevenly): monthly from that charge.
    have = {r["key"] for r in out}
    for (k, income), rows in groups.items():
        d, amt, desc = max(rows)
        if income or k in have or not SUBS.search(desc) or (today - d).days > 35 or abs(amt) > 100:
            continue
        nxt = _months(d, 1, d.day)
        out.append({"key": k, "name": nice(desc), "amount": round(amt, 2), "kind": "subscription",
                    "every": "monthly", "next": nxt.isoformat(), "last": d.isoformat(), "seen": len(rows),
                    "variable": False, "income": False, "source": "found"})
    return sorted(out, key=lambda r: r["next"])


def occurrences(items: list[dict], today: dt.date, days: int) -> list[dict]:
    """Every bill and payday falling from today through `days` ahead, in date order."""
    end = today + dt.timedelta(days=days)
    out = []
    for it in items:
        try:
            d = dt.date.fromisoformat(it["next"])
        except (KeyError, ValueError):
            continue
        every = it.get("every", "monthly")
        day = d.day
        while d < today:
            if every == "once":
                break
            d = _step(d, every, day)
        while today <= d <= end:
            out.append({"date": d.isoformat(), "name": it["name"], "amount": float(it["amount"]),
                        "income": float(it["amount"]) > 0, "source": it.get("source", "his"),
                        "kind": it.get("kind") or ("income" if float(it["amount"]) > 0 else "bill")})
            if every == "once":
                break
            d = _step(d, every, day)
    return sorted(out, key=lambda o: (o["date"], o["amount"]))


def cash(accounts: list[dict]) -> float:
    """Money he has: his accounts that aren't cards or loans (by name, or a balance below zero)."""
    return round(sum(a["balance"] for a in accounts
                     if not DEBT.search(a.get("name", "")) and a["balance"] >= 0), 2)


def forecast(start: float, occ: list[dict], spend: float = 0.0, on: str | None = None) -> dict:
    """The balance walked through what's coming: its lowest point and when, the next
    payday, and what's safe to spend before it (cash less the bills due first)."""
    bal, low, low_on = start, start, None
    ordered = list(occ)
    if spend:
        ordered.append({"date": on or (occ[0]["date"] if occ else dt.date.today().isoformat()),
                        "name": "this purchase", "amount": -abs(spend), "income": False})
        ordered.sort(key=lambda o: (o["date"], o["amount"]))
    rows = []
    for o in ordered:
        bal = round(bal + o["amount"], 2)
        rows.append({**o, "after": bal})
        if bal < low:
            low, low_on = bal, o["date"]
    pay = next((o["date"] for o in occ if o["income"]), None)
    before = [o for o in occ if not o["income"] and (pay is None or o["date"] < pay)]
    return {"start": round(start, 2), "end": bal, "low": round(low, 2), "low_on": low_on, "payday": pay,
            "safe": round(start + sum(o["amount"] for o in before), 2), "rows": rows}


def _money(v: float) -> str:
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


# ---- the widget and her verbs --------------------------------------------------------

class BankAdapter(Adapter):
    name = "bank"
    # (her tool's description: the system prompt has no room left for it)
    summary = ("His money, read-only: you can't move any. For plans (a budget, saving for something, "
               "paying a card down, whether he can afford it) work from these numbers and say which. "
               "Not connected: he pastes a SimpleFIN setup token in Settings > Models > Bank. Pick an action:")
    events = ("bill_soon", "synced")
    event_info = {"bill_soon": {"phrase": "sees a bill coming up in a few days",
                                "fields": {"name": "text", "amount": "number", "date": "text", "days": "number"},
                                "outside": True},
                  "synced": {"phrase": "gets fresh numbers from his bank",
                             "fields": {"cash": "number", "safe": "number"}, "outside": False}}
    state_fields = {"cash": ("number", "cash"), "safe": ("number", "safe")}

    def __init__(self, publish, root: Path | None = None, access_path: Path | None = None) -> None:
        super().__init__(publish)
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        self.root = root or base / "ariadne2" / "bank"
        self._access_path = access_path
        self.clock = time.time
        self.opener = urllib.request.urlopen
        self._task: asyncio.Task | None = None
        self._jitter = random.uniform(0, 3600)       # (a random minute: the Bridge asks for it)
        self._lock = asyncio.Lock()
        self.controls = {"refresh": "refresh"}
        days = {"type": "integer", "description": "how many days ahead (default 30)"}
        self.verbs = [
            Verb("summary", "His money now: accounts and balances, cash on hand, the next payday, what's safe "
                 "to spend before it, and the bills due in the next two weeks.", {}, self._summary),
            Verb("upcoming", "Subscriptions, bills and paydays coming up (found in his history, and his own), with the "
                 "balance after each.", {"properties": {"days": days}}, self._upcoming),
            Verb("transactions", "His recent transactions, newest first; search narrows by description.",
                 {"properties": {"search": {"type": "string"}, "days": {"type": "integer",
                  "description": "how far back (default 30)"}}}, self._transactions, outside_content=True),
            Verb("spending", "Where his money went: out and in over a period, and the biggest payees.",
                 {"properties": {"days": {"type": "integer", "description": "default 30"}}}, self._spending,
                 outside_content=True),
            Verb("forecast", "Walk his balance through what's coming: its lowest point, payday, what's safe "
                 "to spend. With spend (and on, YYYY-MM-DD), whether a purchase fits.",
                 {"properties": {"days": days, "spend": {"type": "number"}, "on": {"type": "string"}}},
                 self._forecast),
            Verb("add_bill", "Add a bill (or income) of his: name, amount (what it costs; income true for "
                 "money in), next date YYYY-MM-DD, every monthly, biweekly, weekly or once.",
                 {"properties": {"name": {"type": "string"}, "amount": {"type": "number"},
                                 "next": {"type": "string"}, "every": {"type": "string",
                                 "enum": ["monthly", "biweekly", "weekly", "once"]},
                                 "income": {"type": "boolean"}},
                  "required": ["name", "amount", "next"]}, self._add_bill),
            Verb("remove_bill", "Remove a bill of his, or tell her a found one isn't really a bill.",
                 {"properties": {"name": {"type": "string"}}, "required": ["name"]}, self._remove_bill),
            Verb("refresh", "Fetch fresh numbers from his bank now (at most hourly).", {}, self._refresh,
                 control="refresh"),
        ]

    # ---- storage ----
    def _access(self) -> str | None:
        env = os.environ.get("ARIADNE2_SIMPLEFIN", "").strip()
        if env:
            return env
        path = self._access_path
        if path is None:
            from ..core import settings
            path = settings._key_path("simplefin_token")
        try:
            return path.read_text("utf-8").strip() or None
        except OSError:
            return None

    def _read(self, name: str, default):
        try:
            return json.loads((self.root / name).read_text("utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        tmp = self.root / (name + ".part")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(self.root / name)

    def _today(self) -> dt.date:
        return dt.datetime.fromtimestamp(self.clock()).date()

    def _txns(self) -> list[dict]:
        out = []
        for acct, rows in self._read("txns.json", {}).items():
            for t in rows.values():
                out.append({**t, "account": acct})
        return sorted(out, key=lambda t: t.get("posted") or t.get("transacted_at") or 0, reverse=True)

    def _items(self) -> list[dict]:
        mine = self._read("mine.json", {"bills": [], "not_bills": []})
        found = [r for r in recurring(self._txns(), self._today()) if r["key"] not in mine.get("not_bills", [])]
        return found + [{**b, "source": "his"} for b in mine.get("bills", [])]

    def _accounts(self) -> list[dict]:
        return [{**a, "kind": kind(a.get("name", ""))} for a in self._read("accounts.json", [])]

    def _main(self, accounts: list[dict]) -> dict | None:
        """The account his bills come out of: his checking, else the busiest one."""
        if not accounts:
            return None
        chk = [a for a in accounts if a["kind"] == "checking"]
        if chk:
            return chk[0]
        busy = {aid: len(rows) for aid, rows in self._read("txns.json", {}).items()}
        return max(accounts, key=lambda a: busy.get(a["id"], 0))

    def _start(self, accounts: list[dict]) -> float:
        """What the bills are walked from: his checking's available balance, not his savings too."""
        main = self._main(accounts)
        return round(main["available"], 2) if main else cash(accounts)

    def _spent(self, days: int) -> list[dict]:
        """What went out, newest first: posted or pending, not moves between his own accounts."""
        cut = self.clock() - days * 86400
        kinds = {a["id"]: a["kind"] for a in self._accounts()}
        return [{"date": _day(t.get("posted") or t.get("transacted_at")).isoformat(), "name": nice(t["description"]),
                 "amount": t["amount"], "account": kinds.get(t["account"], "account"), "pending": t["pending"]}
                for t in self._txns() if t["amount"] < 0 and not INTERNAL.search(t["description"])
                and (t.get("posted") or t.get("transacted_at") or 0) >= cut]

    # ---- syncing ----
    async def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(20)                     # (after the desk has connected)
        while True:
            try:
                meta = self._read("sync.json", {})
                if self._access() and self.clock() - float(meta.get("last", 0)) > SYNC_EVERY + self._jitter:
                    await self.sync()
                else:
                    await self.publish_state()
            except Exception:
                log.exception("bank sync failed")
            await asyncio.sleep(1800)

    async def sync(self) -> str:
        """Fetch from SimpleFIN, keep what's new, save, tell the widget. Returns a note."""
        access = self._access()
        if not access:
            raise AdapterError("his bank isn't connected (Settings > Models > Bank: a SimpleFIN setup token)")
        async with self._lock:
            meta = self._read("sync.json", {})
            now = self.clock()
            start = float(meta["last"]) - OVERLAP if meta.get("last") else now - FIRST
            try:
                data = await asyncio.to_thread(fetch, access, max(start, now - FIRST), now + 86400, self.opener)
            except BankError as e:
                meta["note"] = str(e)
                self._write("sync.json", meta)
                await self.publish_state()
                raise AdapterError(str(e)) from e
            conns = {c.get("conn_id"): c.get("name") or c.get("org_name") or "" for c in data.get("connections") or []}
            accounts, txns = [], self._read("txns.json", {})
            for a in data.get("accounts") or []:
                aid = str(a.get("id"))
                accounts.append({"id": aid, "name": a.get("name", "Account"), "bank": conns.get(a.get("conn_id"), ""),
                                 "currency": a.get("currency", "USD"), "balance": _num(a.get("balance")),
                                 "available": _num(a["available-balance"]) if a.get("available-balance") is not None
                                 else _num(a.get("balance")), "as_of": a.get("balance-date")})
                rows = txns.setdefault(aid, {})
                for t in a.get("transactions") or []:
                    tid = str(t.get("id"))
                    rows[tid] = {"id": tid, "posted": t.get("posted") or 0, "transacted_at": t.get("transacted_at"),
                                 "amount": _num(t.get("amount")), "description": str(t.get("description", ""))[:200],
                                 "pending": bool(t.get("pending")), "seen": rows.get(tid, {}).get("seen", now)}
                # (a pending one that has since posted comes back under a new id: the stale one goes)
                for tid in [k for k, v in rows.items() if v["pending"] and now - float(v.get("seen", now)) > 10 * 86400]:
                    del rows[tid]
            errs = [e.get("msg", "") for e in data.get("errlist") or [] if e.get("msg")] or list(data.get("errors") or [])
            self._write("accounts.json", accounts)
            self._write("txns.json", txns)
            meta.update(last=now, note="; ".join(errs)[:300])
            self._write("sync.json", meta)
        st = self.state()
        self.emit("synced", cash=st["cash"], safe=st["safe"])
        self._announce()
        await self.publish_state()
        return "Fresh from the bank" + (f" (SimpleFIN says: {meta['note']})" if meta["note"] else "") + "."

    def _announce(self) -> None:
        """bill_soon, once for each bill within SOON_DAYS."""
        meta = self._read("sync.json", {})
        told = set(meta.get("told", []))
        today = self._today()
        for o in occurrences(self._items(), today, SOON_DAYS):
            key = f"{o['name']}|{o['date']}"
            if o["income"] or key in told:
                continue
            told.add(key)
            self.emit("bill_soon", name=o["name"], amount=abs(o["amount"]), date=o["date"],
                      days=(dt.date.fromisoformat(o["date"]) - today).days)
        meta["told"] = sorted(told)[-200:]
        self._write("sync.json", meta)

    # ---- state (the widget) ----
    def state(self) -> dict:
        accounts = self._accounts()
        meta = self._read("sync.json", {})
        connected = bool(self._access())
        items = self._items()
        main = self._main(accounts)
        f = forecast(self._start(accounts), occurrences(items, self._today(), 30))
        rows = [{"date": r["date"], "name": r["name"], "amount": r["amount"], "after": r["after"],
                 "income": r["income"], "kind": r["kind"]} for r in f["rows"]]
        spent = self._spent(7)
        return {"connected": connected, "accounts": accounts, "main": main["id"] if main else None,
                "cash": cash(accounts), "start": f["start"], "safe": f["safe"],
                "payday": f["payday"], "low": f["low"], "low_on": f["low_on"],
                "subs": [r for r in rows if r["kind"] == "subscription"][:14],
                "subs_month": round(sum(_per_month(i) for i in items if i.get("kind") == "subscription"), 2),
                "bills": [r for r in rows if r["kind"] != "subscription"][:14],
                "spent": spent[:25], "spent_week": round(-sum(s["amount"] for s in spent), 2),
                "synced": meta.get("last"), "note": meta.get("note", "")}

    # ---- verbs ----
    def _need(self) -> None:
        if not self._accounts():
            raise AdapterError("there are no bank numbers yet" + (" (it hasn't synced; try refresh)" if self._access()
                               else " (his bank isn't connected: Settings > Models > Bank)"))

    async def _summary(self) -> str:
        self._need()
        st = self.state()
        lines = [f"{a['name']} [{a['kind']}]{' (' + a['bank'] + ')' if a['bank'] else ''}: {_money(a['balance'])}"
                 + (f", {_money(a['available'])} available" if abs(a["available"] - a["balance"]) > 0.005 else "")
                 for a in st["accounts"]]
        lines.append(f"Cash on hand: {_money(st['cash'])}; the bills come out of the one with {_money(st['start'])}.")
        if st["subs_month"]:
            lines.append(f"Subscriptions: {_money(st['subs_month'])} a month.")
        if st["payday"]:
            lines.append(f"Next payday: {st['payday']}; safe to spend before it: {_money(st['safe'])}.")
        else:
            lines.append(f"No payday found in the next 30 days; after the bills due, {_money(st['safe'])} is left.")
        soon = sorted((u for u in st["subs"] + st["bills"] if not u["income"]), key=lambda u: u["date"])[:8]
        if soon:
            lines.append("Due soon: " + "; ".join(f"{u['date']} {u['name']} {_money(abs(u['amount']))}" for u in soon) + ".")
        if st["low"] < 0:
            lines.append(f"Warning: the balance goes to {_money(st['low'])} on {st['low_on']}.")
        if st["synced"]:
            lines.append(f"(as of {dt.datetime.fromtimestamp(st['synced']).strftime('%a %d %b %H:%M')})")
        if st["note"]:
            lines.append(f"SimpleFIN says: {st['note']}")
        return "\n".join(lines)

    async def _upcoming(self, days: int = 30) -> str:
        self._need()
        days = max(1, min(int(days or 30), 120))
        f = forecast(self._start(self._accounts()), occurrences(self._items(), self._today(), days))
        if not f["rows"]:
            return f"Nothing found coming up in the next {days} days."
        return "\n".join(f"{r['date']}  {r['name']} [{r['kind']}]  {_money(r['amount'])}  (then {_money(r['after'])})"
                         for r in f["rows"])

    async def _transactions(self, search: str = "", days: int = 30) -> str:
        self._need()
        cut = self.clock() - max(1, min(int(days or 30), 365)) * 86400
        want = (search or "").lower()
        rows = [t for t in self._txns() if (t.get("posted") or t.get("transacted_at") or 0) >= cut
                and (not want or want in t["description"].lower())][:40]
        if not rows:
            return "No transactions match." if want else "No transactions in that time."
        return "\n".join(f"{_day(t.get('posted') or t.get('transacted_at')).isoformat()}  {_money(t['amount'])}  "
                         f"{t['description']}{'  (pending)' if t['pending'] else ''}" for t in rows)

    async def _spending(self, days: int = 30) -> str:
        self._need()
        days = max(1, min(int(days or 30), 365))
        cut = self.clock() - days * 86400
        rows = [t for t in self._txns() if (t.get("posted") or 0) >= cut and not t["pending"]
                and not INTERNAL.search(t["description"])]
        out = sum(-t["amount"] for t in rows if t["amount"] < 0)
        inn = sum(t["amount"] for t in rows if t["amount"] > 0)
        by: dict[str, float] = {}
        for t in rows:
            if t["amount"] < 0:
                k = payee(t["description"]) or t["description"][:20]
                by[k] = by.get(k, 0) - t["amount"]
        top = sorted(by.items(), key=lambda kv: -kv[1])[:10]
        return (f"Last {days} days: {_money(out)} out, {_money(inn)} in.\nBiggest: "
                + "; ".join(f"{k} {_money(v)}" for k, v in top))

    async def _forecast(self, days: int = 30, spend: float = 0.0, on: str | None = None) -> str:
        self._need()
        days = max(1, min(int(days or 30), 120))
        if on:
            try:
                dt.date.fromisoformat(on)
            except ValueError:
                raise AdapterError("on wants a date as YYYY-MM-DD")
        f = forecast(self._start(self._accounts()), occurrences(self._items(), self._today(), days),
                     float(spend or 0), on)
        head = (f"Starting from {_money(f['start'])}: lowest {_money(f['low'])}"
                + (f" on {f['low_on']}" if f["low_on"] else "") + f", {_money(f['end'])} after {days} days.")
        if spend:
            head += (" The purchase fits." if f["low"] >= 0 else " The purchase would take him below zero.")
        if f["payday"]:
            head += f" Next payday {f['payday']}; safe to spend before it: {_money(f['safe'])}."
        return head

    async def _add_bill(self, name: str, amount: float, next: str, every: str = "monthly",
                        income: bool = False) -> str:
        try:
            dt.date.fromisoformat(next)
        except ValueError:
            raise AdapterError("next wants a date as YYYY-MM-DD")
        if every not in ("monthly", "biweekly", "weekly", "once"):
            raise AdapterError("every is monthly, biweekly, weekly or once")
        mine = self._read("mine.json", {"bills": [], "not_bills": []})
        mine["bills"] = [b for b in mine.get("bills", []) if b["name"].lower() != name.strip().lower()]
        mine["bills"].append({"name": name.strip()[:60], "amount": abs(float(amount)) * (1 if income else -1),
                              "next": next, "every": every,
                              "kind": "income" if income else "subscription" if SUBS.search(name) else "bill"})
        self._write("mine.json", mine)
        await self.publish_state()
        return f"Added {name.strip()}: {_money(abs(float(amount)))} {'in' if income else 'out'}, {every}, next {next}."

    async def _remove_bill(self, name: str) -> str:
        want = name.strip().lower()
        mine = self._read("mine.json", {"bills": [], "not_bills": []})
        before = len(mine.get("bills", []))
        mine["bills"] = [b for b in mine.get("bills", []) if b["name"].lower() != want]
        if len(mine["bills"]) < before:
            self._write("mine.json", mine)
            await self.publish_state()
            return f"Removed his bill {name}."
        found = [r for r in recurring(self._txns(), self._today())
                 if want in r["name"].lower() or want == r["key"]]
        if not found:
            raise AdapterError(f"there's no bill called {name!r}")
        mine.setdefault("not_bills", []).extend(r["key"] for r in found if r["key"] not in mine["not_bills"])
        self._write("mine.json", mine)
        await self.publish_state()
        return "Noted: " + ", ".join(r["name"] for r in found) + " isn't a bill."

    async def _refresh(self) -> str:
        meta = self._read("sync.json", {})
        wait = MIN_REFRESH - (self.clock() - float(meta.get("last", 0)))
        if wait > 0:
            raise AdapterError(f"it synced under an hour ago; SimpleFIN only updates daily (try again in {int(wait // 60) + 1} min)")
        return await self.sync()
