"""Contract tests for the V1.3 recovery-episode overlay."""

from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from types import SimpleNamespace
from enum import Enum
import math
import unittest

from private_quant.backtest import regime_reentry_v1_3 as module
from private_quant.backtest.regime_stabilization import _V1Signal, _stabilization_diagnostics
from private_quant.risk.market_regime import MarketRegime
from private_quant.data import PriceBar


class ProtocolEngine:
    def __init__(self, caps=None):
        self.caps = caps or {}
        self.calls = []

    def evaluate(self, spy_bars, *, as_of, qqq_bars):
        assert qqq_bars is None
        assert all(bar.trading_date <= as_of for bar in spy_bars)
        self.calls.append(as_of)
        cap = self.caps.get(as_of, 1.0)
        return SimpleNamespace(score=60 if cap == 1 else -50,
                               regime=MarketRegime.BULL if cap == 1 else MarketRegime.BEAR,
                               maximum_long_exposure=cap)


def protocol_bars(days=None):
    days = days or [date(2007, 10, 1), date(2014, 12, 30), date(2014, 12, 31),
                    date(2015, 1, 1), date(2015, 1, 2), date(2020, 12, 31)]
    warmup = [days[0] - timedelta(days=260-i) for i in range(260)]
    def bars(symbol, dates):
        return [PriceBar(symbol, day, 100., 100., 100., 100., 100., 1000) for day in dates]
    return bars('SPY', warmup + days), bars('BIL', days)


def literal_periods(candidate=None, cagr=.1001, split=.095, turnover=.85,
                    whipsaws=8, drawdown=-.20):
    return tuple(module.V13CandidatePeriodResult(
        candidate, period,
        SimpleNamespace(cagr=cagr if period is module.ResearchPeriod.COMBINED_SELECTION else split,
                        annualized_turnover=turnover, max_drawdown=drawdown),
        SimpleNamespace(whipsaw_pairs=whipsaws), ())
        for period in (module.ResearchPeriod.DEVELOPMENT, module.ResearchPeriod.VALIDATION,
                       module.ResearchPeriod.COMBINED_SELECTION))


class SelectionProtocolTests(unittest.TestCase):
    def test_exact_seven_gates_and_undefined_denominators(self):
        baseline = literal_periods(cagr=.10, split=.10, turnover=1., whipsaws=10)
        candidate = module.FIXED_V13_CANDIDATES[0]
        passing = module._qualify_v13(candidate, baseline, literal_periods(candidate))
        self.assertTrue(passing.qualified)
        self.assertEqual(len(passing.gates), 7)
        for change in ({'cagr': .10}, {'turnover': .850001}, {'whipsaws': 9},
                       {'split': .094999}, {'drawdown': -.200001}):
            with self.subTest(change=change):
                self.assertFalse(module._qualify_v13(candidate, baseline,
                    literal_periods(candidate, **change)).qualified)
        for turnover in (None, 0., -1.):
            result = module._qualify_v13(candidate, literal_periods(turnover=turnover, whipsaws=0),
                                         literal_periods(candidate))
            self.assertIs(result.gates[5].status, module.GateStatus.NOT_EVALUABLE)
            self.assertIs(result.gates[6].status, module.GateStatus.NOT_EVALUABLE)

    def test_ranking_each_precedence_tie_band_and_shuffled_input(self):
        a, b, c = module.FIXED_V13_CANDIDATES
        def q(candidate, **kw):
            return module.V13CandidateQualification(candidate, literal_periods(candidate, **kw), (), True)
        cases = [
            ((q(a, whipsaws=5), q(b, whipsaws=4)), b),
            ((q(a, drawdown=-.2), q(b, drawdown=-.1)), b),
            ((q(a, turnover=.8), q(b, turnover=.7)), b),
            ((q(b), q(a)), a),
            ((q(a, cagr=.1000, whipsaws=1), q(b, cagr=.1005, whipsaws=8)), a),
            ((q(a, cagr=.099999, whipsaws=1), q(b, cagr=.1005, whipsaws=8)), b),
        ]
        for values, winner in cases:
            for ordering in (values, tuple(reversed(values))):
                self.assertEqual(module._rank_v13(ordering)[0].candidate, winner)
        self.assertEqual(tuple(x.candidate for x in module._rank_v13((q(c), q(b), q(a)))), (a,b,c))
        self.assertEqual(module._rank_v13(()), ())


class ReentryOrchestrationTests(unittest.TestCase):
    def test_selection_is_continuous_frozen_and_point_in_time(self):
        spy, bil = protocol_bars()
        engine = ProtocolEngine({date(2014, 12, 30): 0., date(2014, 12, 31): 0.})
        result = module.select_regime_reentry_v1_3_candidate(spy, bil, engine=engine)
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.common_intervals[-1][1], date(2020,12,31))
        validation = result.candidates[0].periods[1]
        self.assertEqual(validation.points[0].target_spy_exposure, .7)
        episode = validation.diagnostics.episodes[0]
        self.assertEqual((episode.opening_signal_date, episode.origin_exposure, episode.minimum_v1_cap),
                         (date(2014,12,30), 1., 0.))
        self.assertEqual(validation.diagnostics.incomplete_recovery_episodes, 0)
        self.assertEqual(result.candidates[0].periods[0].points[0].target_spy_exposure, 1.)
        self.assertEqual(len(engine.calls), len(set(engine.calls)))
        with self.assertRaises(FrozenInstanceError):
            result.winner = None

    def test_no_qualifier_and_future_content_exclusion(self):
        spy, bil = protocol_bars()
        expected = module.select_regime_reentry_v1_3_candidate(spy, bil, engine=ProtocolEngine())
        class Future:
            trading_date = date(2021,1,1)
            @property
            def adjusted_close(self):
                raise AssertionError('future content read')
        result = module.select_regime_reentry_v1_3_candidate(spy+[Future()], bil+[Future()], engine=ProtocolEngine())
        self.assertEqual(result, expected)
        self.assertIsNone(result.winner)
        self.assertIs(result.status, module.V13SelectionStatus.NO_QUALIFIED_V1_3_CANDIDATE)

    def test_bad_dates_and_active_data_fail_before_classifier(self):
        spy, bil = protocol_bars()
        from dataclasses import asdict
        cases = [(spy+[SimpleNamespace(trading_date='bad')], bil),
                 (spy, bil[:-2]+bil[-1:]), (spy, bil+[bil[-1]]),
                 (spy+[spy[-1]], bil), (spy, bil[:-1]+[SimpleNamespace(**(asdict(bil[-1]) | {'adjusted_close':0.}))]),
                 (spy[:-1]+[SimpleNamespace(**(asdict(spy[-1]) | {'adjusted_close':0.}))], bil)]
        for bad_spy, bad_bil in cases:
            engine = ProtocolEngine()
            with self.assertRaises(ValueError):
                module.select_regime_reentry_v1_3_candidate(bad_spy, bad_bil, engine=engine)
            self.assertEqual(engine.calls, [])

    def test_real_engine_integration(self):
        spy, bil = protocol_bars([date(2021,1,1), date(2021,1,2), date(2021,1,3)])
        result = module.evaluate_locked_regime_reentry_v1_3(spy, bil,
            frozen_candidate=module.FIXED_V13_CANDIDATES[0])
        self.assertEqual(len(result.candidate.points), 2)

    def test_initial_ramp_is_processed_before_first_measured_return(self):
        spy, bil = protocol_bars()
        # Exactly one warm-up signal precedes the first measured signal.
        result = module.select_regime_reentry_v1_3_candidate(spy[8:], bil, engine=ProtocolEngine())
        point = result.candidates[0].periods[0].points[0]
        self.assertEqual(point.target_spy_exposure, .7)
        self.assertAlmostEqual(point.transaction_cost, 35.)
        self.assertEqual(result.candidates[0].periods[0].diagnostics.total_recovery_episodes, 0)

    def test_selection_requires_exact_outer_boundaries_and_both_splits(self):
        for days in ([date(2007,10,2), date(2014,12,31), date(2015,1,1), date(2020,12,31)],
                     [date(2007,10,1), date(2014,12,31), date(2015,1,1), date(2020,12,30)],
                     [date(2007,10,1), date(2015,1,1), date(2020,12,31)]):
            with self.assertRaises(ValueError):
                module.select_regime_reentry_v1_3_candidate(*protocol_bars(days), engine=ProtocolEngine())

    def test_signal_applies_to_next_return_not_same_session(self):
        from dataclasses import replace
        days = [date(2020,12,31), date(2021,1,1), date(2021,1,2), date(2021,1,3)]
        spy, bil = protocol_bars(days)
        spy[-2] = replace(spy[-2], adjusted_close=110.)
        spy[-1] = replace(spy[-1], adjusted_close=220.)
        result = module.evaluate_locked_regime_reentry_v1_3(spy, bil,
            frozen_candidate=module.FIXED_V13_CANDIDATES[0],
            engine=ProtocolEngine({date(2021,1,2):0.}))
        first, second = result.candidate.points
        self.assertAlmostEqual(first.ending_value, 110000.)
        self.assertAlmostEqual(second.transaction_cost, 55.)
        self.assertAlmostEqual(second.ending_value, 109945.)


class LockedProtocolTests(unittest.TestCase):
    def test_decimal_floor_cannot_round_down_into_false_promotion(self):
        baseline = literal_periods(cagr=.10000000000000007, turnover=1., whipsaws=10)[-1]
        candidate = literal_periods(cagr=.10250000000000006)[-1]
        gates, status = module._promotion_v13(baseline, candidate)
        self.assertIs(gates[1].status, module.GateStatus.FAIL)
        self.assertIs(status, module.V13PromotionStatus.NO_V1_3_PROMOTION)

    def test_four_exact_locked_gates(self):
        baseline = literal_periods(cagr=.10, split=.10, turnover=1., whipsaws=10)[-1]
        for cagr, expected in ((.1025, True), (.102499, False), (math.nextafter(.1025, -math.inf), False)):
            gates, status = module._promotion_v13(baseline, literal_periods(cagr=cagr)[-1])
            self.assertEqual(len(gates), 4)
            self.assertEqual(status is module.V13PromotionStatus.PROMOTE_V1_3_RESEARCH, expected)
        for changes in ({'drawdown':-.200001}, {'turnover':.850001}, {'whipsaws':9}):
            gates, status = module._promotion_v13(baseline, literal_periods(cagr=.1025, **changes)[-1])
            self.assertIs(status, module.V13PromotionStatus.NO_V1_3_PROMOTION)
        for turnover in (None, 0., -1.):
            gates, status = module._promotion_v13(literal_periods(turnover=turnover, whipsaws=0)[-1],
                                                  literal_periods(cagr=.1025)[-1])
            self.assertIs(gates[2].status, module.GateStatus.NOT_EVALUABLE)
            self.assertIs(gates[3].status, module.GateStatus.NOT_EVALUABLE)

    def test_locked_start_missing_from_bil_cannot_silently_shift(self):
        spy, bil = protocol_bars([date(2020,12,31), date(2021,1,1), date(2021,1,2), date(2021,1,3)])
        with self.assertRaises(ValueError):
            module.evaluate_locked_regime_reentry_v1_3(spy, bil[2:],
                frozen_candidate=module.FIXED_V13_CANDIDATES[0], engine=ProtocolEngine())

    def test_invalid_candidates_rejected_before_any_input_access(self):
        class Unreadable:
            def __iter__(self):
                raise AssertionError('input accessed')
        class Subclass(module.V13ReentryCandidate):
            pass
        class Spoof:
            def __eq__(self, other):
                return True
        mutated = module.V13ReentryCandidate(module.V13ReentryStructure.DEEP_RECOVERY)
        object.__setattr__(mutated, 'structure', Spoof())
        missing = object.__new__(module.V13ReentryCandidate)
        for candidate in (None, [], 'deep_recovery', Spoof(), mutated, missing,
                          Subclass(module.V13ReentryStructure.DEEP_RECOVERY)):
            for function in (module.evaluate_locked_regime_reentry_v1_3,
                             module.build_regime_reentry_v1_3_post_selection_diagnostics):
                with self.assertRaises(ValueError):
                    function(Unreadable(), Unreadable(), frozen_candidate=candidate)

    def test_locked_episode_carry_and_opening_cost(self):
        days = [date(2020,12,29), date(2020,12,30), date(2020,12,31), date(2021,1,1), date(2021,1,2)]
        spy, bil = protocol_bars(days)
        result = module.evaluate_locked_regime_reentry_v1_3(spy, bil,
            frozen_candidate=module.FIXED_V13_CANDIDATES[0],
            engine=ProtocolEngine({date(2020,12,30):0., date(2020,12,31):0.}))
        point = result.candidate.points[0]
        self.assertEqual((point.signal_date, point.return_end_date), (date(2021,1,1), date(2021,1,2)))
        self.assertEqual(point.target_spy_exposure, .7)
        self.assertAlmostEqual(point.transaction_cost, 35.)
        self.assertAlmostEqual(point.ending_value, 99965.)
        self.assertEqual(result.candidate.diagnostics.episodes[0].origin_exposure, 1.)
        self.assertEqual(result.candidate.diagnostics.incomplete_recovery_episodes, 1)
        carried = module.evaluate_locked_regime_reentry_v1_3(spy, bil,
            frozen_candidate=module.FIXED_V13_CANDIDATES[0], engine=ProtocolEngine())
        self.assertEqual(carried.candidate.points[0].transaction_cost, 0.)


class PostSelectionTests(unittest.TestCase):
    def test_costs_windows_rebasing_and_terminal_signal_exclusion(self):
        days = [date(2007,10,1), date(2009,6,30), date(2020,1,1), date(2020,12,31),
                date(2022,1,1), date(2022,12,31), date(2023,1,1), date(2025,12,31)]
        spy, bil = protocol_bars(days)
        result = module.build_regime_reentry_v1_3_post_selection_diagnostics(spy, bil,
            frozen_candidate=module.FIXED_V13_CANDIDATES[0],
            engine=ProtocolEngine({date(2009,6,30):0., date(2020,12,31):0.}))
        self.assertEqual(tuple(x.transaction_cost_bps for x in result.full_period_comparisons), (0.,2.,5.,10.))
        self.assertEqual(len(result.window_comparisons), 16)
        for window in result.window_comparisons:
            self.assertIs(window.availability, module.EvaluationAvailability.AVAILABLE)
            self.assertEqual(window.candidate.metrics.initial_capital, 100.)
        crisis = result.window_comparisons[0]
        self.assertEqual(crisis.candidate.diagnostics.total_recovery_episodes, 0)
        self.assertAlmostEqual(result.full_period_comparisons[2].candidate.points[0].transaction_cost, 50.)
        # 2020 begins with .7 after prior zero, so its rebased opening cost is .035.
        covid = result.window_comparisons[9]
        self.assertAlmostEqual(covid.candidate.metrics.total_transaction_cost, .035)
        self.assertAlmostEqual(covid.candidate.metrics.final_value, 99.965)
        sparse = module.build_regime_reentry_v1_3_post_selection_diagnostics(*protocol_bars(),
            frozen_candidate=module.FIXED_V13_CANDIDATES[0], engine=ProtocolEngine())
        self.assertIs(sparse.window_comparisons[2].availability, module.EvaluationAvailability.UNAVAILABLE)
        self.assertIsNone(sparse.window_comparisons[2].candidate)


class ReentryContractTests(unittest.TestCase):
    def test_fixed_candidates_are_exactly_three_canonical_immutable_structures(self):
        self.assertEqual(
            tuple(candidate.structure for candidate in module.FIXED_V13_CANDIDATES),
            (
                module.V13ReentryStructure.DEEP_RECOVERY,
                module.V13ReentryStructure.DEFENSIVE_RECOVERY,
                module.V13ReentryStructure.BROAD_BULL_CATCH_UP,
            ),
        )
        self.assertEqual(len(module.FIXED_V13_CANDIDATES), 3)
        for candidate in module.FIXED_V13_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertEqual(type(candidate), module.V13ReentryCandidate)
                with self.assertRaises(FrozenInstanceError):
                    candidate.structure = module.V13ReentryStructure.DEEP_RECOVERY

    def test_candidate_boundary_rejects_spoofs_wrong_enums_subclasses_and_mutations(self):
        class OtherStructure(Enum):
            DEEP_RECOVERY = "deep_recovery"

        class CandidateSubclass(module.V13ReentryCandidate):
            pass

        class Spoof:
            structure = module.V13ReentryStructure.DEEP_RECOVERY

        invalid = (
            "deep_recovery",
            OtherStructure.DEEP_RECOVERY,
            CandidateSubclass(module.V13ReentryStructure.DEEP_RECOVERY),
            Spoof(),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    module._validate_candidate(candidate)

        candidate = module.V13ReentryCandidate(
            module.V13ReentryStructure.DEEP_RECOVERY
        )
        object.__setattr__(candidate, "structure", "deep_recovery")
        with self.assertRaises(ValueError):
            module._validate_candidate(candidate)


class ReentryTransitionTests(unittest.TestCase):
    def _signal(self, day, score, regime, cap):
        return _V1Signal(date(2020, 1, day), score, regime, cap)

    def _run(self, signals, structure=module.V13ReentryStructure.DEEP_RECOVERY):
        return module._run_reentry_state_machine(
            tuple(signals), module.V13ReentryCandidate(structure)
        )

    def test_initial_warmup_rises_normally_without_episode_privileges(self):
        points = self._run(
            (
                self._signal(1, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 45, MarketRegime.BULL, 1.0),
                self._signal(3, 45, MarketRegime.BULL, 1.0),
            )
        )
        self.assertEqual(tuple(point.overlay_exposure for point in points), (0.3, 0.7, 1.0))
        self.assertEqual(
            tuple(point.transition for point in points),
            (module.V13ReentryTransition.NORMAL_RE_ENTRY,) * 3,
        )
        self.assertTrue(all(not point.episode.active for point in points))

    def test_deep_recovery_fast_path_and_closing_preserves_minimum_on_point(self):
        points = self._run(
            (
                self._signal(1, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 45, MarketRegime.BULL, 1.0),
                self._signal(3, 45, MarketRegime.BULL, 1.0),
                self._signal(4, -30, MarketRegime.BEAR, 0.0),
                self._signal(5, 45, MarketRegime.BULL, 1.0),
                self._signal(6, 45, MarketRegime.BULL, 1.0),
            )
        )
        self.assertEqual(tuple(point.overlay_exposure for point in points), (0.3, 0.7, 1.0, 0.0, 0.7, 1.0))
        self.assertEqual(points[3].transition, module.V13ReentryTransition.DE_RISK)
        self.assertEqual(points[4].transition, module.V13ReentryTransition.FAST_RE_ENTRY)
        self.assertEqual(points[4].episode.minimum_v1_cap, 0.0)
        self.assertFalse(points[5].episode.active)
        self.assertEqual(points[5].prior_episode.minimum_v1_cap, 0.0)

    def test_de_risk_preserves_origin_and_never_recovers_same_day(self):
        points = self._run(
            (
                self._signal(1, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 45, MarketRegime.BULL, 1.0),
                self._signal(3, 45, MarketRegime.BULL, 1.0),
                self._signal(4, 0, MarketRegime.RISK_OFF, 0.3),
                self._signal(5, -30, MarketRegime.BEAR, 0.0),
            )
        )
        self.assertEqual(points[3].overlay_exposure, 0.3)
        self.assertEqual(points[3].episode.origin_exposure, 1.0)
        self.assertEqual(points[4].overlay_exposure, 0.0)
        self.assertEqual(points[4].episode.origin_exposure, 1.0)
        self.assertEqual(points[4].episode.minimum_v1_cap, 0.0)

    def test_equal_v1_cap_holds_current_overlay(self):
        points = self._run(
            (
                self._signal(1, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 0, MarketRegime.RISK_OFF, 0.3),
            )
        )
        self.assertEqual(points[-1].overlay_exposure, 0.3)
        self.assertEqual(points[-1].transition, module.V13ReentryTransition.HOLD)

    def test_fast_trigger_requires_every_conjunct_and_structure_depth(self):
        base = (
            self._signal(1, 45, MarketRegime.BULL, 1.0),
            self._signal(2, 45, MarketRegime.BULL, 1.0),
            self._signal(3, 45, MarketRegime.BULL, 1.0),
            self._signal(4, 0, MarketRegime.RISK_OFF, 0.3),
        )
        deep = self._run(base + (self._signal(5, 45, MarketRegime.BULL, 1.0),))
        defensive = self._run(
            base + (self._signal(5, 45, MarketRegime.BULL, 1.0),),
            module.V13ReentryStructure.DEFENSIVE_RECOVERY,
        )
        low_score = self._run(base + (self._signal(5, 44, MarketRegime.BULL, 1.0),))
        wrong_regime = self._run(base + (self._signal(5, 45, MarketRegime.CAUTIOUS_BULL, 1.0),))
        self.assertEqual(deep[-1].overlay_exposure, 0.7)
        self.assertEqual(defensive[-1].overlay_exposure, 1.0)
        self.assertEqual(low_score[-1].overlay_exposure, 0.7)
        self.assertEqual(wrong_regime[-1].overlay_exposure, 0.7)

    def test_fast_trigger_rejects_subfull_cap_even_for_eligible_deep_episode(self):
        points = self._run(
            (
                self._signal(1, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 45, MarketRegime.BULL, 1.0),
                self._signal(3, 45, MarketRegime.BULL, 1.0),
                self._signal(4, -30, MarketRegime.BEAR, 0.0),
                self._signal(5, 45, MarketRegime.BULL, 0.7),
            )
        )
        self.assertEqual(points[-1].overlay_exposure, 0.3)
        self.assertEqual(points[-1].transition, module.V13ReentryTransition.NORMAL_RE_ENTRY)

    def test_broad_structure_allows_shallow_episode_fast_completion_but_others_do_not(self):
        signals = (
            self._signal(1, 45, MarketRegime.BULL, 1.0),
            self._signal(2, 45, MarketRegime.BULL, 1.0),
            self._signal(3, 45, MarketRegime.BULL, 1.0),
            self._signal(4, 15, MarketRegime.CAUTIOUS_BULL, 0.7),
            self._signal(5, 45, MarketRegime.BULL, 1.0),
        )
        deep = self._run(signals, module.V13ReentryStructure.DEEP_RECOVERY)
        defensive = self._run(signals, module.V13ReentryStructure.DEFENSIVE_RECOVERY)
        broad = self._run(signals, module.V13ReentryStructure.BROAD_BULL_CATCH_UP)
        self.assertEqual(deep[-1].transition, module.V13ReentryTransition.NORMAL_RE_ENTRY)
        self.assertEqual(defensive[-1].transition, module.V13ReentryTransition.NORMAL_RE_ENTRY)
        self.assertEqual(broad[-1].transition, module.V13ReentryTransition.FAST_RE_ENTRY)

    def test_rejects_invalid_signal_inputs_and_non_increasing_dates(self):
        invalid_signals = (
            (self._signal(1, True, MarketRegime.BULL, 1.0),),
            (self._signal(1, math.inf, MarketRegime.BULL, 1.0),),
            (self._signal(1, 45, "bull", 1.0),),
            (self._signal(1, 45, MarketRegime.BULL, True),),
            (self._signal(1, 45, MarketRegime.BULL, 0.5),),
            (
                self._signal(2, 45, MarketRegime.BULL, 1.0),
                self._signal(2, 45, MarketRegime.BULL, 1.0),
            ),
        )
        for signals in invalid_signals:
            with self.subTest(signals=signals):
                with self.assertRaises(ValueError):
                    self._run(signals)


class RecoveryDiagnosticsTests(unittest.TestCase):
    def _point(self, day, prior, overlay, cap, transition, prior_episode, episode):
        return module.V13ReentrySignalPoint(
            date(2020, 1, day), 45, MarketRegime.BULL, cap, prior, overlay,
            prior_episode, episode, transition,
        )

    def test_uses_v12_nonoverlapping_whipsaw_definition_and_no_episode_rate_is_none(self):
        inactive = module._RecoveryEpisodeState()
        schedule = (1.0, 0.3, 0.7, 1.0, 0.3, 1.0)
        points = tuple(
            self._point(
                index, schedule[index - 2] if index > 1 else schedule[0], value,
                1.0, module.V13ReentryTransition.HOLD, inactive, inactive,
            )
            for index, value in enumerate(schedule, start=1)
        )
        diagnostics = module._recovery_diagnostics(points, start=date(2020, 1, 1), end=date(2020, 1, 6))
        comparable = _stabilization_diagnostics(points, start=date(2020, 1, 1), end=date(2020, 1, 6), include_reentry_detail=False)
        self.assertEqual((diagnostics.schedule_exposure_changes, diagnostics.whipsaw_pairs), (5, 2))
        self.assertEqual((diagnostics.schedule_exposure_changes, diagnostics.whipsaw_pairs), (comparable.schedule_exposure_changes, comparable.whipsaw_pairs))
        self.assertIsNone(diagnostics.fast_path_activation_rate)

    def test_carry_in_and_end_cutoff_only_use_context_through_end(self):
        points = module._run_reentry_state_machine(
            (
                _V1Signal(date(2020, 1, 1), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 2), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 3), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 4), -30, MarketRegime.BEAR, 0.0),
                _V1Signal(date(2020, 1, 5), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 6), 45, MarketRegime.BULL, 1.0),
            ), module.FIXED_V13_CANDIDATES[0]
        )
        early = module._recovery_diagnostics(points, start=date(2020, 1, 5), end=date(2020, 1, 5))
        late = module._recovery_diagnostics(points, start=date(2020, 1, 5), end=date(2020, 1, 6))
        self.assertEqual((early.total_recovery_episodes, early.completed_recovery_episodes, early.incomplete_recovery_episodes), (1, 0, 1))
        self.assertEqual((late.total_recovery_episodes, late.completed_recovery_episodes, late.incomplete_recovery_episodes), (1, 1, 0))
        self.assertEqual(late.recovery_durations, (2,))

    def test_lags_are_inclusive_and_reset_when_permission_is_lost(self):
        points = module._run_reentry_state_machine(
            (
                _V1Signal(date(2020, 1, 1), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 2), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 3), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 4), -30, MarketRegime.BEAR, 0.0),
                _V1Signal(date(2020, 1, 5), 44, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 6), -30, MarketRegime.BEAR, 0.0),
                _V1Signal(date(2020, 1, 7), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 8), 45, MarketRegime.BULL, 1.0),
            ), module.FIXED_V13_CANDIDATES[0]
        )
        diagnostics = module._recovery_diagnostics(points, start=date(2020, 1, 4), end=date(2020, 1, 8))
        self.assertEqual(diagnostics.reentry_lags, (1, 1, 1, 2))
        self.assertEqual(diagnostics.fast_two_level_reentry_count, 1)
        self.assertEqual(diagnostics.ordinary_one_level_reentry_count, 1)

    def test_fast_one_level_completion_is_not_counted_as_two_level_or_ordinary(self):
        points = module._run_reentry_state_machine(
            (
                _V1Signal(date(2020, 1, 1), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 2), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 3), 45, MarketRegime.BULL, 1.0),
                _V1Signal(date(2020, 1, 4), 15, MarketRegime.CAUTIOUS_BULL, 0.7),
                _V1Signal(date(2020, 1, 5), 45, MarketRegime.BULL, 1.0),
            ), module.FIXED_V13_CANDIDATES[2]
        )
        diagnostics = module._recovery_diagnostics(
            points, start=date(2020, 1, 4), end=date(2020, 1, 5)
        )
        self.assertEqual(diagnostics.fast_path_activation_count, 1)
        self.assertEqual(diagnostics.fast_two_level_reentry_count, 0)
        self.assertEqual(diagnostics.ordinary_one_level_reentry_count, 0)


if __name__ == "__main__":
    unittest.main()
