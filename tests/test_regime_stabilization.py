import ast
from dataclasses import FrozenInstanceError, fields
from datetime import date, timedelta
import inspect
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import private_quant.backtest as backtest
from private_quant.backtest import regime_stabilization
from private_quant.backtest.regime_evaluation import (
    EvaluationAvailability,
    EvaluationStrategy,
    InvalidEvaluationDataError,
    PerformanceMetrics,
    _PriceInterval,
    _simulate_intervals,
)
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


def make_selection_bars():
    warmup_dates = [
        DEVELOPMENT_START - timedelta(days=260 - index) for index in range(260)
    ]
    measured_dates = [
        DEVELOPMENT_START,
        date(2010, 1, 4),
        DEVELOPMENT_END,
        VALIDATION_START,
        date(2018, 1, 2),
        SELECTION_END,
    ]

    def bars(symbol, dates):
        return [
            PriceBar(symbol, day, 100.0, 100.0, 100.0, 100.0, 100.0, 1_000_000)
            for day in dates
        ]

    return bars("SPY", warmup_dates + measured_dates), bars("BIL", measured_dates)


def make_locked_bars():
    warmup_dates = [
        date(2020, 1, 1) + timedelta(days=index) for index in range(252)
    ]
    prelocked_dates = [
        date(2020, 12, 28),
        date(2020, 12, 29),
        date(2020, 12, 30),
        date(2020, 12, 31),
    ]
    locked_dates = [date(2021, 1, day) for day in (4, 5, 6)]

    def bars(symbol, dates):
        return [
            PriceBar(symbol, day, 100.0, 100.0, 100.0, 100.0, 100.0, 1_000_000)
            for day in dates
        ]

    return (
        bars("SPY", warmup_dates + prelocked_dates + locked_dates),
        bars("BIL", locked_dates),
        tuple(locked_dates),
    )


def make_initial_locked_bars():
    warmup_dates = [
        date(2020, 12, 31) - timedelta(days=250 - index)
        for index in range(251)
    ]
    locked_dates = [date(2021, 1, day) for day in (4, 5)]

    def bars(symbol, dates):
        return [
            PriceBar(symbol, day, 100.0, 100.0, 100.0, 100.0, 100.0, 1_000_000)
            for day in dates
        ]

    return bars("SPY", warmup_dates + locked_dates), bars("BIL", locked_dates)


def make_post_selection_bars():
    warmup_dates = [
        DEVELOPMENT_START - timedelta(days=260 - index) for index in range(260)
    ]
    measured_dates = [
        DEVELOPMENT_START,
        date(2009, 6, 30),
        date(2020, 1, 1),
        date(2020, 12, 31),
        date(2022, 1, 1),
        date(2022, 12, 31),
        date(2023, 1, 1),
        date(2025, 12, 31),
        date(2026, 1, 2),
    ]

    def bars(symbol, dates):
        return [
            PriceBar(symbol, day, 100.0, 100.0, 100.0, 100.0, 100.0, 1_000_000)
            for day in dates
        ]

    return (
        bars("SPY", warmup_dates + measured_dates),
        bars("BIL", measured_dates),
        tuple(measured_dates),
    )


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


class SelectionEngine:
    def __init__(self):
        self.calls = []

    def evaluate(self, spy_bars, *, as_of, qqq_bars):
        self.calls.append((as_of, qqq_bars))
        return SimpleNamespace(
            score=60,
            regime=MarketRegime.BULL,
            maximum_long_exposure=1.0,
        )


class LockedContinuityEngine:
    def __init__(self):
        self.calls = []

    def evaluate(self, spy_bars, *, as_of, qqq_bars):
        self.calls.append((as_of, qqq_bars))
        is_reentry = as_of >= date(2020, 12, 28)
        return SimpleNamespace(
            score=60 if is_reentry else -50,
            regime=MarketRegime.BULL if is_reentry else MarketRegime.BEAR,
            maximum_long_exposure=1.0 if is_reentry else 0.0,
        )


class WindowClosingTransitionEngine:
    def evaluate(self, spy_bars, *, as_of, qqq_bars):
        risk_on = as_of < date(2009, 6, 30)
        return SimpleNamespace(
            score=60 if risk_on else -50,
            regime=MarketRegime.BULL if risk_on else MarketRegime.BEAR,
            maximum_long_exposure=1.0 if risk_on else 0.0,
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

    def test_candidate_rejects_boolean_and_float_numeric_aliases(self):
        for args in ((False, 1), (5, True), (5.0, 2), (5, 2.0)):
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


def literal_metrics(*, cagr, max_drawdown=-0.10, annualized_turnover=1.0):
    return PerformanceMetrics(
        initial_capital=100.0,
        final_value=110.0,
        total_return=0.10,
        cagr=cagr,
        max_drawdown=max_drawdown,
        annualized_volatility=0.10,
        sharpe=1.0,
        sortino=1.0,
        calmar=1.0,
        total_transaction_cost=0.0,
        annualized_turnover=annualized_turnover,
        exposure_changes=1,
        average_spy_exposure=0.7,
        exposure_buckets=(),
    )


def literal_diagnostics(*, whipsaw_pairs):
    return StabilizationDiagnostics(
        schedule_exposure_changes=10,
        whipsaw_pairs=whipsaw_pairs,
        whipsaw_rate=whipsaw_pairs / 10,
        delayed_below_cap_sessions=0,
        reentry_lags=(),
        mean_reentry_lag=None,
        median_reentry_lag=None,
        recovery_durations=(),
        mean_recovery_duration=None,
        median_recovery_duration=None,
        incomplete_recovery_episodes=0,
    )


class CandidateQualificationTests(unittest.TestCase):
    def _periods(
        self,
        candidate,
        *,
        development_cagr=0.10,
        validation_cagr=0.10,
        combined_cagr=0.10,
        development_drawdown=-0.10,
        validation_drawdown=-0.10,
        combined_drawdown=-0.10,
        turnover=1.0,
        whipsaws=10,
    ):
        period_values = (
            (ResearchPeriod.DEVELOPMENT, development_cagr, development_drawdown),
            (ResearchPeriod.VALIDATION, validation_cagr, validation_drawdown),
            (ResearchPeriod.COMBINED_SELECTION, combined_cagr, combined_drawdown),
        )
        return tuple(
            regime_stabilization.CandidatePeriodResult(
                candidate=candidate,
                period=period,
                metrics=literal_metrics(
                    cagr=cagr,
                    max_drawdown=drawdown,
                    annualized_turnover=turnover,
                ),
                diagnostics=literal_diagnostics(whipsaw_pairs=whipsaws),
                points=(),
            )
            for period, cagr, drawdown in period_values
        )

    def _qualify(self, **candidate_values):
        candidate = StabilizationCandidate(0, 1)
        baseline = self._periods(
            None,
            development_cagr=0.10,
            validation_cagr=0.09,
            combined_cagr=0.095,
            turnover=1.0,
            whipsaws=10,
        )
        candidate_periods = self._periods(candidate, **candidate_values)
        return regime_stabilization._qualify_candidate(
            candidate, baseline, candidate_periods
        )

    def test_exact_risk_return_turnover_and_whipsaw_boundaries(self):
        qualification = self._qualify(
            development_cagr=0.095,
            validation_cagr=0.085,
            combined_cagr=0.096,
            development_drawdown=-0.20,
            validation_drawdown=-0.20,
            turnover=0.85,
            whipsaws=8,
        )
        gates = {gate.name: gate for gate in qualification.gates}

        self.assertTrue(qualification.qualified)
        self.assertEqual(
            {name: gate.status for name, gate in gates.items()},
            {
                "development_max_drawdown": GateStatus.PASS,
                "validation_max_drawdown": GateStatus.PASS,
                "combined_cagr_above_baseline": GateStatus.PASS,
                "development_cagr_floor": GateStatus.PASS,
                "validation_cagr_floor": GateStatus.PASS,
                "combined_turnover_reduction": GateStatus.PASS,
                "combined_whipsaw_reduction": GateStatus.PASS,
            },
        )
        self.assertEqual(gates["combined_turnover_reduction"].required, 0.85)
        self.assertEqual(gates["combined_whipsaw_reduction"].required, 8.0)

    def test_validation_drawdown_below_negative_twenty_percent_fails(self):
        qualification = self._qualify(
            combined_cagr=0.096,
            turnover=0.84,
            whipsaws=7,
            validation_drawdown=-0.201,
        )

        gate = next(
            gate
            for gate in qualification.gates
            if gate.name == "validation_max_drawdown"
        )
        self.assertEqual(gate.status, GateStatus.FAIL)
        self.assertFalse(qualification.qualified)

    def test_combined_cagr_equal_to_baseline_fails_strict_improvement(self):
        qualification = self._qualify(
            combined_cagr=0.095,
            turnover=0.84,
            whipsaws=7,
        )

        gate = next(
            gate
            for gate in qualification.gates
            if gate.name == "combined_cagr_above_baseline"
        )
        self.assertEqual(gate.status, GateStatus.FAIL)
        self.assertFalse(qualification.qualified)

    def test_zero_baseline_reduction_denominators_are_not_evaluable(self):
        candidate = StabilizationCandidate(0, 1)
        candidate_periods = self._periods(
            candidate, combined_cagr=0.11, turnover=0.0, whipsaws=0
        )

        for turnover, whipsaws, gate_name in (
            (0.0, 10, "combined_turnover_reduction"),
            (1.0, 0, "combined_whipsaw_reduction"),
        ):
            with self.subTest(gate_name=gate_name):
                baseline = self._periods(
                    None,
                    development_cagr=0.10,
                    validation_cagr=0.10,
                    combined_cagr=0.10,
                    turnover=turnover,
                    whipsaws=whipsaws,
                )
                qualification = regime_stabilization._qualify_candidate(
                    candidate, baseline, candidate_periods
                )
                gate = next(
                    gate for gate in qualification.gates if gate.name == gate_name
                )
                self.assertEqual(gate.status, GateStatus.NOT_EVALUABLE)
                self.assertFalse(qualification.qualified)


class LockedPromotionGateTests(unittest.TestCase):
    def _period(
        self,
        candidate,
        *,
        cagr,
        max_drawdown=-0.20,
        turnover=0.85,
        whipsaws=8,
    ):
        return regime_stabilization.CandidatePeriodResult(
            candidate=candidate,
            period=ResearchPeriod.LOCKED,
            metrics=literal_metrics(
                cagr=cagr,
                max_drawdown=max_drawdown,
                annualized_turnover=turnover,
            ),
            diagnostics=literal_diagnostics(whipsaw_pairs=whipsaws),
            points=(),
        )

    def test_public_signature_requires_one_frozen_candidate_without_search_inputs(self):
        signature = inspect.signature(
            regime_stabilization.evaluate_locked_regime_stabilization
        )

        self.assertEqual(
            tuple(signature.parameters),
            (
                "spy_bars",
                "bil_bars",
                "frozen_candidate",
                "engine",
                "initial_capital",
            ),
        )
        self.assertEqual(
            signature.parameters["frozen_candidate"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(
            signature.parameters["frozen_candidate"].default,
            inspect.Parameter.empty,
        )

    def test_candidate_outside_fixed_grid_is_rejected_before_data_access(self):
        with self.assertRaisesRegex(
            ValueError,
            "locked evaluation requires a frozen fixed-grid candidate",
        ):
            regime_stabilization.evaluate_locked_regime_stabilization(
                (),
                (),
                frozen_candidate=SimpleNamespace(
                    margin=20,
                    confirmation_sessions=10,
                ),
            )

    def test_locked_cagr_gate_rejects_one_ulp_below_and_passes_exact_floor(self):
        candidate = StabilizationCandidate(0, 1)
        baseline = self._period(
            None,
            cagr=0.10,
            turnover=1.0,
            whipsaws=10,
        )
        required_floor = 0.10 + LOCKED_CAGR_IMPROVEMENT
        below_floor = math.nextafter(required_floor, -math.inf)

        for cagr, expected_gate, expected_status in (
            (0.1024, GateStatus.FAIL, PromotionStatus.NO_V1_2_PROMOTION),
            (below_floor, GateStatus.FAIL, PromotionStatus.NO_V1_2_PROMOTION),
            (
                required_floor,
                GateStatus.PASS,
                PromotionStatus.PROMOTE_V1_2_RESEARCH,
            ),
        ):
            with self.subTest(cagr=cagr):
                gates, status = regime_stabilization._locked_promotion_decision(
                    baseline,
                    self._period(candidate, cagr=cagr),
                )
                cagr_gate = next(
                    gate for gate in gates if gate.name == "locked_cagr_improvement"
                )

                self.assertEqual(cagr_gate.status, expected_gate)
                self.assertEqual(status, expected_status)

    def test_zero_or_undefined_reduction_denominators_block_promotion(self):
        candidate = StabilizationCandidate(0, 1)

        for baseline_turnover in (0.0, None):
            with self.subTest(baseline_turnover=baseline_turnover):
                baseline = self._period(
                    None,
                    cagr=0.10,
                    turnover=baseline_turnover,
                    whipsaws=0,
                )
                gates, status = regime_stabilization._locked_promotion_decision(
                    baseline,
                    self._period(
                        candidate,
                        cagr=0.11,
                        turnover=0.0,
                        whipsaws=0,
                    ),
                )
                by_name = {gate.name: gate for gate in gates}

                self.assertEqual(
                    by_name["locked_turnover_reduction"].status,
                    GateStatus.NOT_EVALUABLE,
                )
                self.assertEqual(
                    by_name["locked_whipsaw_reduction"].status,
                    GateStatus.NOT_EVALUABLE,
                )
                self.assertEqual(status, PromotionStatus.NO_V1_2_PROMOTION)

    def test_locked_result_contract_is_minimal_frozen_and_slotted(self):
        candidate = StabilizationCandidate(0, 1)
        baseline = self._period(None, cagr=0.10, turnover=1.0, whipsaws=10)
        candidate_period = self._period(candidate, cagr=0.1025)
        gates, status = regime_stabilization._locked_promotion_decision(
            baseline,
            candidate_period,
        )
        result = regime_stabilization.LockedEvaluationResult(
            frozen_candidate=candidate,
            common_intervals=(),
            baseline=baseline,
            candidate=candidate_period,
            gates=gates,
            status=status,
        )

        self.assertEqual(
            tuple(
                field.name
                for field in fields(regime_stabilization.LockedEvaluationResult)
            ),
            (
                "frozen_candidate",
                "common_intervals",
                "baseline",
                "candidate",
                "gates",
                "status",
            ),
        )
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.status = PromotionStatus.NO_V1_2_PROMOTION


class CandidateRankingTests(unittest.TestCase):
    def _qualification(self, candidate, *, cagr, drawdown, whipsaws):
        periods = CandidateQualificationTests()._periods(
            candidate,
            combined_cagr=cagr,
            combined_drawdown=drawdown,
            whipsaws=whipsaws,
        )
        return regime_stabilization.CandidateQualification(
            candidate=candidate,
            periods=periods,
            gates=(GateResult("all", GateStatus.PASS, 1, 1),),
            qualified=True,
        )

    def test_return_tie_band_includes_exact_boundary_but_not_lower_candidate(self):
        top = self._qualification(
            StabilizationCandidate(10, 5), cagr=0.1000, drawdown=-0.10, whipsaws=5
        )
        boundary = self._qualification(
            StabilizationCandidate(10, 3), cagr=0.0995, drawdown=-0.10, whipsaws=4
        )
        outside = self._qualification(
            StabilizationCandidate(0, 1), cagr=0.09949, drawdown=-0.01, whipsaws=0
        )

        ranked = regime_stabilization._rank_qualified_candidates(
            (outside, top, boundary)
        )

        self.assertEqual(
            tuple(item.candidate for item in ranked),
            (boundary.candidate, top.candidate, outside.candidate),
        )

    def test_tie_order_is_whipsaw_drawdown_confirmation_then_margin(self):
        qualifications = (
            self._qualification(
                StabilizationCandidate(10, 5), cagr=0.10, drawdown=-0.05, whipsaws=2
            ),
            self._qualification(
                StabilizationCandidate(10, 1), cagr=0.10, drawdown=-0.20, whipsaws=1
            ),
            self._qualification(
                StabilizationCandidate(5, 5), cagr=0.10, drawdown=-0.10, whipsaws=1
            ),
            self._qualification(
                StabilizationCandidate(10, 3), cagr=0.10, drawdown=-0.10, whipsaws=1
            ),
            self._qualification(
                StabilizationCandidate(0, 3), cagr=0.10, drawdown=-0.10, whipsaws=1
            ),
        )

        ranked = regime_stabilization._rank_qualified_candidates(qualifications)

        self.assertEqual(
            tuple(item.candidate for item in ranked),
            (
                StabilizationCandidate(0, 3),
                StabilizationCandidate(10, 3),
                StabilizationCandidate(5, 5),
                StabilizationCandidate(10, 1),
                StabilizationCandidate(10, 5),
            ),
        )


class CandidateSelectionOrchestrationTests(unittest.TestCase):
    def test_public_signature_has_no_custom_grid_date_or_cost_parameters(self):
        signature = inspect.signature(
            regime_stabilization.select_regime_stabilization_candidate
        )

        self.assertEqual(
            tuple(signature.parameters),
            ("spy_bars", "bil_bars", "engine", "initial_capital"),
        )
        self.assertEqual(
            signature.parameters["engine"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(signature.parameters["engine"].default, None)
        self.assertEqual(
            signature.parameters["initial_capital"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(
            signature.parameters["initial_capital"].default, 100_000.0
        )

    def test_result_contracts_freeze_full_grid_gates_ranking_and_winner(self):
        spy, bil = make_selection_bars()

        result = regime_stabilization.select_regime_stabilization_candidate(
            spy, bil, engine=SelectionEngine()
        )

        self.assertEqual(
            tuple(field.name for field in fields(regime_stabilization.CandidatePeriodResult)),
            ("candidate", "period", "metrics", "diagnostics", "points"),
        )
        self.assertEqual(
            tuple(field.name for field in fields(regime_stabilization.CandidateQualification)),
            ("candidate", "periods", "gates", "qualified"),
        )
        self.assertEqual(
            tuple(field.name for field in fields(regime_stabilization.CandidateSelectionResult)),
            (
                "common_intervals",
                "baseline_periods",
                "candidates",
                "ranking_order",
                "status",
                "winner",
            ),
        )
        self.assertEqual(
            tuple(item.candidate for item in result.candidates),
            FIXED_STABILIZATION_CANDIDATES,
        )
        self.assertTrue(all(len(item.gates) == 7 for item in result.candidates))
        self.assertLessEqual(len(result.ranking_order), 12)
        self.assertEqual(
            result.status is SelectionStatus.SELECTED,
            result.winner is not None,
        )
        if result.winner is not None:
            self.assertEqual(result.winner, result.ranking_order[0])
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.winner = StabilizationCandidate(0, 1)

    def test_selection_uses_exact_common_intervals_and_premeasurement_state(self):
        spy, bil = make_selection_bars()
        measured_dates = tuple(bar.trading_date for bar in bil)

        result = regime_stabilization.select_regime_stabilization_candidate(
            spy, bil, engine=SelectionEngine()
        )

        expected_intervals = tuple(zip(measured_dates[:-1], measured_dates[1:]))
        self.assertEqual(result.common_intervals, expected_intervals)
        baseline_combined = next(
            item
            for item in result.baseline_periods
            if item.period is ResearchPeriod.COMBINED_SELECTION
        )
        self.assertEqual(
            tuple((point.signal_date, point.return_end_date) for point in baseline_combined.points),
            expected_intervals,
        )
        self.assertEqual(baseline_combined.points[0].target_spy_exposure, 1.0)
        self.assertEqual(baseline_combined.points[0].transaction_cost, 50.0)

        for qualification in result.candidates:
            combined = next(
                item
                for item in qualification.periods
                if item.period is ResearchPeriod.COMBINED_SELECTION
            )
            with self.subTest(candidate=qualification.candidate):
                self.assertEqual(
                    tuple(
                        (point.signal_date, point.return_end_date)
                        for point in combined.points
                    ),
                    expected_intervals,
                )
                self.assertEqual(combined.points[0].target_spy_exposure, 1.0)
                self.assertEqual(combined.points[0].transaction_cost, 50.0)

    def test_valid_dated_2021_content_cannot_affect_selection(self):
        spy, bil = make_selection_bars()
        baseline = regime_stabilization.select_regime_stabilization_candidate(
            spy, bil, engine=SelectionEngine()
        )
        future_spy = PriceBar(
            "SPY", date(2021, 1, 4), 1.0, 1.0, 1.0, 1.0, 1.0, 1
        )
        future_bil = PriceBar(
            "BIL", date(2021, 1, 4), 1.0, 1.0, 1.0, 1.0, 1.0, 1
        )
        object.__setattr__(future_spy, "symbol", "malformed")
        object.__setattr__(future_spy, "adjusted_close", "malformed")
        object.__setattr__(future_bil, "symbol", "malformed")
        object.__setattr__(future_bil, "adjusted_close", "malformed")

        changed = regime_stabilization.select_regime_stabilization_candidate(
            spy + [future_spy], bil + [future_bil], engine=SelectionEngine()
        )

        self.assertEqual(changed, baseline)

    def test_unparseable_date_fails_before_engine_is_called(self):
        spy, bil = make_selection_bars()
        unknown_date = PriceBar(
            "SPY", date(2021, 1, 4), 1.0, 1.0, 1.0, 1.0, 1.0, 1
        )
        object.__setattr__(unknown_date, "trading_date", "unparseable")
        engine = SelectionEngine()

        with self.assertRaises(InvalidEvaluationDataError):
            regime_stabilization.select_regime_stabilization_candidate(
                spy + [unknown_date], bil, engine=engine
            )

        self.assertEqual(engine.calls, [])


class LockedEvaluationOrchestrationTests(unittest.TestCase):
    def test_first_eligible_locked_signal_uses_zero_prior_exposure(self):
        spy, bil = make_initial_locked_bars()

        result = regime_stabilization.evaluate_locked_regime_stabilization(
            spy,
            bil,
            frozen_candidate=StabilizationCandidate(0, 1),
            engine=SelectionEngine(),
            initial_capital=100_000.0,
        )

        self.assertEqual(
            result.common_intervals,
            ((date(2021, 1, 4), date(2021, 1, 5)),),
        )
        self.assertEqual(result.baseline.points[0].exposure_change, 1.0)
        self.assertEqual(result.baseline.points[0].transaction_cost, 50.0)
        self.assertEqual(result.candidate.points[0].exposure_change, 0.3)
        self.assertEqual(result.candidate.points[0].transaction_cost, 15.0)

    def test_first_locked_cost_uses_state_before_actual_measured_date(self):
        state_points = (
            StabilizationSignalPoint(
                date(2020, 12, 31),
                60,
                MarketRegime.BULL,
                1.0,
                0.7,
                1.0,
                BoundaryConfirmationState(),
                StabilizationTransition.HOLD,
            ),
            StabilizationSignalPoint(
                date(2021, 1, 4),
                -50,
                MarketRegime.BEAR,
                0.0,
                1.0,
                0.0,
                BoundaryConfirmationState(),
                StabilizationTransition.DE_RISK,
            ),
        )

        self.assertEqual(
            regime_stabilization._prelocked_target(state_points, date(2021, 1, 5)),
            0.0,
        )

    def test_missing_first_locked_bil_signal_fails_instead_of_shifting_boundary(self):
        spy, bil, _ = make_locked_bars()

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "locked evaluation history does not cover the fixed start boundary",
        ):
            regime_stabilization.evaluate_locked_regime_stabilization(
                spy,
                bil[1:],
                frozen_candidate=StabilizationCandidate(0, 3),
                engine=LockedContinuityEngine(),
            )

    def test_locked_evaluation_rejects_candidate_subclass_impostor_before_data_access(self):
        class CandidateImpostor(StabilizationCandidate):
            def __post_init__(self):
                pass

            def __eq__(self, other):
                return True

        with self.assertRaisesRegex(
            ValueError,
            "locked evaluation requires a frozen fixed-grid candidate",
        ):
            regime_stabilization.evaluate_locked_regime_stabilization(
                (),
                (),
                frozen_candidate=CandidateImpostor(99, 99),
            )

    def test_locked_evaluation_rejects_mutated_equality_spoof_candidate(self):
        class EqualInt(int):
            def __eq__(self, other):
                return True

        candidate = StabilizationCandidate(0, 1)
        object.__setattr__(candidate, "margin", EqualInt(99))
        object.__setattr__(candidate, "confirmation_sessions", EqualInt(99))

        with self.assertRaisesRegex(
            ValueError,
            "locked evaluation requires a frozen fixed-grid candidate",
        ):
            regime_stabilization.evaluate_locked_regime_stabilization(
                (),
                (),
                frozen_candidate=candidate,
            )

    def test_prelocked_state_sets_first_target_and_only_actual_boundary_cost(self):
        spy, bil, locked_dates = make_locked_bars()
        engine = LockedContinuityEngine()
        candidate = StabilizationCandidate(0, 3)

        result = regime_stabilization.evaluate_locked_regime_stabilization(
            spy,
            bil,
            frozen_candidate=candidate,
            engine=engine,
            initial_capital=100_000.0,
        )

        expected_intervals = tuple(zip(locked_dates[:-1], locked_dates[1:]))
        self.assertEqual(result.frozen_candidate, candidate)
        self.assertEqual(result.common_intervals, expected_intervals)
        self.assertEqual(result.baseline.period, ResearchPeriod.LOCKED)
        self.assertIsNone(result.baseline.candidate)
        self.assertEqual(result.candidate.period, ResearchPeriod.LOCKED)
        self.assertEqual(result.candidate.candidate, candidate)
        self.assertEqual(len(result.gates), 4)
        self.assertEqual(result.status, PromotionStatus.NO_V1_2_PROMOTION)

        for period in (result.baseline, result.candidate):
            with self.subTest(period=period.candidate):
                self.assertEqual(
                    tuple(
                        (point.signal_date, point.return_end_date)
                        for point in period.points
                    ),
                    expected_intervals,
                )
                self.assertTrue(
                    all(point.signal_date >= LOCKED_START for point in period.points)
                )
                self.assertEqual(period.points[0].starting_value, 100_000.0)
                self.assertEqual(period.metrics.initial_capital, 100_000.0)

        self.assertEqual(result.baseline.points[0].target_spy_exposure, 1.0)
        self.assertEqual(result.baseline.points[0].exposure_change, 0.0)
        self.assertEqual(result.baseline.points[0].transaction_cost, 0.0)

        self.assertEqual(result.candidate.points[0].target_spy_exposure, 1.0)
        self.assertAlmostEqual(result.candidate.points[0].exposure_change, 0.3)
        self.assertAlmostEqual(result.candidate.points[0].transaction_cost, 15.0)
        self.assertAlmostEqual(result.candidate.metrics.final_value, 99_985.0)
        self.assertTrue(any(as_of < LOCKED_START for as_of, _ in engine.calls))
        self.assertTrue(all(qqq_bars is None for _, qqq_bars in engine.calls))


class PostSelectionDiagnosticsTests(unittest.TestCase):
    def test_public_signature_accepts_only_one_frozen_candidate_and_fixed_protocol_inputs(self):
        signature = inspect.signature(
            regime_stabilization.build_stabilization_post_selection_diagnostics
        )

        self.assertEqual(
            tuple(signature.parameters),
            (
                "spy_bars",
                "bil_bars",
                "frozen_candidate",
                "engine",
                "initial_capital",
            ),
        )
        self.assertEqual(
            signature.parameters["frozen_candidate"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertEqual(
            signature.parameters["frozen_candidate"].default,
            inspect.Parameter.empty,
        )
        for forbidden in ("grid", "costs", "windows", "start", "end"):
            self.assertNotIn(forbidden, signature.parameters)

    def test_candidate_outside_fixed_grid_is_rejected_before_data_access(self):
        with self.assertRaisesRegex(
            ValueError,
            "post-selection diagnostics require a frozen fixed-grid candidate",
        ):
            regime_stabilization.build_stabilization_post_selection_diagnostics(
                (),
                (),
                frozen_candidate=SimpleNamespace(
                    margin=20,
                    confirmation_sessions=10,
                ),
            )

    def test_post_selection_rejects_candidate_subclass_impostor_before_data_access(self):
        class CandidateImpostor(StabilizationCandidate):
            def __post_init__(self):
                pass

            def __eq__(self, other):
                return True

        with self.assertRaisesRegex(
            ValueError,
            "post-selection diagnostics require a frozen fixed-grid candidate",
        ):
            regime_stabilization.build_stabilization_post_selection_diagnostics(
                (),
                (),
                frozen_candidate=CandidateImpostor(99, 99),
            )

    def test_post_selection_rejects_mutated_equality_spoof_candidate(self):
        class EqualInt(int):
            def __eq__(self, other):
                return True

        candidate = StabilizationCandidate(0, 1)
        object.__setattr__(candidate, "margin", EqualInt(99))
        object.__setattr__(candidate, "confirmation_sessions", EqualInt(99))

        with self.assertRaisesRegex(
            ValueError,
            "post-selection diagnostics require a frozen fixed-grid candidate",
        ):
            regime_stabilization.build_stabilization_post_selection_diagnostics(
                (),
                (),
                frozen_candidate=candidate,
            )

    def test_full_path_cannot_silently_shift_the_fixed_start_boundary(self):
        spy, bil, _ = make_post_selection_bars()

        with self.assertRaisesRegex(
            InvalidEvaluationDataError,
            "post-selection history does not cover the fixed start boundary",
        ):
            regime_stabilization.build_stabilization_post_selection_diagnostics(
                spy,
                bil[1:],
                frozen_candidate=StabilizationCandidate(0, 3),
                engine=SelectionEngine(),
            )

    def test_fixed_costs_windows_and_full_path_are_descriptive_and_auditable(self):
        spy, bil, measured_dates = make_post_selection_bars()
        candidate = StabilizationCandidate(0, 3)
        engine = SelectionEngine()
        state_machine_candidates = []
        run_state_machine = regime_stabilization._run_stabilization_state_machine

        def record_state_machine(signals, frozen_candidate):
            state_machine_candidates.append(frozen_candidate)
            return run_state_machine(signals, frozen_candidate)

        forbidden_selection = AssertionError(
            "post-selection diagnostics cannot run selection or ranking"
        )
        with (
            patch.object(
                regime_stabilization,
                "select_regime_stabilization_candidate",
                side_effect=forbidden_selection,
            ),
            patch.object(
                regime_stabilization,
                "_qualify_candidate",
                side_effect=forbidden_selection,
            ),
            patch.object(
                regime_stabilization,
                "_ranking_values",
                side_effect=forbidden_selection,
            ),
            patch.object(
                regime_stabilization,
                "_rank_qualified_candidates",
                side_effect=forbidden_selection,
            ),
            patch.object(
                regime_stabilization,
                "_locked_promotion_decision",
                side_effect=forbidden_selection,
            ),
            patch.object(
                regime_stabilization,
                "_run_stabilization_state_machine",
                side_effect=record_state_machine,
            ),
        ):
            result = regime_stabilization.build_stabilization_post_selection_diagnostics(
                spy,
                bil,
                frozen_candidate=candidate,
                engine=engine,
                initial_capital=100_000.0,
            )

        expected_intervals = tuple(zip(measured_dates[:-1], measured_dates[1:]))
        expected_windows = (
            (
                "2008 financial crisis",
                date(2007, 10, 1),
                date(2009, 6, 30),
            ),
            (
                "2020 COVID crash and recovery",
                date(2020, 1, 1),
                date(2020, 12, 31),
            ),
            (
                "2022 bear market",
                date(2022, 1, 1),
                date(2022, 12, 31),
            ),
            (
                "2023-2025 recovery and bull period",
                date(2023, 1, 1),
                date(2025, 12, 31),
            ),
        )

        self.assertIs(result.frozen_candidate, candidate)
        self.assertEqual(result.common_intervals, expected_intervals)
        self.assertEqual(
            tuple(
                comparison.transaction_cost_bps
                for comparison in result.full_period_comparisons
            ),
            (0.0, 2.0, 5.0, 10.0),
        )
        self.assertEqual(
            tuple(
                (
                    comparison.window_name,
                    comparison.requested_start,
                    comparison.requested_end,
                    comparison.transaction_cost_bps,
                )
                for comparison in result.window_comparisons
            ),
            tuple(
                (*window, cost_bps)
                for cost_bps in (0.0, 2.0, 5.0, 10.0)
                for window in expected_windows
            ),
        )
        self.assertEqual(len(engine.calls), len(spy) - 252)
        self.assertEqual(state_machine_candidates, [candidate])

        for comparison in result.full_period_comparisons:
            expected_opening_cost = (
                100_000.0 * comparison.transaction_cost_bps / 10_000.0
            )
            for path in (comparison.baseline, comparison.candidate):
                with self.subTest(
                    scope="full",
                    cost_bps=comparison.transaction_cost_bps,
                    path=path,
                ):
                    self.assertEqual(
                        tuple(
                            (point.signal_date, point.return_end_date)
                            for point in path.points
                        ),
                        expected_intervals,
                    )
                    self.assertEqual(path.metrics.initial_capital, 100_000.0)
                    self.assertEqual(path.points[0].exposure_change, 1.0)
                    self.assertEqual(
                        path.points[0].transaction_cost,
                        expected_opening_cost,
                    )
                    self.assertEqual(
                        tuple(
                            bucket.exposure
                            for bucket in path.metrics.exposure_buckets
                        ),
                        (0.0, 0.3, 0.7, 1.0),
                    )

        for comparison in result.window_comparisons:
            self.assertIs(comparison.availability, EvaluationAvailability.AVAILABLE)
            for path in (comparison.baseline, comparison.candidate):
                with self.subTest(
                    scope=comparison.window_name,
                    cost_bps=comparison.transaction_cost_bps,
                    path=path,
                ):
                    self.assertEqual(len(path.points), 1)
                    self.assertGreaterEqual(
                        path.points[0].signal_date,
                        comparison.requested_start,
                    )
                    self.assertLessEqual(
                        path.points[-1].return_end_date,
                        comparison.requested_end,
                    )
                    self.assertEqual(path.metrics.initial_capital, 100.0)

        for forbidden in (
            "candidates",
            "ranking_order",
            "winner",
            "gates",
            "status",
        ):
            self.assertFalse(hasattr(result, forbidden))
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.frozen_candidate = StabilizationCandidate(5, 2)

    def test_public_result_contracts_are_minimal_frozen_and_slotted(self):
        spy, bil, _ = make_post_selection_bars()
        result = regime_stabilization.build_stabilization_post_selection_diagnostics(
            spy,
            bil,
            frozen_candidate=StabilizationCandidate(0, 3),
            engine=SelectionEngine(),
        )

        expected_fields = {
            regime_stabilization.PostSelectionPathResult: (
                "metrics",
                "diagnostics",
                "points",
            ),
            regime_stabilization.PostSelectionCostComparison: (
                "transaction_cost_bps",
                "baseline",
                "candidate",
            ),
            regime_stabilization.PostSelectionWindowComparison: (
                "window_name",
                "requested_start",
                "requested_end",
                "transaction_cost_bps",
                "availability",
                "baseline",
                "candidate",
            ),
            regime_stabilization.StabilizationPostSelectionResult: (
                "frozen_candidate",
                "common_intervals",
                "full_period_comparisons",
                "window_comparisons",
            ),
        }
        instances = (
            result.full_period_comparisons[0].baseline,
            result.full_period_comparisons[0],
            result.window_comparisons[0],
            result,
        )

        for contract, instance in zip(expected_fields, instances):
            with self.subTest(contract=contract.__name__):
                self.assertEqual(
                    tuple(field.name for field in fields(contract)),
                    expected_fields[contract],
                )
                self.assertFalse(hasattr(instance, "__dict__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(instance, fields(contract)[0].name, "mutation")

    def test_unavailable_fixed_window_is_retained_without_invented_paths(self):
        spy, bil, _ = make_post_selection_bars()

        result = regime_stabilization.build_stabilization_post_selection_diagnostics(
            spy[:-3],
            bil[:-3],
            frozen_candidate=StabilizationCandidate(0, 3),
            engine=SelectionEngine(),
        )

        unavailable = tuple(
            comparison
            for comparison in result.window_comparisons
            if comparison.window_name == "2023-2025 recovery and bull period"
        )
        self.assertEqual(len(unavailable), 4)
        for comparison in unavailable:
            with self.subTest(cost_bps=comparison.transaction_cost_bps):
                self.assertIs(
                    comparison.availability,
                    EvaluationAvailability.UNAVAILABLE,
                )
                self.assertIsNone(comparison.baseline)
                self.assertIsNone(comparison.candidate)

    def test_window_diagnostics_exclude_signal_whose_return_starts_at_requested_end(self):
        spy, bil, _ = make_post_selection_bars()

        result = regime_stabilization.build_stabilization_post_selection_diagnostics(
            spy,
            bil,
            frozen_candidate=StabilizationCandidate(0, 1),
            engine=WindowClosingTransitionEngine(),
        )

        gfc_windows = tuple(
            comparison
            for comparison in result.window_comparisons
            if comparison.window_name == "2008 financial crisis"
        )
        self.assertEqual(len(gfc_windows), 4)
        for comparison in gfc_windows:
            with self.subTest(cost_bps=comparison.transaction_cost_bps):
                for path in (comparison.baseline, comparison.candidate):
                    self.assertEqual(len(path.points), 1)
                    self.assertEqual(path.points[0].signal_date, DEVELOPMENT_START)
                    self.assertEqual(
                        path.points[0].return_end_date,
                        date(2009, 6, 30),
                    )
                    self.assertEqual(path.points[0].target_spy_exposure, 1.0)
                    self.assertEqual(
                        path.diagnostics.schedule_exposure_changes,
                        0,
                    )
                    self.assertIsNone(path.diagnostics.whipsaw_rate)


class StabilizationPublicExportTests(unittest.TestCase):
    def test_package_exports_only_public_orchestration_and_interpretation_contracts(self):
        expected = (
            "StabilizationCandidate",
            "StabilizationDiagnostics",
            "ResearchPeriod",
            "GateStatus",
            "GateResult",
            "CandidatePeriodResult",
            "CandidateQualification",
            "SelectionStatus",
            "CandidateSelectionResult",
            "PromotionStatus",
            "LockedEvaluationResult",
            "PostSelectionPathResult",
            "PostSelectionCostComparison",
            "PostSelectionWindowComparison",
            "StabilizationPostSelectionResult",
            "select_regime_stabilization_candidate",
            "evaluate_locked_regime_stabilization",
            "build_stabilization_post_selection_diagnostics",
        )
        forbidden = (
            "BoundaryConfirmationState",
            "StabilizationSignalPoint",
            "StabilizationTransition",
            "FIXED_STABILIZATION_CANDIDATES",
            "POST_SELECTION_COST_BPS",
            "_run_stabilization_state_machine",
            "_qualify_candidate",
            "_rank_qualified_candidates",
            "_simulate_bil_cash_schedule",
        )
        existing_v1_1_exports = (
            "EVALUATION_TRANSACTION_COST_BPS",
            "EvaluationAvailability",
            "EvaluationPoint",
            "EvaluationStrategy",
            "ExposureBucketPercentage",
            "HISTORICAL_REGIME_WINDOWS",
            "HistoricalWindowResult",
            "InvalidEvaluationDataError",
            "PerformanceMetrics",
            "RegimeBucketStats",
            "RegimeComparison",
            "RegimeEquityPoint",
            "RegimeEvaluationResult",
            "RegimeEvaluationV11Result",
            "RegimeObservation",
            "StrategyScenarioResult",
            "evaluate_regime_history",
            "evaluate_regime_v1_1",
        )

        self.assertEqual(set(backtest.__all__), set(existing_v1_1_exports + expected))
        self.assertEqual(len(backtest.__all__), len(set(backtest.__all__)))
        for name in expected:
            with self.subTest(export=name):
                self.assertIn(name, backtest.__all__)
                self.assertIs(
                    getattr(backtest, name),
                    getattr(regime_stabilization, name),
                )
        for name in forbidden:
            with self.subTest(not_exported=name):
                self.assertNotIn(name, backtest.__all__)
                self.assertFalse(hasattr(backtest, name))


class StabilizationDocumentationReleaseStateTests(unittest.TestCase):
    def _read_doc(self, name):
        return (Path(__file__).resolve().parents[1] / "docs" / name).read_text(
            encoding="utf-8"
        )

    def test_market_regime_docs_describe_v12_without_premature_result_claims(self):
        market_regime = self._read_doc("MARKET_REGIME_V1.md")

        for required in (
            "Market Regime Stabilization & Re-entry V1.2",
            "NO_QUALIFIED_CANDIDATE",
            "2021-01-01",
            "freshness must be rechecked",
        ):
            with self.subTest(required=required):
                self.assertIn(required, market_regime)

        self.assertNotIn("V1.2 winner:", market_regime)
        self.assertNotIn("PROMOTE_V1_2_RESEARCH confirmed", market_regime)

    def test_roadmap_keeps_both_manual_authorization_stages_unchecked(self):
        roadmap = self._read_doc("ROADMAP.md")

        self.assertIn("- [ ] Manual Stage 1", roadmap)
        self.assertIn("- [ ] Manual Stage 2", roadmap)
        self.assertNotIn("V1.2 winner:", roadmap)
        self.assertNotIn("PROMOTE_V1_2_RESEARCH confirmed", roadmap)


class StabilizationSourceSafetyTests(unittest.TestCase):
    def test_module_has_no_provider_broker_order_configuration_or_confidence_coupling(self):
        source = Path(regime_stabilization.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.add(module)
                imports.update(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                )

        for forbidden in (
            "streamlit",
            "dotenv",
            "ibapi",
            "private_quant.broker",
            "private_quant.app.paper_trading",
        ):
            self.assertFalse(
                any(
                    name == forbidden or name.startswith(forbidden + ".")
                    for name in imports
                )
            )
        self.assertFalse(any("qqq" in name.lower() for name in imports))
        for forbidden in (
            "RegimeConfidence",
            "placeOrder",
            "build_market_data_provider",
            ".env",
        ):
            self.assertNotIn(forbidden, source)

        confidence_identifiers = []
        qqq_identifiers = []
        qqq_keywords = []
        for node in ast.walk(tree):
            if isinstance(node, ast.arg):
                identifier = node.arg
            elif isinstance(node, ast.Name):
                identifier = node.id
            elif isinstance(node, ast.Attribute):
                identifier = node.attr
            elif isinstance(node, ast.alias):
                identifier = f"{node.name} {node.asname or ''}"
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifier = node.name
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                identifier = node.value
            else:
                identifier = None

            if identifier is not None and "qqq" in identifier.lower():
                qqq_identifiers.append(node)
            if identifier is not None and "confidence" in identifier.lower():
                confidence_identifiers.append(node)
            if isinstance(node, ast.keyword) and node.arg == "qqq_bars":
                qqq_keywords.append(node)

        self.assertEqual(qqq_identifiers, [])
        self.assertEqual(confidence_identifiers, [])
        self.assertGreaterEqual(len(qqq_keywords), 1)
        for keyword in qqq_keywords:
            self.assertIsInstance(keyword.value, ast.Constant)
            self.assertIsNone(keyword.value.value)


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


class StabilizationAccountingTests(unittest.TestCase):
    def test_bil_cash_schedule_charges_opening_70_percent_trade_before_return(self):
        aligned = SimpleNamespace(
            intervals=(
                _PriceInterval(date(2020, 1, 2), date(2020, 1, 3), 0.0, 0.0),
            )
        )

        points = regime_stabilization._simulate_bil_cash_schedule(
            aligned, (0.7,), cost_bps=5.0, initial_capital=100.0
        )

        self.assertEqual(points[0].transaction_cost, 0.035)

    def test_bil_cash_schedule_does_not_charge_unchanged_exposure(self):
        aligned = SimpleNamespace(
            intervals=(
                _PriceInterval(date(2020, 1, 2), date(2020, 1, 3), 0.0, 0.0),
                _PriceInterval(date(2020, 1, 3), date(2020, 1, 6), 0.0, 0.0),
            )
        )

        points = regime_stabilization._simulate_bil_cash_schedule(
            aligned, (0.7, 0.7), cost_bps=5.0, initial_capital=100.0
        )

        self.assertEqual(points[1].transaction_cost, 0.0)

    def test_period_slice_preserves_actual_boundary_exposure_change(self):
        points = _simulate_intervals(
            (
                _PriceInterval(date(2020, 1, 2), date(2020, 1, 3), 0.0, 0.0),
                _PriceInterval(date(2020, 1, 3), date(2020, 1, 6), 0.0, 0.0),
                _PriceInterval(date(2020, 1, 6), date(2020, 1, 7), 0.0, 0.0),
            ),
            (0.0, 0.3, 0.7),
            strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
            initial_capital=100.0,
            transaction_cost_bps=0.0,
        )

        period = regime_stabilization._slice_period_points(
            points, start=date(2020, 1, 6), end=date(2020, 1, 7)
        )

        self.assertEqual(len(period), 1)
        self.assertAlmostEqual(period[0].exposure_change, 0.4)

    def test_rebased_period_metrics_normalize_existing_path_to_100(self):
        points = _simulate_intervals(
            (
                _PriceInterval(date(2020, 1, 2), date(2020, 1, 3), 0.10, 0.0),
                _PriceInterval(date(2020, 1, 3), date(2020, 1, 6), -0.05, 0.0),
            ),
            (1.0, 1.0),
            strategy=EvaluationStrategy.REGIME_BIL_CASH_PROXY,
            initial_capital=200.0,
            transaction_cost_bps=0.0,
        )

        metrics = regime_stabilization._rebased_period_metrics(points)

        self.assertEqual(metrics.initial_capital, 100.0)
        self.assertAlmostEqual(metrics.final_value, 104.5)


class StabilizationDiagnosticsTests(unittest.TestCase):
    def _point(
        self,
        day,
        overlay,
        *,
        prior_overlay=None,
        cap=None,
        confirmations=BoundaryConfirmationState(),
    ):
        return StabilizationSignalPoint(
            signal_date=date(2020, 1, day),
            v1_score=60,
            v1_regime=MarketRegime.BULL,
            v1_maximum_long_exposure=overlay if cap is None else cap,
            prior_overlay_exposure=(
                overlay if prior_overlay is None else prior_overlay
            ),
            overlay_exposure=overlay,
            confirmations=confirmations,
            transition=StabilizationTransition.HOLD,
        )

    def _diagnostics(self, schedule, *, start_day=1, end_day=None):
        points = tuple(
            self._point(
                index,
                overlay,
                prior_overlay=schedule[index - 2] if index > 1 else overlay,
            )
            for index, overlay in enumerate(schedule, start=1)
        )
        return regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, start_day),
            end=date(2020, 1, end_day or len(schedule)),
            include_reentry_detail=False,
        )

    def test_downward_change_returning_to_prior_target_within_five_sessions_is_whipsaw(self):
        diagnostics = self._diagnostics((0.7, 0.3, 0.3, 0.7))

        self.assertEqual(diagnostics.schedule_exposure_changes, 2)
        self.assertEqual(diagnostics.whipsaw_pairs, 1)
        self.assertEqual(diagnostics.whipsaw_rate, 0.5)

    def test_upward_change_returning_to_prior_target_within_five_sessions_is_whipsaw(self):
        diagnostics = self._diagnostics((0.3, 0.7, 0.7, 0.3))

        self.assertEqual(diagnostics.schedule_exposure_changes, 2)
        self.assertEqual(diagnostics.whipsaw_pairs, 1)
        self.assertEqual(diagnostics.whipsaw_rate, 0.5)

    def test_partial_reversal_does_not_close_downward_whipsaw_before_full_return(self):
        diagnostics = self._diagnostics((1.0, 0.0, 0.3, 1.0, 0.3))

        self.assertEqual(diagnostics.schedule_exposure_changes, 4)
        self.assertEqual(diagnostics.whipsaw_pairs, 1)
        self.assertEqual(diagnostics.whipsaw_rate, 0.25)

    def test_monotonic_zero_to_full_schedule_has_no_whipsaw(self):
        diagnostics = self._diagnostics((0.0, 0.3, 0.7, 1.0))

        self.assertEqual(diagnostics.schedule_exposure_changes, 3)
        self.assertEqual(diagnostics.whipsaw_pairs, 0)
        self.assertEqual(diagnostics.whipsaw_rate, 0.0)

    def test_return_after_more_than_five_signal_sessions_is_not_whipsaw(self):
        diagnostics = self._diagnostics(
            (1.0, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 1.0)
        )

        self.assertEqual(diagnostics.schedule_exposure_changes, 2)
        self.assertEqual(diagnostics.whipsaw_pairs, 0)
        self.assertEqual(diagnostics.whipsaw_rate, 0.0)

    def test_constant_schedule_has_no_changes_and_no_whipsaw_rate(self):
        diagnostics = self._diagnostics((0.7, 0.7, 0.7))

        self.assertEqual(diagnostics.schedule_exposure_changes, 0)
        self.assertEqual(diagnostics.whipsaw_pairs, 0)
        self.assertIsNone(diagnostics.whipsaw_rate)

    def test_first_in_period_target_has_no_invented_schedule_change(self):
        diagnostics = self._diagnostics((0.3, 0.7), start_day=2, end_day=2)

        self.assertEqual(diagnostics.schedule_exposure_changes, 0)
        self.assertIsNone(diagnostics.whipsaw_rate)

    def test_whipsaw_pairs_are_non_overlapping(self):
        diagnostics = self._diagnostics((0.7, 0.3, 0.7, 0.3))

        self.assertEqual(diagnostics.schedule_exposure_changes, 3)
        self.assertEqual(diagnostics.whipsaw_pairs, 1)

    def test_completed_and_incomplete_defensive_recoveries_use_signal_sessions(self):
        points = (
            self._point(1, 1.0, prior_overlay=1.0),
            self._point(2, 0.7, prior_overlay=1.0, cap=0.7),
            self._point(3, 0.7, prior_overlay=0.7, cap=1.0),
            self._point(4, 1.0, prior_overlay=0.7),
            self._point(5, 1.0, prior_overlay=1.0),
            self._point(6, 0.7, prior_overlay=1.0, cap=0.7),
            self._point(7, 0.7, prior_overlay=0.7, cap=1.0),
        )

        diagnostics = regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, 1),
            end=date(2020, 1, 7),
            include_reentry_detail=True,
        )

        self.assertEqual(diagnostics.delayed_below_cap_sessions, 2)
        self.assertEqual(diagnostics.recovery_durations, (2,))
        self.assertEqual(diagnostics.mean_recovery_duration, 2.0)
        self.assertEqual(diagnostics.median_recovery_duration, 2.0)
        self.assertEqual(diagnostics.incomplete_recovery_episodes, 1)

    def test_reentry_lag_starts_on_first_qualification_after_counter_reset(self):
        points = (
            self._point(
                1,
                0.7,
                prior_overlay=0.7,
                cap=1.0,
                confirmations=BoundaryConfirmationState(3, 3, 0),
            ),
            self._point(
                2,
                0.7,
                prior_overlay=0.7,
                cap=1.0,
                confirmations=BoundaryConfirmationState(3, 3, 1),
            ),
            self._point(
                3,
                0.7,
                prior_overlay=0.7,
                cap=1.0,
                confirmations=BoundaryConfirmationState(3, 3, 2),
            ),
            self._point(
                4,
                1.0,
                prior_overlay=0.7,
                confirmations=BoundaryConfirmationState(3, 3, 3),
            ),
        )

        diagnostics = regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, 1),
            end=date(2020, 1, 4),
            include_reentry_detail=True,
        )

        self.assertEqual(diagnostics.reentry_lags, (3,))
        self.assertEqual(diagnostics.mean_reentry_lag, 3.0)
        self.assertEqual(diagnostics.median_reentry_lag, 3.0)

    def test_parallel_counters_preserve_pre_period_lags_across_successive_crossings(self):
        points = (
            self._point(
                1,
                0.0,
                prior_overlay=0.0,
                cap=1.0,
                confirmations=BoundaryConfirmationState(0, 0, 0),
            ),
            self._point(
                2,
                0.0,
                prior_overlay=0.0,
                cap=1.0,
                confirmations=BoundaryConfirmationState(1, 1, 1),
            ),
            self._point(
                3,
                0.3,
                prior_overlay=0.0,
                cap=1.0,
                confirmations=BoundaryConfirmationState(2, 2, 2),
            ),
            self._point(
                4,
                0.7,
                prior_overlay=0.3,
                cap=1.0,
                confirmations=BoundaryConfirmationState(2, 2, 2),
            ),
            self._point(
                5,
                1.0,
                prior_overlay=0.7,
                confirmations=BoundaryConfirmationState(2, 2, 2),
            ),
        )

        diagnostics = regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, 3),
            end=date(2020, 1, 5),
            include_reentry_detail=True,
        )

        self.assertEqual(diagnostics.schedule_exposure_changes, 2)
        self.assertEqual(diagnostics.reentry_lags, (2, 3, 4))
        self.assertEqual(diagnostics.mean_reentry_lag, 3.0)
        self.assertEqual(diagnostics.median_reentry_lag, 3.0)

    def test_recovery_opened_before_period_is_incomplete_until_full_duration_closes(self):
        points = (
            self._point(1, 1.0, prior_overlay=1.0),
            self._point(2, 0.7, prior_overlay=1.0, cap=0.7),
            self._point(3, 0.7, prior_overlay=0.7, cap=1.0),
            self._point(4, 0.7, prior_overlay=0.7, cap=1.0),
            self._point(5, 1.0, prior_overlay=0.7),
        )

        incomplete = regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, 3),
            end=date(2020, 1, 4),
            include_reentry_detail=True,
        )
        completed = regime_stabilization._stabilization_diagnostics(
            points,
            start=date(2020, 1, 3),
            end=date(2020, 1, 5),
            include_reentry_detail=True,
        )

        self.assertEqual(incomplete.recovery_durations, ())
        self.assertEqual(incomplete.incomplete_recovery_episodes, 1)
        self.assertEqual(completed.recovery_durations, (3,))
        self.assertEqual(completed.mean_recovery_duration, 3.0)
        self.assertEqual(completed.median_recovery_duration, 3.0)
        self.assertEqual(completed.incomplete_recovery_episodes, 0)


if __name__ == "__main__":
    unittest.main()
