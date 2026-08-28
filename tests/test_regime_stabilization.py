from dataclasses import FrozenInstanceError, fields
from datetime import date, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from private_quant.backtest import regime_stabilization
from private_quant.backtest.regime_evaluation import InvalidEvaluationDataError
from private_quant.backtest.regime_stabilization import (
    ALLOWED_EXPOSURES,
    CONFIRMATION_SESSIONS,
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FIXED_STABILIZATION_CANDIDATES,
    GateResult,
    GateStatus,
    LOCKED_CAGR_IMPROVEMENT,
    LOCKED_START,
    MARGINS,
    POST_SELECTION_COST_BPS,
    PRIMARY_COST_BPS,
    PromotionStatus,
    ResearchPeriod,
    SELECTION_END,
    SPLIT_CAGR_ALLOWANCE,
    SelectionStatus,
    StabilizationCandidate,
    StabilizationDiagnostics,
    StabilizationSignalPoint,
    StabilizationTransition,
    BoundaryConfirmationState,
    TURNOVER_REDUCTION,
    VALIDATION_START,
    WHIPSAW_REDUCTION,
    WINNER_CAGR_TIE_BAND,
)
from private_quant.risk import InvalidRegimeDataError, MarketRegime
from private_quant.data import PriceBar


def make_spy_bars(count: int) -> list[PriceBar]:
    return [
        PriceBar(
            "SPY",
            date(2020, 1, 1) + timedelta(days=index),
            100.0 + index,
            100.0 + index,
            100.0 + index,
            100.0 + index,
            100.0 + index,
            1_000_000,
        )
        for index in range(count)
    ]


class RecordingEngine:
    def __init__(self, maximum_long_exposure=1.0) -> None:
        self.calls = []
        self.maximum_long_exposure = maximum_long_exposure

    def evaluate(self, spy_bars, *, as_of, qqq_bars):
        self.calls.append((tuple(spy_bars), as_of, qqq_bars))
        return SimpleNamespace(
            score=60,
            regime=MarketRegime.BULL,
            maximum_long_exposure=self.maximum_long_exposure,
        )


class StabilizationContractTests(unittest.TestCase):
    def test_fixed_grid(self):
        self.assertEqual(
            FIXED_STABILIZATION_CANDIDATES,
            tuple(
                StabilizationCandidate(margin, confirmations)
                for margin in (0, 5, 10)
                for confirmations in (1, 2, 3, 5)
            ),
        )
        self.assertEqual(len(FIXED_STABILIZATION_CANDIDATES), 12)

    def test_candidate_validation(self):
        for args in ((-1, 1), (7, 1), (5, 4), (5, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                StabilizationCandidate(*args)

    def test_period_constants(self):
        self.assertEqual(DEVELOPMENT_START, date(2007, 10, 1))
        self.assertEqual(DEVELOPMENT_END, date(2014, 12, 31))
        self.assertEqual(VALIDATION_START, date(2015, 1, 1))
        self.assertEqual(SELECTION_END, date(2020, 12, 31))
        self.assertEqual(LOCKED_START, date(2021, 1, 1))

    def test_protocol_constants(self):
        self.assertEqual(ALLOWED_EXPOSURES, (0.0, 0.3, 0.7, 1.0))
        self.assertEqual(MARGINS, (0, 5, 10))
        self.assertEqual(CONFIRMATION_SESSIONS, (1, 2, 3, 5))
        self.assertEqual(PRIMARY_COST_BPS, 5.0)
        self.assertEqual(SPLIT_CAGR_ALLOWANCE, 0.005)
        self.assertEqual(WINNER_CAGR_TIE_BAND, 0.0005)
        self.assertEqual(LOCKED_CAGR_IMPROVEMENT, 0.0025)
        self.assertEqual(TURNOVER_REDUCTION, 0.15)
        self.assertEqual(WHIPSAW_REDUCTION, 0.20)
        self.assertEqual(POST_SELECTION_COST_BPS, (0.0, 2.0, 5.0, 10.0))

    def test_boundary_confirmation_defaults_and_validation(self):
        self.assertEqual(BoundaryConfirmationState(), BoundaryConfirmationState(0, 0, 0))
        self.assertEqual(BoundaryConfirmationState(1, 2, 3).to_100, 3)

        for value in (True, False, 1.0, "1", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BoundaryConfirmationState(to_30=value)

    def test_enum_protocol_values(self):
        self.assertEqual(
            tuple((member.name, member.value) for member in StabilizationTransition),
            (("HOLD", "hold"), ("DE_RISK", "de_risk"), ("RE_ENTRY", "re_entry")),
        )
        self.assertEqual(
            tuple((member.name, member.value) for member in ResearchPeriod),
            (
                ("DEVELOPMENT", "development"),
                ("VALIDATION", "validation"),
                ("COMBINED_SELECTION", "combined_selection"),
                ("LOCKED", "locked"),
            ),
        )
        self.assertEqual(
            tuple((member.name, member.value) for member in GateStatus),
            (("PASS", "pass"), ("FAIL", "fail"), ("NOT_EVALUABLE", "not_evaluable")),
        )
        self.assertEqual(
            tuple((member.name, member.value) for member in SelectionStatus),
            (("SELECTED", "selected"), ("NO_QUALIFIED_CANDIDATE", "no_qualified_candidate")),
        )
        self.assertEqual(
            tuple((member.name, member.value) for member in PromotionStatus),
            (
                ("PROMOTE_V1_2_RESEARCH", "promote_v1_2_research"),
                ("NO_V1_2_PROMOTION", "no_v1_2_promotion"),
            ),
        )

    def test_contract_field_order(self):
        self.assertEqual(
            tuple(field.name for field in fields(StabilizationSignalPoint)),
            (
                "signal_date",
                "v1_score",
                "v1_regime",
                "v1_maximum_long_exposure",
                "prior_overlay_exposure",
                "overlay_exposure",
                "confirmations",
                "transition",
            ),
        )
        self.assertEqual(
            tuple(field.name for field in fields(StabilizationDiagnostics)),
            (
                "schedule_exposure_changes",
                "whipsaw_pairs",
                "whipsaw_rate",
                "delayed_below_cap_sessions",
                "reentry_lags",
                "mean_reentry_lag",
                "median_reentry_lag",
                "recovery_durations",
                "mean_recovery_duration",
                "median_recovery_duration",
                "incomplete_recovery_episodes",
            ),
        )
        self.assertEqual(
            tuple(field.name for field in fields(GateResult)),
            ("name", "status", "actual", "required"),
        )

    def test_contracts_are_frozen_and_slotted(self):
        contracts = (
            StabilizationCandidate(5, 2),
            BoundaryConfirmationState(),
            StabilizationSignalPoint(
                signal_date=date(2020, 1, 2),
                v1_score=60,
                v1_regime=MarketRegime.BULL,
                v1_maximum_long_exposure=1.0,
                prior_overlay_exposure=0.7,
                overlay_exposure=1.0,
                confirmations=BoundaryConfirmationState(2, 2, 2),
                transition=StabilizationTransition.RE_ENTRY,
            ),
            StabilizationDiagnostics(
                schedule_exposure_changes=2,
                whipsaw_pairs=1,
                whipsaw_rate=0.5,
                delayed_below_cap_sessions=3,
                reentry_lags=(2,),
                mean_reentry_lag=2.0,
                median_reentry_lag=2.0,
                recovery_durations=(4,),
                mean_recovery_duration=4.0,
                median_recovery_duration=4.0,
                incomplete_recovery_episodes=1,
            ),
            GateResult("combined_cagr", GateStatus.PASS, 0.08, 0.07),
        )

        for contract in contracts:
            with self.subTest(contract=type(contract).__name__):
                self.assertFalse(hasattr(contract, "__dict__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(contract, fields(contract)[0].name, "mutation")


class StabilizationSignalStreamTests(unittest.TestCase):
    def test_first_v1_signal_uses_the_252nd_spy_observation(self):
        spy = make_spy_bars(253)
        engine = RecordingEngine()

        signals = regime_stabilization._build_v1_signals(
            spy,
            final_signal_date=spy[-1].trading_date,
            engine=engine,
        )

        self.assertEqual(
            tuple(signal.signal_date for signal in signals),
            (spy[251].trading_date, spy[252].trading_date),
        )
        self.assertEqual(len(engine.calls[0][0]), 252)

    def test_each_engine_call_receives_only_spy_through_as_of_and_no_qqq(self):
        spy = make_spy_bars(254)
        engine = RecordingEngine()

        regime_stabilization._build_v1_signals(
            spy,
            final_signal_date=spy[-1].trading_date,
            engine=engine,
        )

        self.assertEqual(
            tuple(
                (
                    tuple(bar.trading_date for bar in visible),
                    as_of,
                    qqq_bars,
                )
                for visible, as_of, qqq_bars in engine.calls
            ),
            tuple(
                (
                    tuple(bar.trading_date for bar in spy[: index + 1]),
                    spy[index].trading_date,
                    None,
                )
                for index in range(251, 254)
            ),
        )

    def test_valid_dated_malformed_future_price_is_cut_off_before_engine_calls(self):
        spy = make_spy_bars(254)
        final_signal_date = spy[252].trading_date
        malformed_future = spy[253]
        object.__setattr__(malformed_future, "adjusted_close", "malformed")
        engine = RecordingEngine()

        signals = regime_stabilization._build_v1_signals(
            spy,
            final_signal_date=final_signal_date,
            engine=engine,
        )

        self.assertEqual(
            tuple(signal.signal_date for signal in signals),
            (spy[251].trading_date, spy[252].trading_date),
        )
        self.assertTrue(
            all(malformed_future not in visible for visible, _, _ in engine.calls)
        )

    def test_unparseable_future_date_fails_before_any_engine_call(self):
        spy = make_spy_bars(254)
        final_signal_date = spy[252].trading_date
        future_bar = spy[253]
        self.assertGreater(future_bar.trading_date, final_signal_date)
        object.__setattr__(future_bar, "trading_date", "unparseable")
        engine = RecordingEngine()

        with self.assertRaises(InvalidRegimeDataError):
            regime_stabilization._build_v1_signals(
                spy,
                final_signal_date=final_signal_date,
                engine=engine,
            )

        self.assertEqual(engine.calls, [])

    def test_invalid_v1_exposure_mapping_is_rejected_with_fixed_error(self):
        spy = make_spy_bars(252)

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "V1 exposure mapping is invalid",
        ):
            regime_stabilization._build_v1_signals(
                spy,
                final_signal_date=spy[-1].trading_date,
                engine=RecordingEngine(maximum_long_exposure=0.5),
            )

    def test_missing_measured_signal_date_is_a_hard_deterministic_error(self):
        signal_dates = (date(2020, 1, 2), date(2020, 1, 3))
        state_points = (
            StabilizationSignalPoint(
                signal_date=signal_dates[0],
                v1_score=60,
                v1_regime=MarketRegime.BULL,
                v1_maximum_long_exposure=1.0,
                prior_overlay_exposure=0.0,
                overlay_exposure=0.3,
                confirmations=BoundaryConfirmationState(1, 1, 1),
                transition=StabilizationTransition.RE_ENTRY,
            ),
        )

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "stabilization state is missing a measured signal date",
        ):
            regime_stabilization._measured_state_points(state_points, signal_dates)


class StabilizationStateMachineTests(unittest.TestCase):
    def _signal(
        self, signal_date: date, score: int, regime: MarketRegime, cap: float
    ):
        self.assertTrue(
            hasattr(regime_stabilization, "_V1Signal"),
            "state-machine signal contract is missing",
        )
        return regime_stabilization._V1Signal(signal_date, score, regime, cap)

    def _run(self, signals, candidate):
        self.assertTrue(
            hasattr(regime_stabilization, "_run_stabilization_state_machine"),
            "state-machine runner is missing",
        )
        return regime_stabilization._run_stabilization_state_machine(signals, candidate)

    def test_one_session_confirmation_reenters_one_level_per_session(self):
        signals = (
            self._signal(date(2020, 1, 2), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 3), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 6), 60, MarketRegime.BULL, 1.0),
        )

        points = self._run(signals, StabilizationCandidate(0, 1))

        self.assertEqual(
            tuple(point.overlay_exposure for point in points), (0.3, 0.7, 1.0)
        )
        self.assertEqual(
            tuple(point.transition for point in points),
            (
                StabilizationTransition.RE_ENTRY,
                StabilizationTransition.RE_ENTRY,
                StabilizationTransition.RE_ENTRY,
            ),
        )

    def test_three_session_confirmation_accumulates_higher_boundaries(self):
        signals = (
            self._signal(date(2020, 1, 2), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 3), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 6), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 7), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 8), 60, MarketRegime.BULL, 1.0),
        )

        points = self._run(signals, StabilizationCandidate(0, 3))

        self.assertEqual(
            tuple(point.overlay_exposure for point in points),
            (0.0, 0.0, 0.3, 0.7, 1.0),
        )

    def test_lower_v1_cap_derisks_immediately_without_same_session_reentry(self):
        signals = (
            self._signal(date(2020, 1, 2), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 3), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 6), -50, MarketRegime.BEAR, 0.0),
        )

        points = self._run(signals, StabilizationCandidate(0, 1))

        self.assertEqual(points[-2].overlay_exposure, 0.7)
        self.assertEqual(points[-1].overlay_exposure, 0.0)
        self.assertEqual(points[-1].transition, StabilizationTransition.DE_RISK)
        self.assertEqual(points[-1].confirmations, BoundaryConfirmationState())

    def test_confirmation_counters_reset_and_cap_independently(self):
        signals = (
            self._signal(date(2020, 1, 2), -15, MarketRegime.RISK_OFF, 0.3),
            self._signal(date(2020, 1, 3), -16, MarketRegime.RISK_OFF, 0.3),
            self._signal(date(2020, 1, 6), -15, MarketRegime.RISK_OFF, 0.3),
            self._signal(date(2020, 1, 7), -15, MarketRegime.RISK_OFF, 0.3),
        )

        points = self._run(signals, StabilizationCandidate(5, 2))

        self.assertEqual(
            tuple(point.confirmations.to_30 for point in points), (1, 0, 1, 2)
        )
        self.assertEqual(points[-1].overlay_exposure, 0.3)

    def test_overlay_always_uses_an_allowed_level_at_or_below_v1_cap(self):
        signals = (
            self._signal(date(2020, 1, 2), 60, MarketRegime.BULL, 1.0),
            self._signal(date(2020, 1, 3), 30, MarketRegime.CAUTIOUS_BULL, 0.7),
            self._signal(date(2020, 1, 6), 0, MarketRegime.RISK_OFF, 0.3),
            self._signal(date(2020, 1, 7), -50, MarketRegime.BEAR, 0.0),
        )

        points = self._run(signals, StabilizationCandidate(0, 1))

        for point in points:
            with self.subTest(signal_date=point.signal_date):
                self.assertIn(point.overlay_exposure, ALLOWED_EXPOSURES)
                self.assertLessEqual(
                    point.overlay_exposure, point.v1_maximum_long_exposure
                )


if __name__ == "__main__":
    unittest.main()
