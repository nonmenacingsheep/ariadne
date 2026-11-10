"""His bank (adapters/bank.py): SimpleFIN claim and fetch, bills found in the
history, what's safe to spend, the widget's state and her verbs. No network:
SimpleFIN is a fake opener."""
import asyncio
import base64
import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ariadne2.adapters import bank as B
from ariadne2.adapters.base import AdapterError

TODAY = dt.date(2026, 11, 10)
NOW = dt.datetime(2026, 11, 10, 12, 0).timestamp()


def ts(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, 12).timestamp())


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_for(body, seen=None, status=200):
    def opener(req, timeout=None):
        if seen is not None:
            seen.append(req)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b""))
        return Resp(body if isinstance(body, bytes) else json.dumps(body).encode())
    return opener


def history():
    """Three months of Netflix and power, fortnightly pay, a stopped gym, a new
    Crunchyroll, round-ups to savings, PayPal in varying sums, and noise."""
    tx, n = [], 0
    def add(d, amt, desc):
        nonlocal n
        n += 1
        tx.append({"id": f"t{n}", "posted": ts(d), "amount": f"{amt:.2f}", "description": desc})
    for m in (8, 9, 10):
        add(dt.date(2026, m, 15), -15.49, f"NETFLIX.COM 866-579-71{m} CA")
    for k in range(6):
        add(dt.date(2026, 8, 21) + dt.timedelta(days=14 * k), 1850.00, "ACME CORP PAYROLL PPD ID: 99")
    for m in (5, 6, 7):
        add(dt.date(2026, m, 3), -40.00, "IRONGYM MONTHLY")          # stopped after July
    for m, amt in ((8, 88.10), (9, 92.40), (10, 79.95)):
        add(dt.date(2026, m, 20), -amt, "CITY ELECTRIC AUTOPAY")
    add(dt.date(2026, 11, 1), -9.99, "Crunchyroll")
    for k, amt in enumerate((100, 80, 200, 136, 160, 127, 50)):
        add(dt.date(2026, 9, 19) + dt.timedelta(days=7 * k), -amt, "Paypal *Jdoe **** 2211 Main St")
    for k in range(8):
        add(dt.date(2026, 9, 15) + dt.timedelta(days=7 * k), -1.00, "Withdrawal Transfer To SXX10 - Change It")
    add(dt.date(2026, 10, 29), -63.12, "SHELL OIL 12345")
    add(dt.date(2026, 11, 2), -8.75, "STARBUCKS #2231")
    return tx


class SimpleFIN(unittest.TestCase):
    def test_claim_posts_the_decoded_url_once(self):
        seen = []
        token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/abc").decode()
        got = B.claim(token, opener_for(b"https://u:p@bridge.simplefin.org/simplefin\n", seen))
        self.assertEqual(got, "https://u:p@bridge.simplefin.org/simplefin")
        self.assertEqual(seen[0].get_method(), "POST")
        self.assertEqual(seen[0].full_url, "https://bridge.simplefin.org/simplefin/claim/abc")
        self.assertNotIn("Python", seen[0].get_header("User-agent"))   # Cloudflare turns that away

    def test_a_firewall_refusal_is_not_called_a_used_token(self):
        token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/abc").decode()
        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(b"error code: 1010\n"))
        with self.assertRaises(B.BankError) as cm:
            B.claim(token, opener)
        self.assertIn("wasn't used", str(cm.exception))

    def test_a_used_token_says_it_may_be_compromised(self):
        token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/abc").decode()
        with self.assertRaises(B.BankError) as cm:
            B.claim(token, opener_for(b"", status=403))
        self.assertIn("someone else", str(cm.exception))
        with self.assertRaises(B.BankError):
            B.claim("not a token!!", opener_for(b""))

    def test_fetch_asks_v2_with_dates_and_basic_auth(self):
        seen = []
        B.fetch("https://user:pa%40ss@bridge.simplefin.org/simplefin", 100, 200, opener_for({"accounts": []}, seen))
        req = seen[0]
        self.assertTrue(req.full_url.startswith("https://bridge.simplefin.org/simplefin/accounts?"))
        self.assertIn("version=2", req.full_url)
        self.assertIn("start-date=100", req.full_url)
        self.assertNotIn("user", req.full_url)                       # credentials not in the URL sent
        self.assertNotIn("Python", req.get_header("User-agent"))
        self.assertEqual(req.get_header("Authorization"), "Basic " + base64.b64encode(b"user:pa@ss").decode())
        with self.assertRaises(B.BankError) as cm:
            B.fetch("https://u:p@x.org/simplefin", opener=opener_for(b"", status=403))
        self.assertIn("Connect the bank again", str(cm.exception))


class Sums(unittest.TestCase):
    def test_bills_and_paydays_found_and_a_stopped_one_dropped(self):
        rec = B.recurring(history(), TODAY)
        by = {r["key"]: r for r in rec}
        self.assertEqual(by["netflix"]["every"], "monthly")
        self.assertEqual(by["netflix"]["next"], "2026-11-15")
        self.assertEqual(by["netflix"]["amount"], -15.49)
        pay = next(r for r in rec if r["income"])
        self.assertEqual(pay["every"], "biweekly")
        self.assertEqual(pay["next"], "2026-11-13")
        self.assertNotIn("irongym", by)                               # stopped in July
        self.assertFalse(any("shell" in k or "starbucks" in k for k in by))   # one-offs aren't bills

    def test_subscriptions_and_bills_apart_and_not_his_own_moves(self):
        by = {r["key"]: r for r in B.recurring(history(), TODAY)}
        self.assertEqual(by["netflix"]["kind"], "subscription")
        self.assertEqual(by["city electric autopay"]["kind"], "bill")
        self.assertEqual(by["crunchyroll"]["next"], "2026-12-01")       # a service seen once lately
        self.assertFalse(any("paypal" in k for k in by))                 # varying sums: spending, not a bill
        self.assertFalse(any("transfer" in k or "change" in k for k in by))   # round-ups to his savings

    def test_names_fit_to_show(self):
        self.assertEqual(B.nice("Discord* Nitromo ***X 444 DE Haro Street"), "Discord Nitromo")
        self.assertEqual(B.nice("Ach Withdrawal Company: Rocket Money Entry: Premium"), "Rocket Money")
        self.assertEqual(B.nice("Payment to Youtube Premium"), "Youtube Premium")
        self.assertEqual([B.kind(n) for n in ("Everyday Checking (1234)", "Savings (5678)", "Visa Signature")],
                         ["checking", "savings", "credit"])

    def test_safe_to_spend_is_cash_less_bills_before_payday(self):
        items = [{"name": "Rent", "amount": -1200, "next": "2026-11-12", "every": "monthly"},
                 {"name": "Pay", "amount": 1850, "next": "2026-11-13", "every": "biweekly"},
                 {"name": "Phone", "amount": -60, "next": "2026-11-20", "every": "monthly"}]
        occ = B.occurrences(items, TODAY, 30)
        f = B.forecast(1500, occ)
        self.assertEqual(f["payday"], "2026-11-13")
        self.assertEqual(f["safe"], 300.0)
        self.assertGreaterEqual(f["low"], 0)
        g = B.forecast(1500, occ, spend=400, on="2026-11-11")
        self.assertLess(g["low"], 0)                                  # the purchase would overdraw him
        self.assertEqual(g["low_on"], "2026-11-12")

    def test_cash_leaves_out_cards_and_loans(self):
        accts = [{"name": "Everyday Checking", "balance": 900.0}, {"name": "Savings", "balance": 300.0},
                 {"name": "Visa Signature", "balance": -450.0}, {"name": "Auto Loan", "balance": 12000.0}]
        self.assertEqual(B.cash(accts), 1200.0)


class Adapter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.access = self.tmp / "simplefin_access"
        self.access.write_text("https://u:p@bridge.simplefin.org/simplefin")
        self.events = []
        self.a = B.BankAdapter(lambda m: asyncio.sleep(0), root=self.tmp / "bank", access_path=self.access)
        self.a.subscribers.append(lambda name, fields: self.events.append((name, fields)))
        self.a.clock = lambda: NOW
        self.body = {"errlist": [], "connections": [{"conn_id": "c1", "name": "Big Bank"}],
                     "accounts": [{"id": "a1", "name": "Checking", "conn_id": "c1", "currency": "USD",
                                   "balance": "1520.40", "balance-date": int(NOW), "transactions": history()},
                                  {"id": "a2", "name": "Visa", "conn_id": "c1", "currency": "USD",
                                   "balance": "-210.00", "balance-date": int(NOW), "transactions": []},
                                  {"id": "a3", "name": "Savings", "conn_id": "c1", "currency": "USD",
                                   "balance": "500.00", "balance-date": int(NOW), "transactions": [
                                       {"id": "s1", "posted": ts(dt.date(2026, 11, 8)), "amount": "-40.00",
                                        "description": "Online banking Withdrawal Transfer to Pam"}]}]}
        self.a.opener = opener_for(self.body)

    def run_(self, coro):
        return asyncio.run(coro)

    def test_sync_fills_the_widget(self):
        self.run_(self.a.sync())
        st = self.a.state()
        self.assertTrue(st["connected"])
        self.assertEqual(st["cash"], 2020.40)                           # checking and savings
        self.assertEqual(st["start"], 1520.40)                          # but the bills come out of checking
        self.assertEqual(st["main"], "a1")
        self.assertEqual(st["payday"], "2026-11-13")
        self.assertTrue(any("NETFLIX" in u["name"] for u in st["subs"]))
        self.assertTrue(any("PAYROLL" in u["name"] for u in st["bills"]))
        self.assertGreater(st["subs_month"], 25)                        # Netflix and Crunchyroll
        spent = {(s["name"], s["account"]) for s in st["spent"]}
        self.assertIn(("Transfer to Pam", "savings"), spent)            # gone through, from savings
        self.assertFalse(any("Change It" in n for n, _ in spent))
        self.assertTrue(any(e[0] == "bank.synced" for e in self.events))
        txt = self.run_(self.a._summary())
        self.assertIn("Checking [checking] (Big Bank): $1,520.40", txt)
        self.assertIn("Next payday: 2026-11-13", txt)

    def test_a_bill_within_three_days_is_announced_once(self):
        self.a.clock = lambda: dt.datetime(2026, 11, 13, 9).timestamp()
        self.run_(self.a.sync())
        soon = [e for e in self.events if e[0] == "bank.bill_soon"]
        self.assertEqual([e[1]["days"] for e in soon], [2])               # Netflix on the 15th
        self.a._announce()
        self.assertEqual(len([e for e in self.events if e[0] == "bank.bill_soon"]), 1)

    def test_his_bills_and_not_a_bill(self):
        self.run_(self.a.sync())
        self.run_(self.a._add_bill("Rent", 1200, "2026-11-28"))
        self.assertIn("Rent", self.run_(self.a._upcoming(30)))
        self.run_(self.a._remove_bill("netflix"))                         # a found one: not a bill
        self.assertNotIn("NETFLIX", self.run_(self.a._upcoming(30)))
        self.run_(self.a._remove_bill("Rent"))
        self.assertNotIn("Rent", self.run_(self.a._upcoming(30)))

    def test_refresh_at_most_hourly_and_not_connected_says_where(self):
        self.run_(self.a.sync())
        with self.assertRaises(AdapterError):
            self.run_(self.a._refresh())
        self.access.unlink()
        with mock.patch.dict("os.environ", {"ARIADNE2_SIMPLEFIN": ""}):
            with self.assertRaises(AdapterError) as cm:
                self.run_(self.a.sync())
        self.assertIn("Settings > Models > Bank", str(cm.exception))

    def test_a_simplefin_error_is_kept_for_him(self):
        self.body["errlist"] = [{"code": "con.auth", "msg": "Big Bank needs you to sign in again"}]
        self.run_(self.a.sync())
        self.assertIn("sign in again", self.a.state()["note"])


class SettingsClaim(unittest.TestCase):
    def test_pasting_a_token_keeps_the_access_link_not_the_token(self):
        from ariadne2.core import settings
        tmp = Path(tempfile.mkdtemp())
        s = settings.Settings(path=tmp / "settings.json")
        with mock.patch.object(settings, "_key_path", lambda key: tmp / "simplefin_access"), \
                mock.patch.object(B, "claim", return_value="https://u:p@bridge.simplefin.org/simplefin"):
            status = s.set("models", "simplefin_token", base64.b64encode(b"https://x/claim/1").decode())
        self.assertTrue(status.startswith("set:"))
        self.assertEqual((tmp / "simplefin_access").read_text().strip(), "https://u:p@bridge.simplefin.org/simplefin")
        with mock.patch.object(settings, "_key_path", lambda key: tmp / "simplefin_access"), \
                mock.patch.object(B, "claim", side_effect=B.BankError("already used")):
            with self.assertRaises(settings.SettingsError):
                s.set("models", "simplefin_token", "QUJDREVGR0g=")


if __name__ == "__main__":
    unittest.main()
