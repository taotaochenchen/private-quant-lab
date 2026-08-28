from dataclasses import FrozenInstanceError, fields
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
from private_quant.risk import MarketRegime


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


if __name__ == "__main__":
    unittest.main()
