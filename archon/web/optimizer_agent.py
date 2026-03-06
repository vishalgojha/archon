"""A/B optimization agent for ARCHON embed configurations."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace
from typing import Literal

from archon.web.injection_generator import EmbedConfig

EventType = Literal["impression", "engagement", "conversion"]

try:  # pragma: no cover - optional dependency
    from scipy.stats import chi2_contingency  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    chi2_contingency = None


@dataclass(slots=True)
class ABVariant:
    """One experiment variant and event counters."""

    variant_id: str
    config: EmbedConfig
    impressions: int = 0
    engagements: int = 0
    conversions: int = 0


@dataclass(slots=True)
class Experiment:
    """A/B experiment data container."""

    experiment_id: str
    control_variant_id: str
    challenger_variant_id: str
    variants: dict[str, ABVariant] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExperimentResult:
    """A/B evaluation summary."""

    winner: str | None
    confidence: float
    lift_pct: float


class OptimizerAgent:
    """Runs and evaluates weekly embed A/B tests."""

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def create_experiment(self, base_config: EmbedConfig) -> Experiment:
        """Create control/challenger variants for a new experiment."""

        experiment_id = f"exp-{uuid.uuid4().hex[:10]}"
        control_id = "control"
        challenger_id = "challenger"
        challenger = _build_challenger(base_config)
        experiment = Experiment(
            experiment_id=experiment_id,
            control_variant_id=control_id,
            challenger_variant_id=challenger_id,
            variants={
                control_id: ABVariant(control_id, base_config),
                challenger_id: ABVariant(challenger_id, challenger),
            },
        )
        self._experiments[experiment_id] = experiment
        return experiment

    def record_event(self, experiment_id: str, variant_id: str, event_type: EventType) -> None:
        """Record one impression/engagement/conversion for a variant."""

        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(f"Unknown experiment_id: {experiment_id}")
        variant = experiment.variants.get(variant_id)
        if variant is None:
            raise KeyError(f"Unknown variant_id: {variant_id}")

        if event_type == "impression":
            variant.impressions += 1
        elif event_type == "engagement":
            variant.engagements += 1
        elif event_type == "conversion":
            variant.conversions += 1
        else:
            raise ValueError(f"Unsupported event_type: {event_type}")

    def evaluate_experiment(self, experiment_id: str) -> ExperimentResult:
        """Evaluate experiment winner using chi-squared significance."""

        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(f"Unknown experiment_id: {experiment_id}")

        control = experiment.variants[experiment.control_variant_id]
        challenger = experiment.variants[experiment.challenger_variant_id]
        if control.impressions < 10 or challenger.impressions < 10:
            return ExperimentResult(winner=None, confidence=0.0, lift_pct=0.0)

        control_conv = min(control.conversions, control.impressions)
        challenger_conv = min(challenger.conversions, challenger.impressions)
        control_fail = max(0, control.impressions - control_conv)
        challenger_fail = max(0, challenger.impressions - challenger_conv)

        p_value = _chi_square_p_value(
            [[control_conv, control_fail], [challenger_conv, challenger_fail]]
        )
        confidence = round(max(0.0, min(1.0, 1.0 - p_value)), 4)

        control_rate = control_conv / control.impressions if control.impressions else 0.0
        challenger_rate = (
            challenger_conv / challenger.impressions if challenger.impressions else 0.0
        )
        lift_pct = 0.0
        if control_rate > 0:
            lift_pct = ((challenger_rate - control_rate) / control_rate) * 100.0
        winner = None
        if p_value < 0.05 and control_rate != challenger_rate:
            winner = control.variant_id if control_rate > challenger_rate else challenger.variant_id
        return ExperimentResult(winner=winner, confidence=confidence, lift_pct=round(lift_pct, 3))

    def suggest_improvement(self, experiment_id: str) -> EmbedConfig:
        """Suggest next embed config based on current best variant."""

        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise KeyError(f"Unknown experiment_id: {experiment_id}")

        evaluation = self.evaluate_experiment(experiment_id)
        if evaluation.winner is None:
            winner_variant = experiment.variants[experiment.control_variant_id]
        else:
            winner_variant = experiment.variants[evaluation.winner]

        improved_config_json = dict(winner_variant.config.config_json)
        improved_config_json["optimizer"] = {
            "experiment_id": experiment_id,
            "winner": evaluation.winner,
            "confidence": evaluation.confidence,
            "lift_pct": evaluation.lift_pct,
        }
        return replace(winner_variant.config, config_json=improved_config_json)


def _build_challenger(base_config: EmbedConfig) -> EmbedConfig:
    new_json = dict(base_config.config_json)
    greeting = str(new_json.get("greeting", base_config.suggested_greeting))
    if "?" in greeting:
        challenger_greeting = greeting.replace("?", " right now?")
    else:
        challenger_greeting = f"{greeting} right now?"
    new_mode = "growth" if base_config.suggested_mode == "auto" else base_config.suggested_mode
    new_json["greeting"] = challenger_greeting
    new_json["mode"] = new_mode
    return replace(
        base_config,
        config_json=new_json,
        suggested_greeting=challenger_greeting,
        suggested_mode=new_mode,
    )


def _chi_square_p_value(table: list[list[int]]) -> float:
    if chi2_contingency is not None:  # pragma: no branch
        _chi2, p_value, _dof, _expected = chi2_contingency(table, correction=False)
        return float(p_value)

    a, b = table[0]
    c, d = table[1]
    total = a + b + c + d
    if total == 0:
        return 1.0

    row1 = a + b
    row2 = c + d
    col1 = a + c
    col2 = b + d
    if row1 == 0 or row2 == 0 or col1 == 0 or col2 == 0:
        return 1.0

    expected_a = (row1 * col1) / total
    expected_b = (row1 * col2) / total
    expected_c = (row2 * col1) / total
    expected_d = (row2 * col2) / total
    expected_values = [expected_a, expected_b, expected_c, expected_d]
    observed_values = [a, b, c, d]
    chi2 = 0.0
    for observed, expected in zip(observed_values, expected_values):
        if expected <= 0:
            return 1.0
        chi2 += ((observed - expected) ** 2) / expected

    # df=1 => CDF relationship with Gaussian error function.
    return math.erfc(math.sqrt(max(0.0, chi2) / 2.0))
