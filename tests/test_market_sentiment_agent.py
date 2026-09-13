import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.agents import ReActAgent
from private_quant_lab.agents.market_sentiment import MarketSentimentSession
from private_quant_lab.tools import build_mock_quant_environment
from market_agent_fixture import market_response

AS_OF = "2026-09-05T08:45:00+08:00"


class MarketSentimentAgentTests(unittest.TestCase):
    def setUp(self):
        self.session = MarketSentimentSession(build_mock_quant_environment(), AS_OF)

    def run_complete(self):
        class Model:
            def complete(self, messages, **kwargs):
                return market_response(messages)
        return ReActAgent(Model(), self.session, max_steps=8).run(
            json.dumps({"scheduled_task": {"as_of": AS_OF}}), system_prompt="market")

    def test_full_loop_with_validated_evidence(self):
        result = self.session.validate_final(self.run_complete().final)
        self.assertFalse(result["data_missing"])
        self.assertEqual(result["sentiment_score"], 56)
        self.assertEqual(len(result["evidence"]), 8)

    def test_tampered_final_and_missing_calls_block(self):
        final = json.loads(self.run_complete().final)
        final["sentiment_score"] = 99
        result = self.session.validate_final(json.dumps(final))
        self.assertTrue(result["data_missing"])
        self.assertIsNone(result["sentiment_score"])
        self.assertEqual(result["trading_mode"], "observe")
        isolated = MarketSentimentSession(build_mock_quant_environment(), AS_OF)
        self.assertTrue(isolated.validate_final(json.dumps(final))["data_missing"])

    def test_inputs_cannot_be_rewritten_and_derived_scores_expire(self):
        self.run_complete()
        args = dict(self.session.observations["compute_market_regime_metrics"]["data"]["inputs"])
        args["advancers"] += 1
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.session.run("compute_market_regime_metrics", args)
        news = self.session.observations["search_news"]["data"]["news"]
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.session.run("analyze_news_sentiment", {"as_of": AS_OF, "news": news[:1]})
        self.session.run("get_market_breadth", {"as_of": AS_OF, "market": "CN_A", "lookback_days": 20})
        self.assertNotIn("compute_market_regime_metrics", self.session.observations)

    def test_cutoff_is_bound_to_task(self):
        with self.assertRaisesRegex(ValueError, "scheduled_task"):
            self.session.run("get_macro_snapshot", {"as_of": "2026-09-06T08:45:00+08:00", "indicators": ["vix"]})

    def test_optional_missing_does_not_block_but_required_missing_does(self):
        final = self.run_complete().final
        self.session.run("get_capital_behavior", {"as_of": AS_OF, "indicators": ["margin_balance_change_pct", "etf_share_change_pct", "northbound_net_buy_cny"]})
        result = self.session.validate_final(final)
        self.assertFalse(result["data_missing"])
        self.assertIn("northbound_net_buy_cny", result["indicator_coverage"]["get_capital_behavior"]["missing_optional"])
        self.session.run("get_liquidity_environment", {"as_of": AS_OF, "indicators": ["dr007"]})
        self.assertTrue(self.session.validate_final(final)["data_missing"])

    def test_monthly_publication_cutoff(self):
        env = build_mock_quant_environment()
        earlier = env.run("get_macro_snapshot", {"as_of": "2026-08-31T23:59:00+08:00", "indicators": ["official_pmi"]}).output
        self.assertEqual(earlier["missing_fields"], ["official_pmi"])
        later = env.run("get_macro_snapshot", {"as_of": AS_OF, "indicators": ["official_pmi"]}).output
        self.assertEqual(later["data"]["indicators"][0]["observation_period"], "2026-08")

    def test_derivatives_definitions_and_unknown_evidence(self):
        final = json.loads(self.run_complete().final)
        result = self.session.run("get_derivatives_sentiment", {"as_of": AS_OF, "indicators": ["etf300_volume_pcr", "etf300_oi_pcr"]}).output
        self.assertNotEqual(result["data"]["indicators"][0]["methodology"], result["data"]["indicators"][1]["methodology"])
        final["assessments"]["overall"]["evidence_refs"] = ["made_up_tool"]
        self.assertTrue(self.session.validate_final(json.dumps(final))["data_missing"])

    def test_failed_refresh_cannot_reuse_old_valid_result(self):
        result = self.run_complete()
        with self.assertRaises(ValueError):
            self.session.run("get_macro_snapshot", {"as_of": AS_OF, "indicators": []})
        self.assertTrue(self.session.validate_final(result.final)["data_missing"])
        self.session.run("get_macro_snapshot", {"as_of": AS_OF, "indicators": ["official_pmi", "social_financing_yoy", "m1_yoy", "m2_yoy"]})
        self.assertFalse(self.session.validate_final(result.final)["data_missing"])
