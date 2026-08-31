import math
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date, datetime, timedelta
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.backtest import regime_churn_diagnostics_v1_4 as module
from private_quant.backtest.regime_evaluation import InvalidEvaluationDataError
from private_quant.data import PriceBar
from private_quant.backtest.regime_stabilization import (
    _V1Signal,
    _stabilization_diagnostics,
)
from private_quant.risk import MarketRegime


class V14ContractTests(unittest.TestCase):
    def test_fixed_enums_and_d1_constants(self):
        self.assertEqual(
            tuple(member.name for member in module.V14Boundary),
            ("ZERO_TO_THIRTY", "THIRTY_TO_SEVENTY", "SEVENTY_TO_FULL"),
        )
        self.assertEqual(
            tuple(member.value for member in module.V14Boundary),
            ("zero_to_thirty", "thirty_to_seventy", "seventy_to_full"),
        )
        self.assertEqual(
            tuple(member.name for member in module.V14Direction),
            ("UP", "DOWN"),
        )
        self.assertEqual(
            tuple(member.value for member in module.V14Direction),
            ("up", "down"),
        )
        self.assertEqual(module._D1_INITIAL_CAPITAL, 100_000.0)
        self.assertEqual(module._D1_COST_BPS, 5.0)
        self.assertEqual(module._D1_START, date(2007, 10, 1))
        self.assertEqual(module._D1_END, date(2014, 12, 31))
        self.assertEqual(module._WHIPSAW_WINDOW, 5)
        self.assertEqual(module._RETRY_WINDOW, 10)
        self.assertEqual(module._CLUSTER_WINDOW, 10)

    def test_all_report_records_are_frozen_slotted_with_exact_field_order(self):
        expected_fields = {
            "V14Coverage": (
                "symbol",
                "first_date",
                "last_date",
                "rows",
            ),
            "V14ExposureChangeEvent": (
                "signal_index",
                "signal_date",
                "from_exposure",
                "to_exposure",
                "direction",
                "primary_boundary",
                "crossed_boundaries",
                "v1_regime",
                "v1_score",
                "v1_cap",
            ),
            "V14PairReturnAttribution": (
                "spy_cumulative_return",
                "baseline_portfolio_return",
                "full_spy_comparator_return",
                "transaction_cost_drag",
            ),
            "V14WhipsawPair": (
                "opener",
                "closer",
                "latency_sessions",
                "primary_boundary",
                "crossed_boundaries",
                "failed_reentry",
                "failed_derisk",
                "opening_transaction_cost",
                "closing_transaction_cost",
                "pair_transaction_cost",
                "return_attribution",
            ),
            "V14RetryEvent": (
                "failed_pair_index",
                "retry_event",
                "primary_boundary",
                "retry_latency_sessions",
                "failed_again",
            ),
            "V14ChurnCluster": (
                "start_date",
                "end_date",
                "start_opener_index",
                "end_closer_index",
                "pair_indices",
                "pair_count",
                "schedule_change_count",
                "boundaries",
                "dominant_boundaries",
                "failed_reentry_count",
                "failed_derisk_count",
                "absolute_exposure_turnover",
                "transaction_cost",
            ),
            "V14BoundaryCount": ("boundary", "count", "share"),
            "V14LatencyCount": ("latency_sessions", "count", "share"),
            "V14DirectionCount": ("direction", "count", "share"),
            "V14RetryBoundaryStats": (
                "boundary",
                "retry_count",
                "retry_failure_count",
                "retry_failure_rate",
            ),
            "V14ReturnSummary": (
                "mean_spy_return",
                "median_spy_return",
                "mean_baseline_return",
                "median_baseline_return",
                "mean_full_spy_return",
                "median_full_spy_return",
                "mean_transaction_cost_drag",
                "median_transaction_cost_drag",
            ),
            "V14WhipsawAnatomyReport": (
                "analysis_start",
                "analysis_end",
                "spy_coverage",
                "bil_coverage",
                "common_interval_count",
                "initial_capital",
                "transaction_cost_bps",
                "schedule_change_count",
                "annualized_turnover",
                "total_transaction_cost",
                "whipsaw_pair_count",
                "whipsaw_rate",
                "pairs",
                "primary_boundary_breakdown",
                "crossed_boundary_incidence",
                "latency_breakdown",
                "share_within_2_sessions",
                "share_within_3_sessions",
                "direction_breakdown",
                "failed_reentry_count",
                "failed_reentry_share",
                "failed_derisk_count",
                "failed_derisk_share",
                "retries",
                "retry_count",
                "retry_success_count",
                "retry_failure_count",
                "retry_failure_rate",
                "retry_by_boundary",
                "clusters",
                "cluster_count",
                "clustered_whipsaw_count",
                "clustered_whipsaw_share",
                "multi_pair_cluster_count",
                "max_pair_count_in_cluster",
                "cluster_dominant_boundary_incidence",
                "cluster_absolute_exposure_turnover",
                "cluster_transaction_cost",
                "cluster_transaction_cost_share",
                "whipsaw_pair_transaction_cost",
                "whipsaw_pair_transaction_cost_share",
                "return_summary",
            ),
        }
        for class_name, names in expected_fields.items():
            contract = getattr(module, class_name)
            self.assertTrue(is_dataclass(contract), class_name)
            self.assertEqual(tuple(field.name for field in fields(contract)), names)
            self.assertEqual(contract.__slots__, names)
            self.assertTrue(contract.__dataclass_params__.frozen)
            instance = contract(*(None for _ in names))
            with self.assertRaises(FrozenInstanceError):
                setattr(instance, names[0], None)


class ExposureChangeEventTests(unittest.TestCase):
    @staticmethod
    def _signal(day, score=60, regime=MarketRegime.BULL, cap=1.0):
        return _V1Signal(day, score, regime, cap)

    def test_first_target_is_context_and_multi_level_boundaries_follow_movement(self):
        signals = (
            _V1Signal(date(2010, 1, 1), 60, MarketRegime.BULL, 1.0),
            _V1Signal(date(2010, 1, 2), 10, MarketRegime.RISK_OFF, 0.3),
            _V1Signal(date(2010, 1, 3), -30, MarketRegime.BEAR, 0.0),
            _V1Signal(date(2010, 1, 4), 60, MarketRegime.BULL, 1.0),
        )
        events = module._extract_change_events(signals)

        self.assertEqual(len(events), 3)
        self.assertEqual(tuple(event.signal_index for event in events), (1, 2, 3))
        self.assertEqual(events[0].from_exposure, 1.0)
        self.assertEqual(events[0].to_exposure, 0.3)
        self.assertEqual(events[0].direction, module.V14Direction.DOWN)
        self.assertEqual(
            events[0].primary_boundary,
            module.V14Boundary.SEVENTY_TO_FULL,
        )
        self.assertEqual(
            events[0].crossed_boundaries,
            (
                module.V14Boundary.SEVENTY_TO_FULL,
                module.V14Boundary.THIRTY_TO_SEVENTY,
            ),
        )
        self.assertEqual(
            events[2].crossed_boundaries,
            (
                module.V14Boundary.ZERO_TO_THIRTY,
                module.V14Boundary.THIRTY_TO_SEVENTY,
                module.V14Boundary.SEVENTY_TO_FULL,
            ),
        )
        self.assertEqual(events[2].primary_boundary, module.V14Boundary.ZERO_TO_THIRTY)
        self.assertEqual(events[2].v1_score, 60)
        self.assertEqual(events[2].v1_regime, MarketRegime.BULL)
        self.assertEqual(events[2].v1_cap, 1.0)

    def test_unchanged_targets_produce_no_events(self):
        signals = (
            self._signal(date(2010, 1, 1), cap=0.3),
            self._signal(date(2010, 1, 2), cap=0.3),
            self._signal(date(2010, 1, 3), cap=0.3),
        )
        self.assertEqual(module._extract_change_events(signals), ())

    def test_rejects_invalid_signal_records_before_extraction(self):
        valid = self._signal(date(2010, 1, 1))
        invalid_signals = (
            (
                self._signal(datetime(2010, 1, 1)),
                self._signal(date(2010, 1, 2)),
            ),
            (
                valid,
                self._signal(date(2010, 1, 1)),
            ),
            (
                valid,
                self._signal(date(2010, 1, 3)),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), score=True),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), score=math.inf),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), score=math.nan),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), regime="BULL"),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), cap=True),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), cap=math.inf),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), cap=math.nan),
                self._signal(date(2010, 1, 2)),
            ),
            (
                self._signal(date(2010, 1, 1), cap=0.4),
                self._signal(date(2010, 1, 2)),
            ),
        )
        for signals in invalid_signals:
            with self.subTest(signals=signals):
                with self.assertRaises(ValueError):
                    module._extract_change_events(signals)

    def test_rejects_spoof_and_subclass_records(self):
        spoof = SimpleNamespace(
            signal_date=date(2010, 1, 1),
            score=60,
            regime=MarketRegime.BULL,
            maximum_long_exposure=1.0,
        )

        class SignalSubclass(_V1Signal):
            pass

        subclass = SignalSubclass(date(2010, 1, 1), 60, MarketRegime.BULL, 1.0)
        for signal in (spoof, subclass):
            with self.subTest(signal_type=type(signal).__name__):
                with self.assertRaises(ValueError):
                    module._extract_change_events((signal,))


class WhipsawPairTests(unittest.TestCase):
    @staticmethod
    def _signals(schedule):
        return tuple(
            _V1Signal(
                date(2020, 1, signal_index),
                60,
                MarketRegime.BULL,
                exposure,
            )
            for signal_index, exposure in enumerate(schedule, start=1)
        )

    @classmethod
    def _pairs(cls, schedule):
        signals = cls._signals(schedule)
        events = module._extract_change_events(signals)
        extractor = getattr(module, "_extract_v14_whipsaw_pairs", None)
        if extractor is None:
            raise AssertionError("V1.4 whipsaw pair extractor is missing")
        return extractor(signals, events)

    @staticmethod
    def _state_points(schedule):
        return tuple(
            SimpleNamespace(
                signal_date=date(2020, 1, signal_index),
                overlay_exposure=exposure,
                v1_maximum_long_exposure=exposure,
            )
            for signal_index, exposure in enumerate(schedule, start=1)
        )

    def test_accepts_latencies_one_through_five_but_rejects_six(self):
        for latency in range(1, 6):
            schedule = (1.0, 0.3) + (0.3,) * (latency - 1) + (1.0,)
            with self.subTest(latency=latency):
                pairs = self._pairs(schedule)
                self.assertEqual(len(pairs), 1)
                self.assertEqual(pairs[0].latency_sessions, latency)

        schedule = (1.0, 0.3) + (0.3,) * 5 + (1.0,)
        self.assertEqual(self._pairs(schedule), ())

    def test_wrong_direction_and_non_crossing_closers_are_rejected(self):
        for schedule in (
            (1.0, 0.3, 0.7),
            (1.0, 0.3, 0.0),
            (0.0, 0.3, 0.7),
        ):
            with self.subTest(schedule=schedule):
                self.assertEqual(self._pairs(schedule), ())

    def test_pairs_are_non_overlapping_and_a_closer_is_used_once(self):
        schedule = (1.0, 0.3, 0.7, 1.0, 0.3, 1.0)
        pairs = self._pairs(schedule)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(
            tuple((pair.opener.signal_index, pair.closer.signal_index) for pair in pairs),
            ((1, 3), (4, 5)),
        )

        one_closer_schedule = (1.0, 0.3, 0.7, 0.3, 1.0)
        one_pair = self._pairs(one_closer_schedule)
        self.assertEqual(len(one_pair), 1)
        self.assertEqual(one_pair[0].closer.signal_index, 4)

    def test_opener_direction_sets_failed_reentry_or_failed_derisk(self):
        failed_reentry = self._pairs((0.0, 0.3, 0.0))[0]
        self.assertTrue(failed_reentry.failed_reentry)
        self.assertFalse(failed_reentry.failed_derisk)

        failed_derisk = self._pairs((1.0, 0.3, 1.0))[0]
        self.assertFalse(failed_derisk.failed_reentry)
        self.assertTrue(failed_derisk.failed_derisk)
        self.assertEqual(
            failed_derisk.crossed_boundaries,
            failed_derisk.opener.crossed_boundaries,
        )
        self.assertEqual(
            failed_derisk.primary_boundary,
            failed_derisk.opener.primary_boundary,
        )
        self.assertEqual(
            (
                failed_derisk.opening_transaction_cost,
                failed_derisk.closing_transaction_cost,
                failed_derisk.pair_transaction_cost,
                failed_derisk.return_attribution,
            ),
            (0.0, 0.0, 0.0, None),
        )

    def test_pair_count_has_parity_with_frozen_stabilization_diagnostics(self):
        schedules = (
            (1.0, 0.3, 1.0),
            (1.0, 0.7, 0.3, 1.0),
            (0.0, 0.3, 0.0, 0.3, 0.0),
            (1.0, 0.3, 0.7, 1.0, 0.3, 1.0),
            (0.0, 0.7, 1.0, 0.3, 0.0),
        )
        for schedule in schedules:
            with self.subTest(schedule=schedule):
                signals = self._signals(schedule)
                events = module._extract_change_events(signals)
                pairs = self._pairs(schedule)
                diagnostics = _stabilization_diagnostics(
                    self._state_points(schedule),
                    start=date(2020, 1, 1),
                    end=date(2020, 1, len(schedule)),
                    include_reentry_detail=False,
                )
                self.assertEqual(
                    len(events),
                    diagnostics.schedule_exposure_changes,
                )
                self.assertEqual(len(pairs), diagnostics.whipsaw_pairs)

        parity_schedule = (1.0, 0.3, 0.7, 1.0, 0.3, 1.0)
        signals = self._signals(parity_schedule)
        events = module._extract_change_events(signals)
        self.assertEqual(len(events), 5)
        self.assertEqual(len(self._pairs(parity_schedule)), 2)


class RetryTests(unittest.TestCase):
    def _extract(self, events, pairs):
        extractor = getattr(module, "_extract_v14_retries", None)
        self.assertIsNotNone(extractor, "V1.4 retry extractor is missing")
        return extractor(events, pairs)

    @classmethod
    def _retry_case(cls, retry_distance):
        schedule = [0.0, 0.3, 0.0]
        schedule.extend([0.0] * (retry_distance - 1))
        schedule.append(0.3)
        signals = WhipsawPairTests._signals(tuple(schedule))
        events = module._extract_change_events(signals)
        pairs = module._extract_v14_whipsaw_pairs(signals, events)
        return events, pairs

    def test_same_boundary_retry_includes_exact_ten_session_distance(self):
        events, pairs = self._retry_case(10)

        retries = self._extract(events, pairs)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0].failed_pair_index, 0)
        self.assertEqual(retries[0].retry_event.signal_index, 12)
        self.assertEqual(retries[0].primary_boundary, module.V14Boundary.ZERO_TO_THIRTY)
        self.assertEqual(retries[0].retry_latency_sessions, 10)
        self.assertFalse(retries[0].failed_again)

    def test_retry_outside_window_is_not_extracted(self):
        events, pairs = self._retry_case(11)

        self.assertEqual(self._extract(events, pairs), ())

    def test_retry_uses_first_upward_same_primary_boundary_only_once(self):
        schedule = (0.0, 0.3, 0.0, 0.7, 0.3, 0.7)
        signals = WhipsawPairTests._signals(schedule)
        events = module._extract_change_events(signals)
        pairs = module._extract_v14_whipsaw_pairs(signals, events)

        retries = self._extract(events, pairs)

        self.assertEqual(
            tuple((pair.opener.signal_index, pair.closer.signal_index) for pair in pairs),
            ((1, 2), (4, 5)),
        )
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0].retry_event.signal_index, 3)
        self.assertEqual(retries[0].retry_latency_sessions, 1)
        self.assertFalse(retries[0].failed_again)

    def test_retry_rejects_downward_event_even_when_primary_boundary_matches(self):
        signals = WhipsawPairTests._signals((0.0, 0.3, 0.0))
        events = module._extract_change_events(signals)
        pair = module._extract_v14_whipsaw_pairs(signals, events)[0]
        wrong_direction = module.V14ExposureChangeEvent(
            signal_index=3,
            signal_date=date(2020, 1, 4),
            from_exposure=0.3,
            to_exposure=0.0,
            direction=module.V14Direction.DOWN,
            primary_boundary=module.V14Boundary.ZERO_TO_THIRTY,
            crossed_boundaries=(module.V14Boundary.ZERO_TO_THIRTY,),
            v1_regime=MarketRegime.BULL,
            v1_score=60,
            v1_cap=0.0,
        )

        self.assertEqual(self._extract((events[0], events[1], wrong_direction), (pair,)), ())

    def test_failed_again_requires_exact_retry_event_to_open_later_failed_pair(self):
        schedule = (0.0, 0.3, 0.0, 0.3, 0.0)
        signals = WhipsawPairTests._signals(schedule)
        events = module._extract_change_events(signals)
        pairs = module._extract_v14_whipsaw_pairs(signals, events)

        retries = self._extract(events, pairs)

        self.assertEqual(len(pairs), 2)
        self.assertEqual(retries[0].retry_event.signal_index, pairs[1].opener.signal_index)
        self.assertTrue(retries[0].failed_again)


class ClusterTests(unittest.TestCase):
    def _build(self, events, pairs):
        builder = getattr(module, "_build_v14_clusters", None)
        self.assertIsNotNone(builder, "V1.4 cluster builder is missing")
        return builder(events, pairs)

    @staticmethod
    def _event(index, from_exposure, to_exposure, crossed_boundaries):
        return module.V14ExposureChangeEvent(
            signal_index=index,
            signal_date=date(2020, 1, index + 1),
            from_exposure=from_exposure,
            to_exposure=to_exposure,
            direction=(
                module.V14Direction.UP
                if to_exposure > from_exposure
                else module.V14Direction.DOWN
            ),
            primary_boundary=crossed_boundaries[0],
            crossed_boundaries=tuple(crossed_boundaries),
            v1_regime=MarketRegime.BULL,
            v1_score=60,
            v1_cap=to_exposure,
        )

    @classmethod
    def _pair(cls, opener, closer):
        return module.V14WhipsawPair(
            opener=opener,
            closer=closer,
            latency_sessions=closer.signal_index - opener.signal_index,
            primary_boundary=opener.primary_boundary,
            crossed_boundaries=opener.crossed_boundaries,
            failed_reentry=opener.direction is module.V14Direction.UP,
            failed_derisk=opener.direction is module.V14Direction.DOWN,
            opening_transaction_cost=0.0,
            closing_transaction_cost=0.0,
            pair_transaction_cost=0.0,
            return_attribution=None,
        )

    def test_joins_at_exact_ten_opener_distance_but_splits_at_eleven(self):
        boundary = (module.V14Boundary.ZERO_TO_THIRTY,)
        opener_one = self._event(1, 0.0, 0.3, boundary)
        closer_one = self._event(2, 0.3, 0.0, boundary)
        opener_two = self._event(11, 0.0, 0.3, boundary)
        closer_two = self._event(12, 0.3, 0.0, boundary)
        events = (opener_one, closer_one, opener_two, closer_two)
        pairs = (self._pair(opener_one, closer_one), self._pair(opener_two, closer_two))

        joined = self._build(events, pairs)

        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0].pair_indices, (0, 1))

        opener_three = self._event(12, 0.0, 0.3, boundary)
        closer_three = self._event(13, 0.3, 0.0, boundary)
        split = self._build(
            (opener_one, closer_one, opener_three, closer_three),
            (self._pair(opener_one, closer_one), self._pair(opener_three, closer_three)),
        )
        self.assertEqual(tuple(cluster.pair_indices for cluster in split), ((0,), (1,)))

    def test_requires_shared_crossed_boundary_and_chains_adjacent_pairs(self):
        zero_to_thirty = (module.V14Boundary.ZERO_TO_THIRTY,)
        thirty_to_seventy = (module.V14Boundary.THIRTY_TO_SEVENTY,)
        pair_specs = (
            (1, 2, zero_to_thirty),
            (9, 10, zero_to_thirty),
            (17, 18, zero_to_thirty),
        )
        events = tuple(
            event
            for opener_index, closer_index, boundary in pair_specs
            for event in (
                self._event(opener_index, 0.0, 0.3, boundary),
                self._event(closer_index, 0.3, 0.0, boundary),
            )
        )
        pairs = tuple(
            self._pair(events[offset], events[offset + 1])
            for offset in (0, 2, 4)
        )

        chained = self._build(events, pairs)

        self.assertEqual(len(chained), 1)
        self.assertEqual(chained[0].pair_indices, (0, 1, 2))

        disjoint_opener = self._event(25, 0.3, 0.7, thirty_to_seventy)
        disjoint_closer = self._event(26, 0.7, 0.3, thirty_to_seventy)
        split = self._build(
            events + (disjoint_opener, disjoint_closer),
            pairs + (self._pair(disjoint_opener, disjoint_closer),),
        )
        self.assertEqual(tuple(cluster.pair_indices for cluster in split), ((0, 1, 2), (3,)))

    def test_tied_dominant_boundaries_are_kept_in_enum_order(self):
        boundaries = (
            module.V14Boundary.ZERO_TO_THIRTY,
            module.V14Boundary.THIRTY_TO_SEVENTY,
        )
        opener_one = self._event(1, 0.0, 0.7, boundaries)
        closer_one = self._event(2, 0.7, 0.0, tuple(reversed(boundaries)))
        opener_two = self._event(9, 0.7, 0.0, tuple(reversed(boundaries)))
        closer_two = self._event(10, 0.0, 0.7, boundaries)
        events = (opener_one, closer_one, opener_two, closer_two)
        pairs = (self._pair(opener_one, closer_one), self._pair(opener_two, closer_two))

        cluster = self._build(events, pairs)[0]

        self.assertEqual(
            cluster.dominant_boundaries,
            (
                module.V14Boundary.ZERO_TO_THIRTY,
                module.V14Boundary.THIRTY_TO_SEVENTY,
            ),
        )

    def test_schedule_count_and_turnover_use_actual_events_once(self):
        boundary = (module.V14Boundary.ZERO_TO_THIRTY,)
        opener = self._event(1, 0.0, 0.3, boundary)
        intervening = self._event(
            3,
            0.3,
            1.0,
            (
                module.V14Boundary.THIRTY_TO_SEVENTY,
                module.V14Boundary.SEVENTY_TO_FULL,
            ),
        )
        closer = self._event(5, 1.0, 0.0, (
            module.V14Boundary.SEVENTY_TO_FULL,
            module.V14Boundary.THIRTY_TO_SEVENTY,
            module.V14Boundary.ZERO_TO_THIRTY,
        ))
        events = (opener, intervening, closer)
        pairs = (self._pair(opener, closer),)

        cluster = self._build(events, pairs)[0]

        self.assertEqual(cluster.schedule_change_count, 3)
        self.assertEqual(cluster.absolute_exposure_turnover, 2.0)
        self.assertEqual(cluster.transaction_cost, 0.0)


class _ProtocolEngine:
    def __init__(self, signal_dates, exposures):
        self.exposures = dict(zip(signal_dates, exposures))
        self.calls = []

    def evaluate(self, spy_history, *, as_of, qqq_bars):
        if qqq_bars is not None:
            raise AssertionError("V1.4 must not pass QQQ bars")
        if as_of > module._D1_END:
            raise AssertionError("V1.4 classifier call exceeded D1")
        self.calls.append(as_of)
        exposure = self.exposures[as_of]
        regime, score = {
            0.0: (MarketRegime.BEAR, -30),
            0.3: (MarketRegime.RISK_OFF, 0),
            0.7: (MarketRegime.CAUTIOUS_BULL, 20),
            1.0: (MarketRegime.BULL, 60),
        }[exposure]
        return SimpleNamespace(
            maximum_long_exposure=exposure,
            regime=regime,
            score=score,
        )


def _make_price_bar(symbol, trading_date, adjusted_close):
    return PriceBar(
        symbol=symbol,
        trading_date=trading_date,
        open=adjusted_close,
        high=adjusted_close,
        low=adjusted_close,
        close=adjusted_close,
        adjusted_close=adjusted_close,
        volume=1,
    )


def _synthetic_d1_dataset(
    exposures,
    *,
    spy_returns=(),
    bil_returns=(),
):
    exposures = tuple(exposures)
    if not exposures:
        raise ValueError("synthetic D1 dataset needs at least one interval")
    signal_dates = tuple(
        module._D1_START + timedelta(days=index)
        for index in range(len(exposures))
    )
    active_dates = signal_dates + (module._D1_END,)
    all_signal_exposures = exposures + (exposures[-1],)

    def prices(returns):
        values = [100.0]
        for value in returns:
            values.append(values[-1] * (1.0 + value))
        return tuple(values + [values[-1]] * (len(active_dates) - len(values)))

    spy_prices = prices(tuple(spy_returns))
    bil_prices = prices(tuple(bil_returns))
    warmup_dates = tuple(
        module._D1_START - timedelta(days=251 - index)
        for index in range(251)
    )
    spy_bars = tuple(
        _make_price_bar("SPY", trading_date, 100.0)
        for trading_date in warmup_dates
    ) + tuple(
        _make_price_bar("SPY", trading_date, adjusted_close)
        for trading_date, adjusted_close in zip(active_dates, spy_prices)
    )
    bil_bars = tuple(
        _make_price_bar("BIL", trading_date, adjusted_close)
        for trading_date, adjusted_close in zip(active_dates, bil_prices)
    )
    return spy_bars, bil_bars, signal_dates, all_signal_exposures


class _FuturePriceBar:
    symbol = "SPY"
    trading_date = date(2015, 1, 2)

    @property
    def adjusted_close(self):
        raise AssertionError("future price must not be read")


class _FutureBILPriceBar:
    symbol = "BIL"
    trading_date = date(2015, 1, 2)

    @property
    def adjusted_close(self):
        raise AssertionError("future BIL price must not be read")


class _MalformedDateBar:
    symbol = "SPY"
    trading_date = "not-a-date"
    adjusted_close = 100.0


class D1OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            callable(getattr(module, "analyze_regime_churn_v1_4", None)),
            "V1.4 orchestration entry point is missing",
        )

    def _dataset(self, exposures=(0.0, 0.3, 0.0, 0.3, 0.0)):
        spy, bil, signal_dates, all_exposures = _synthetic_d1_dataset(exposures)
        return spy, bil, _ProtocolEngine(signal_dates + (module._D1_END,), all_exposures)

    def test_fixed_boundaries_signature_and_point_in_time_engine_calls(self):
        spy_bars, bil_bars, engine = self._dataset()

        report = module.analyze_regime_churn_v1_4(spy_bars, bil_bars, engine=engine)

        signature = inspect.signature(module.analyze_regime_churn_v1_4)
        self.assertEqual(
            tuple(signature.parameters),
            ("spy_bars", "bil_bars", "engine"),
        )
        self.assertEqual(signature.parameters["engine"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(signature.parameters["engine"].default)
        self.assertEqual(report.analysis_start, module._D1_START)
        self.assertEqual(report.analysis_end, module._D1_END)
        self.assertEqual(report.spy_coverage.last_date, module._D1_END)
        self.assertEqual(report.bil_coverage.last_date, module._D1_END)
        self.assertEqual(engine.calls[0], module._D1_START)
        self.assertTrue(all(as_of <= module._D1_END for as_of in engine.calls))
        self.assertEqual(len(engine.calls), len(set(engine.calls)))

    def test_future_prices_are_date_filtered_without_property_reads(self):
        spy_bars, bil_bars, engine = self._dataset()
        baseline = module.analyze_regime_churn_v1_4(spy_bars, bil_bars, engine=engine)

        future_report = module.analyze_regime_churn_v1_4(
            spy_bars + (_FuturePriceBar(),),
            bil_bars + (_FutureBILPriceBar(),),
            engine=self._dataset()[2],
        )

        self.assertEqual(future_report, baseline)

    def test_malformed_future_date_fails_before_classifier_call(self):
        spy_bars, bil_bars, engine = self._dataset()

        with self.assertRaises(InvalidEvaluationDataError):
            module.analyze_regime_churn_v1_4(
                spy_bars + (_MalformedDateBar(),), bil_bars, engine=engine
            )
        self.assertEqual(engine.calls, [])

    def test_active_input_validation_fails_closed_before_classifier(self):
        spy_bars, bil_bars, _ = self._dataset()
        active_date = module._D1_START + timedelta(days=1)
        valid_active = next(
            bar for bar in spy_bars if bar.trading_date == active_date
        )
        invalid_values = (0.0, math.inf)
        invalid_cases = {
            "duplicate": (
                spy_bars + (valid_active,),
                bil_bars,
            ),
            "wrong_symbol": (
                tuple(
                    SimpleNamespace(
                        symbol=("QQQ" if bar.trading_date == active_date else bar.symbol),
                        trading_date=bar.trading_date,
                        adjusted_close=bar.adjusted_close,
                    )
                    for bar in spy_bars
                ),
                bil_bars,
            ),
        }
        for invalid_value in invalid_values:
            invalid_cases[f"adjusted_close_{invalid_value}"] = (
                tuple(
                    SimpleNamespace(
                        symbol=bar.symbol,
                        trading_date=bar.trading_date,
                        adjusted_close=(
                            invalid_value
                            if bar.trading_date == active_date
                            else bar.adjusted_close
                        ),
                    )
                    for bar in spy_bars
                ),
                bil_bars,
            )

        for name, (invalid_spy, invalid_bil) in invalid_cases.items():
            with self.subTest(case=name):
                engine = self._dataset()[2]
                with self.assertRaises(InvalidEvaluationDataError):
                    module.analyze_regime_churn_v1_4(
                        invalid_spy, invalid_bil, engine=engine
                    )
                self.assertEqual(engine.calls, [])

    def test_missing_boundaries_warmup_and_common_intervals_fail(self):
        spy_bars, bil_bars, _ = self._dataset()
        cases = {
            "missing_spy_start": (
                tuple(bar for bar in spy_bars if bar.trading_date != module._D1_START),
                bil_bars,
            ),
            "missing_spy_end": (
                tuple(bar for bar in spy_bars if bar.trading_date != module._D1_END),
                bil_bars,
            ),
            "missing_bil_start": (
                spy_bars,
                tuple(bar for bar in bil_bars if bar.trading_date != module._D1_START),
            ),
            "missing_bil_end": (
                spy_bars,
                tuple(bar for bar in bil_bars if bar.trading_date != module._D1_END),
            ),
            "insufficient_warmup": (
                spy_bars[1:],
                bil_bars,
            ),
            "no_common_intervals": (
                spy_bars[:252] + (spy_bars[251],),
                bil_bars[:1],
            ),
        }
        for name, (invalid_spy, invalid_bil) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(InvalidEvaluationDataError):
                    module.analyze_regime_churn_v1_4(
                        invalid_spy, invalid_bil, engine=self._dataset()[2]
                    )


class D1AccountingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            callable(getattr(module, "analyze_regime_churn_v1_4", None)),
            "V1.4 orchestration entry point is missing",
        )

    def test_opening_cost_is_baseline_only_and_cluster_cost_covers_intervening_event(self):
        exposures = (0.3, 1.0, 0.7, 0.3)
        spy_bars, bil_bars, signal_dates, all_exposures = _synthetic_d1_dataset(exposures)
        engine = _ProtocolEngine(signal_dates + (module._D1_END,), all_exposures)

        report = module.analyze_regime_churn_v1_4(spy_bars, bil_bars, engine=engine)

        opening_cost = 15.0
        opener_cost = 34.99475
        intervening_cost = 14.9925007875
        closer_cost = 19.9870025498425
        self.assertEqual(report.schedule_change_count, 3)
        self.assertAlmostEqual(
            report.total_transaction_cost,
            opening_cost + opener_cost + intervening_cost + closer_cost,
        )
        self.assertEqual(report.whipsaw_pair_count, 1)
        pair = report.pairs[0]
        self.assertAlmostEqual(pair.opening_transaction_cost, opener_cost)
        self.assertAlmostEqual(pair.closing_transaction_cost, closer_cost)
        self.assertAlmostEqual(pair.pair_transaction_cost, opener_cost + closer_cost)
        self.assertEqual(report.clusters[0].schedule_change_count, 3)
        self.assertAlmostEqual(
            report.clusters[0].transaction_cost,
            opener_cost + intervening_cost + closer_cost,
        )

    def test_structural_classification_is_independent_of_returns(self):
        exposures = (0.0, 0.3, 0.0, 0.3, 0.0)
        spy_a, bil_a, signal_dates, all_exposures = _synthetic_d1_dataset(
            exposures,
            spy_returns=(0.01, -0.02, 0.03, -0.01, 0.02),
            bil_returns=(0.001, 0.001, 0.001, 0.001, 0.001),
        )
        spy_b, bil_b, _, _ = _synthetic_d1_dataset(
            exposures,
            spy_returns=(-0.03, 0.02, -0.01, 0.04, -0.02),
            bil_returns=(-0.001, -0.001, -0.001, -0.001, -0.001),
        )
        report_a = module.analyze_regime_churn_v1_4(
            spy_a,
            bil_a,
            engine=_ProtocolEngine(signal_dates + (module._D1_END,), all_exposures),
        )
        report_b = module.analyze_regime_churn_v1_4(
            spy_b,
            bil_b,
            engine=_ProtocolEngine(signal_dates + (module._D1_END,), all_exposures),
        )

        self.assertEqual(
            tuple(
                (
                    event.signal_index,
                    event.signal_date,
                    event.from_exposure,
                    event.to_exposure,
                    event.direction,
                    event.primary_boundary,
                    event.crossed_boundaries,
                    event.v1_regime,
                    event.v1_score,
                    event.v1_cap,
                )
                for pair in report_a.pairs
                for event in (pair.opener, pair.closer)
            ),
            tuple(
                (
                    event.signal_index,
                    event.signal_date,
                    event.from_exposure,
                    event.to_exposure,
                    event.direction,
                    event.primary_boundary,
                    event.crossed_boundaries,
                    event.v1_regime,
                    event.v1_score,
                    event.v1_cap,
                )
                for pair in report_b.pairs
                for event in (pair.opener, pair.closer)
            ),
        )
        self.assertEqual(
            tuple(
                (
                    pair.latency_sessions,
                    pair.primary_boundary,
                    pair.crossed_boundaries,
                    pair.failed_reentry,
                    pair.failed_derisk,
                )
                for pair in report_a.pairs
            ),
            tuple(
                (
                    pair.latency_sessions,
                    pair.primary_boundary,
                    pair.crossed_boundaries,
                    pair.failed_reentry,
                    pair.failed_derisk,
                )
                for pair in report_b.pairs
            ),
        )
        self.assertEqual(report_a.retries, report_b.retries)
        self.assertEqual(
            tuple(
                (
                    cluster.pair_indices,
                    cluster.boundaries,
                    cluster.dominant_boundaries,
                    cluster.failed_reentry_count,
                    cluster.failed_derisk_count,
                    cluster.absolute_exposure_turnover,
                )
                for cluster in report_a.clusters
            ),
            tuple(
                (
                    cluster.pair_indices,
                    cluster.boundaries,
                    cluster.dominant_boundaries,
                    cluster.failed_reentry_count,
                    cluster.failed_derisk_count,
                    cluster.absolute_exposure_turnover,
                )
                for cluster in report_b.clusters
            ),
        )
        self.assertNotEqual(
            tuple(pair.return_attribution for pair in report_a.pairs),
            tuple(pair.return_attribution for pair in report_b.pairs),
        )

    def test_empty_pair_report_has_fixed_rows_and_none_denominators(self):
        exposures = (0.0, 0.0, 0.0, 0.0)
        spy_bars, bil_bars, signal_dates, all_exposures = _synthetic_d1_dataset(exposures)
        report = module.analyze_regime_churn_v1_4(
            spy_bars,
            bil_bars,
            engine=_ProtocolEngine(signal_dates + (module._D1_END,), all_exposures),
        )

        self.assertEqual(report.pairs, ())
        self.assertEqual(report.retries, ())
        self.assertEqual(report.clusters, ())
        self.assertEqual(
            tuple(row.boundary for row in report.primary_boundary_breakdown),
            tuple(module.V14Boundary),
        )
        self.assertEqual(len(report.latency_breakdown), 5)
        self.assertEqual(len(report.direction_breakdown), 2)
        self.assertEqual(len(report.retry_by_boundary), 3)
        self.assertEqual(len(report.cluster_dominant_boundary_incidence), 3)
        self.assertIsNone(report.whipsaw_rate)
        self.assertIsNone(report.share_within_2_sessions)
        self.assertIsNone(report.share_within_3_sessions)
        self.assertIsNone(report.failed_reentry_share)
        self.assertIsNone(report.failed_derisk_share)
        self.assertIsNone(report.retry_failure_rate)
        self.assertIsNone(report.clustered_whipsaw_share)
        self.assertIsNone(report.return_summary.mean_spy_return)
        self.assertIsNone(report.return_summary.median_transaction_cost_drag)


if __name__ == "__main__":
    unittest.main()
