from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant_lab.tools import build_mock_quant_environment, ToolEnvironment
from private_quant_lab.tools.market_sentiment import build_market_sentiment_tools, MARKET_TOOL_NAMES


AS_OF = "2026-09-05T08:45:00+08:00"


class MarketSentimentToolsTests(unittest.TestCase):
    def setUp(self):
        self.env = build_mock_quant_environment().subset(MARKET_TOOL_NAMES)

    def test_news_to_sentiment_and_scores(self):
        news = self.env.run("search_news", {"query": "市场政策", "start_at": "2026-09-04T00:00:00+08:00",
            "as_of": AS_OF, "limit": 2}).output["data"]["news"]
        sentiment = self.env.run("analyze_news_sentiment", {"news": news, "as_of": AS_OF}).output["data"]
        self.assertEqual([n["news_id"] for n in news], [n["news_id"] for n in sentiment["items"]])
        breadth = self.env.run("get_market_breadth", {"market": "CN_A", "lookback_days": 20, "as_of": AS_OF}).output["data"]
        args = {key: breadth[key] for key in ("advancers", "decliners", "turnover_ratio", "annualized_volatility_pct")}
        args.update(as_of=AS_OF, news_sentiment=sentiment["aggregate_sentiment"])
        result = self.env.run("compute_market_regime_metrics", args).output
        self.assertEqual(result["data"]["sentiment_score"], 56)
        self.assertEqual(result["data"]["capital_intensity"], 56)
        self.assertEqual(result["data"]["volatility_risk"], 44)
        self.assertTrue(result["is_mock"])

    def test_data_cutoff_and_missing_news(self):
        result = self.env.run("get_market_breadth", {"market": "CN_A", "lookback_days": 20,
            "as_of": "2026-09-03T00:00:00Z"}).output
        self.assertEqual(result["data"], {})
        self.assertTrue(result["missing_fields"])
        empty = self.env.run("analyze_news_sentiment", {"news": [], "as_of": AS_OF}).output
        self.assertIsNone(empty["data"]["aggregate_sentiment"])
        news = self.env.run("search_news", {"query": "市场", "start_at": "2026-09-04T00:00:00Z",
            "as_of": AS_OF, "limit": 2}).output["data"]["news"]
        with self.assertRaises(ValueError):
            self.env.run("analyze_news_sentiment", {"news": news, "as_of": "2026-09-03T00:00:00Z"})

    def test_runtime_validation_and_permissions(self):
        for limit in (0, True, 21):
            with self.assertRaises(ValueError):
                self.env.run("search_news", {"query": "市场", "start_at": AS_OF, "as_of": AS_OF, "limit": limit})
        with self.assertRaises(ValueError):
            self.env.run("paper_order", {})
        with self.assertRaises(ValueError):
            self.env.run("get_macro_snapshot", {"indicators": ["vix"], "as_of": "2026-09-05"})

    def test_scores_never_call_observation_model(self):
        class NeverMock:
            def simulate(self, *args):
                raise AssertionError("score must be local")
        env = ToolEnvironment(build_market_sentiment_tools(NeverMock()))
        args = {"as_of": AS_OF, "advancers": 1, "decliners": 1,
                "news_sentiment": 0, "turnover_ratio": 1, "annualized_volatility_pct": 20}
        self.assertEqual(env.run("compute_market_regime_metrics", args).output["data"]["sentiment_score"], 50)
        args["news_sentiment"] = float("nan")
        with self.assertRaises(ValueError):
            env.run("compute_market_regime_metrics", args)

    def test_model_data_and_invalid_shape_fallback(self):
        class Mocker:
            invalid = False
            def simulate(self, spec, arguments, fallback):
                from copy import deepcopy
                result = deepcopy(fallback)
                result["observation_source"] = "deepseek"
                result["data"]["advancers"] = "bad" if self.invalid else 3200
                return result
        mocker = Mocker()
        env = ToolEnvironment(build_market_sentiment_tools(mocker))
        args = {"market": "CN_A", "lookback_days": 20, "as_of": AS_OF}
        result = env.run("get_market_breadth", args).output
        self.assertEqual(result["source"], "deepseek_mock")
        self.assertEqual(result["data"]["advancers"], 3200)
        mocker.invalid = True
        result = env.run("get_market_breadth", args).output
        self.assertEqual(result["observation_source"], "local_fallback")
        self.assertEqual(result["data"]["advancers"], 3100)
