import math
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date, datetime
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.backtest import regime_churn_diagnostics_v1_4 as module
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


if __name__ == "__main__":
    unittest.main()
