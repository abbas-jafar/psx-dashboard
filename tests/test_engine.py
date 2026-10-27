"""Offline tests for the engine. Run:  python -m unittest discover -s tests -v   (from the project folder)"""
import datetime as dt, json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import indicators as ind, signals as sg, ai_agent as ai, rules, trade, fetcher

R = {"near_low_pct": 5, "below_avg_pct": 15, "max_stock_weight_pct": 12, "max_sector_weight_pct": 25, "opp_min_yield_pct": 4, "opp_max_pe": 10,
     "trim_yield_below_pct": 3, "trim_range_pos_pct": 85, "high_payout_pct": 90}


def row(t, qty=10, price=100.0, avg=100.0, eps=20.0, dps=6.0, low=90.0, high=140.0, **kw):
    r = {"ticker": t, "sector": "Banking", "qty": str(qty), "avg_cost": str(avg), "price": str(price), "change_pct": "0", "low52": str(low), "high52": str(high),
         "eps": str(eps), "dps": str(dps), **{k: str(v) for k, v in kw.items()}}
    e = rules.enrich([r, {**r, "ticker": "ZZ", "qty": "90"}])
    return e[0]


UP = {"trend": "up", "sma50": 99, "sma200": 90, "sma20": 100, "rsi14": 50, "boll": {"pct_b": .5}, "support": 95, "resistance": 130, "n": 300}


class Indicators(unittest.TestCase):
    def test_rsi_extremes(self):
        self.assertEqual(ind.rsi(list(range(1, 40))), 100.0)
        self.assertLess(ind.rsi(list(range(40, 1, -1))), 1)

    def test_sma_and_boll(self):
        v = [float(i) for i in range(1, 31)]
        self.assertAlmostEqual(ind.sma(v, 20), 20.5)
        self.assertIsNone(ind.sma(v, 50))
        b = ind.bollinger(v)
        self.assertTrue(b["lower"] < b["mid"] < b["upper"])

    def test_compute_uses_live_price_and_handles_short_history(self):
        rows = [[20260101 + i, 100 + i] for i in range(10)]
        out = ind.compute(rows, 112, dt.date(2026, 10, 1))
        self.assertIsNone(out["sma200"])
        self.assertEqual(out["n"], 11)

    def test_history_price_mismatch_is_rejected(self):
        rows = [[20260101 + i, 100 + i] for i in range(10)]
        out = ind.compute(rows, 300, dt.date(2026, 10, 1))
        self.assertTrue(out["mismatch"])
        self.assertIsNone(out["sma20"])


class Signals(unittest.TestCase):
    def test_hubco_style_strong_buy(self):
        r = row("HUBC", qty=0, price=188, eps=38, dps=20, low=180, high=300, avg=0)
        s = sg.assess(r, {**UP, "support": 184}, {"payouts": [1], "n_12m": 2, "n_36m": 5}, [], R)
        self.assertEqual(s["signal"], "Strong Buy")
        self.assertTrue(any("yield" in x["id"] for x in s["reasons"]))

    def test_over_cap_forces_trim(self):
        r = row("EFERT", qty=500, eps=20, dps=8)   # other row ZZ is 90 shares, so EFERT is large
        r["weight_pct"] = 20.0
        s = sg.assess(r, UP, None, [], R)
        self.assertEqual(s["signal"], "Trim/Take Profit")
        self.assertIn("over_cap", s["flags"])

    def test_near_cap_blocks_adding(self):
        r = row("X", price=100, eps=30, dps=10, low=95)
        r["weight_pct"] = 11.5
        s = sg.assess(r, UP, {"payouts": [1], "n_12m": 1, "n_36m": 3}, [], R)
        self.assertEqual(s["signal"], "Hold")
        self.assertIn("near_cap", s["flags"])

    def test_risk_notice_overrides(self):
        s = sg.assess(row("SSGC", eps=20, dps=6), UP, None, [{"category": "Risk notice", "title": "Deficit list"}], R)
        self.assertEqual(s["signal"], "Review/Exit")

    def test_unheld_never_gets_trim_label(self):
        r = row("Q", qty=0, price=139, eps=3, dps=0.5, avg=0)
        s = sg.assess(r, {**UP, "rsi14": 80}, None, [], R)
        self.assertIn(s["signal"], sg.UNHELD)

    def test_watchlist_triggers(self):
        r = row("W", qty=0, price=100, eps=20, dps=6, avg=0, entry_price=105, target_yield=4, target_pe=10)
        s = sg.assess(r, UP, None, [], R)
        self.assertIn("all_triggers", s["flags"])
        self.assertEqual(len(s["triggers"]), 3)
        r2 = row("W", qty=0, price=100, eps=20, dps=6, avg=0, entry_price=90)
        self.assertNotIn("all_triggers", sg.assess(r2, UP, None, [], R)["flags"])

    def test_not_kmi_blocks_buy(self):
        r = row("N", qty=0, price=100, eps=30, dps=10, low=95, avg=0)
        s = sg.assess(r, UP, {"payouts": [1], "n_12m": 1, "n_36m": 3}, [], R, shariah=False)
        self.assertEqual(s["signal"], "Hold")

    def test_track_record(self):
        log = {"A": {"2026-01-01": ["Strong Buy", 100], "2026-03-01": ["Hold", 120]}}
        self.assertEqual(sg.track_record(log)["Strong Buy"], {"n": 1, "avg_return_pct": 20.0, "hit_pct": 100})


def results_for(*specs):
    out = []
    for t, held, sig, flags in specs:
        out.append({"ticker": t, "held": held, "signal": sig, "score": 1, "flags": flags, "reasons": [{"id": "x", "pts": 1, "txt": "t"}],
                    "facts": {"yield_pct": 6.0, "pe": 5.0}, "summary": ""})
    return out


class AI(unittest.TestCase):
    def setUp(self):
        self.res = results_for(("AAA", True, "Hold", []), ("BBB", True, "Hold", ["over_cap"]), ("CCC", False, "Accumulate", ["not_kmi"]))
        self.news = [{"id": "O1", "source": "State Bank of Pakistan", "title": "SBP cuts rate", "date": "x", "url": "https://sbp.org.pk/x", "text": "The policy rate is cut by 100bps."}]
        self.payload, self.valid = ai.build_payload(self.res, [{"ticker": "AAA", "date": "d", "category": "Results", "title": "Profit down 30%"}], self.news, {"KSE100": {"change_pct": -1.0}})

    def test_valid_upgrade_one_step_only(self):
        raw = {"market_view": {"stance": "neutral", "summary": "ok", "evidence": ["O1"]},
               "assessments": [{"ticker": "AAA", "signal": "Strong Buy", "sentiment": "positive", "rationale": "r", "risks": [], "opportunity": "", "evidence": ["AAA.yield_pct", "O1"]}]}
        out, mv, dropped = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(out["AAA"]["signal"], "Accumulate")      # clipped from two steps to one
        self.assertEqual(out["AAA"]["view"], "upgrade")

    def test_one_evidence_is_not_enough(self):
        raw = {"assessments": [{"ticker": "AAA", "signal": "Accumulate", "evidence": ["AAA.yield_pct"], "rationale": "r"}]}
        out, _, _ = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(out["AAA"]["signal"], "Hold")

    def test_fake_evidence_ignored(self):
        raw = {"assessments": [{"ticker": "AAA", "signal": "Accumulate", "evidence": ["AAA.made_up", "O99"], "rationale": "r"}]}
        out, _, _ = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(out["AAA"]["signal"], "Hold")

    def test_locked_stock_keeps_rule_signal(self):
        raw = {"assessments": [{"ticker": "BBB", "signal": "Review/Exit", "evidence": ["BBB.yield_pct", "O1"], "rationale": "r"}]}
        out, _, _ = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(out["BBB"]["signal"], "Hold")

    def test_guard_flags_block_upgrade(self):
        raw = {"assessments": [{"ticker": "CCC", "signal": "Strong Buy", "evidence": ["CCC.yield_pct", "O1"], "rationale": "r"}]}
        out, _, _ = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(out["CCC"]["signal"], "Accumulate")

    def test_unknown_ticker_and_markup_cleaned(self):
        raw = {"assessments": [{"ticker": "EVIL", "signal": "Hold"}, {"ticker": "AAA", "signal": "Hold", "rationale": "<script>alert(1)</script> fine", "risks": ["<b>x</b>"] * 5, "evidence": []}]}
        out, _, dropped = ai.sanitize(raw, self.res, self.valid)
        self.assertEqual(dropped, 1)
        self.assertNotIn("<", out["AAA"]["rationale"])
        self.assertEqual(len(out["AAA"]["risks"]), 3)

    def test_payload_has_no_money_amounts(self):
        txt = json.dumps(self.payload)
        for bad in ("qty", "avg_cost", "value", "Rs"):
            self.assertNotIn(bad, txt)

    def test_run_with_mock_api_and_cache(self):
        tool = {"market_view": {"stance": "mixed", "summary": "s", "evidence": ["O1"]},
                "findings": [{"headline": "h", "what_happened": "SBP cut", "analysis": "a", "reality_check": "r", "affected": ["AAA", "ZZZ"], "stance": "positive", "sources": ["O1", "O77"]},
                             {"headline": "bad", "what_happened": "x", "analysis": "", "reality_check": "", "affected": [], "stance": "neutral", "sources": ["O88"]}],
                "assessments": [{"ticker": t, "signal": s, "sentiment": "neutral", "rationale": "r", "risks": [], "opportunity": "", "evidence": []} for t, s in (("AAA", "Hold"), ("BBB", "Hold"), ("CCC", "Accumulate"))]}
        resp = mock.Mock(status_code=200, json=lambda: {"content": [{"type": "tool_use", "name": "submit_assessments", "input": tool}], "usage": {"input_tokens": 10, "output_tokens": 5}})
        post = mock.Mock(return_value=resp)
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "ai.json")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            b = ai.run(self.res, [], self.news, {}, {}, force=True, cache_path=p, post=post)
            self.assertEqual(b["status"], "fresh")
            self.assertEqual(len(b["findings"]), 1)                    # the one citing a made-up source is dropped
            self.assertEqual(b["findings"][0]["sources"], ["O1"])
            self.assertEqual(b["findings"][0]["affected"], ["AAA"])
            self.assertEqual(b["findings"][0]["basis"], "full text")
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["tool_choice"]["name"], "submit_assessments")
            b2 = ai.run(self.res, [], self.news, {}, {}, force=False, cache_path=p, post=post)
            self.assertEqual(b2["status"], "cached")
            self.assertEqual(post.call_count, 1)
            post.return_value = mock.Mock(status_code=500, text="boom sk-secretkey123")
            b3 = ai.run(self.res, [], self.news, {}, {}, force=True, cache_path=p, post=post)
            self.assertEqual(b3["status"], "stale")
            self.assertNotIn("secretkey", b3["note"])

    def test_no_key_means_off(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(ai.run(self.res, [], [], {}, {}, force=True)["status"], "off")

    def test_stale_answer_not_applied(self):
        block = {"assessments": {"AAA": {"rule_signal": "Accumulate", "signal": "Strong Buy", "view": "upgrade", "rationale": "x"}}}
        res = ai.apply(self.res, block)
        self.assertEqual(res[0]["signal"], "Hold")
        self.assertTrue(res[0]["ai"]["stale"])


class Official(unittest.TestCase):
    def test_dedupe_keeps_most_authoritative(self):
        items = [{"title": "SBP keeps policy rate unchanged at 11 percent", "priority": 1}, {"title": "SBP keeps policy rate unchanged at 11 percent today", "priority": 3}, {"title": "FBR extends tax return deadline", "priority": 4}]
        out = fetcher.dedupe_items(items)
        self.assertEqual(len(out), 2)
        self.assertTrue(any(o["priority"] == 1 for o in out))

    def test_scrape_dated_links(self):
        today = dt.datetime.now(fetcher.PKT).date()
        html = f"<table><tr><td>{today.strftime('%d %b %Y')}</td><td><a href='/press/a.htm'>Monetary Policy Committee decides to keep the policy rate unchanged</a></td></tr>" \
               f"<tr><td>01 Jan 2020</td><td><a href='/old.htm'>An old press release from many years ago about something</a></td></tr><tr><td><a href='/menu'>Home page menu link text that is long enough</a></td></tr></table>"
        out = fetcher._scrape_dated_links("https://www.sbp.org.pk/press/index.htm", 14, get=lambda u: mock.Mock(text=html))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://www.sbp.org.pk/press/a.htm")

    def test_yahoo_rows(self):
        import history
        payload = {"chart": {"result": [{"timestamp": [1761000000, 1761086400], "indicators": {"quote": [{"close": [100.5, None], "high": [101, 1], "low": [99, 1], "volume": [1000, 5]}]}}]}}
        out = history.yahoo_rows("OGDC", get=lambda *a, **k: mock.Mock(status_code=200, json=lambda: payload))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1:], [100.5, 101, 99, 1000])


class Parsers(unittest.TestCase):
    PAGE = """<table><tr><th>Date</th><th>Details</th></tr>
      <tr><td>Aug 20, 2026</td><td>150% (i) (D)</td></tr>
      <tr><td>Mar 02, 2026</td><td>100% (F) (D)</td></tr></table>
      <table><tr><th>Item</th><th>2025</th><th>2024</th></tr><tr><td>EPS</td><td>38.5</td><td>30.1</td></tr></table>"""

    def test_fundamentals(self):
        from bs4 import BeautifulSoup
        with mock.patch.object(fetcher, "company_soup", return_value=BeautifulSoup(self.PAGE, "html.parser")), \
             mock.patch.object(fetcher.dt, "datetime", wraps=dt.datetime) as m:
            m.now.return_value = dt.datetime(2026, 10, 27, tzinfo=fetcher.PKT)
            f = fetcher.fundamentals("HUBC")
        self.assertEqual(f["eps"][0]["values"][:2], [38.5, 30.1])
        self.assertEqual(len(f["payouts"]), 2)
        self.assertEqual(f["n_12m"], 2)
        self.assertEqual(f["dps_12m_est"], 25.0)

    def test_indices(self):
        html = "<table><tr><th>Index</th><th>High</th><th>Low</th><th>Current</th><th>Change</th><th>% Change</th></tr><tr><td>KMI 30</td><td>1</td><td>1</td><td>100,000.5</td><td>500</td><td>0.5</td></tr></table>"
        with mock.patch.object(fetcher, "_get", return_value=mock.Mock(text=html)):
            self.assertEqual(fetcher.indices_all()["KMI30"]["level"], 100000.5)


class Trade(unittest.TestCase):
    def test_watch_set(self):
        W = [{c: "" for c in trade.W_COLS} | {"ticker": "LUCK"}]
        H2, W2, err = trade.apply_ops([{"op": "watch_set", "t": "LUCK", "entry": "380", "yield": "5", "pe": ""}], [], W, {})
        self.assertIsNone(err)
        self.assertEqual((W2[0]["entry_price"], W2[0]["target_yield"]), ("380", "5"))
        _, _, err = trade.apply_ops([{"op": "watch_set", "t": "LUCK", "entry": "abc"}], [], W, {})
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
