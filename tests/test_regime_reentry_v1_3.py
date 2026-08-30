"""Contract tests for the V1.3 recovery-episode overlay."""

from dataclasses import FrozenInstanceError
from datetime import date
from enum import Enum
import math
import unittest

from private_quant.backtest import regime_reentry_v1_3 as module
from private_quant.backtest.regime_stabilization import _V1Signal, _stabilization_diagnostics
from private_quant.risk.market_regime import MarketRegime


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
