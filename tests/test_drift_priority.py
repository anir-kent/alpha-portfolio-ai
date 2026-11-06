"""Pure drift engine and priority scorer: exact numbers, no I/O."""
import pytest

from app.config_service import Band, PriorityWeights
from app.drift import compute_drift
from app.priority import label_for, score_portfolio

BAND = Band(warn=3, breach=5)
W = PriorityWeights(drift=0.4, risk=0.3, opportunity=0.2, urgency=0.1)
TARGET = {"equity": 0.45, "bond": 0.45, "cash": 0.10}


def test_asset_class_drift_is_absolute_point_deviation_and_portfolio_drift_is_half_the_sum():
    d = compute_drift({"equity": 0.60, "bond": 0.35, "cash": 0.05}, TARGET, BAND)
    by = {c.asset_class: c for c in d.classes}
    assert by["equity"].drift_pp == pytest.approx(15)
    assert by["bond"].drift_pp == pytest.approx(10)
    assert by["cash"].drift_pp == pytest.approx(5)
    assert by["cash"].signed_pp == pytest.approx(-5)
    assert d.portfolio_drift_pp == pytest.approx(15)


@pytest.mark.parametrize("actual,status", [(0.47, "ok"), (0.48, "warn"), (0.50, "breach"), (0.41, "warn"), (0.35, "breach")])
def test_tolerance_band_status_per_asset_class(actual, status):
    d = compute_drift({"equity": actual, "bond": 0.45, "cash": 0.10}, TARGET, BAND)
    assert {c.asset_class: c for c in d.classes}["equity"].status == status


def test_missing_asset_class_counts_as_zero_weight():
    d = compute_drift({"equity": 0.5, "bond": 0.5}, TARGET, BAND)
    assert {c.asset_class: c for c in d.classes}["cash"].drift_pp == pytest.approx(10)


def test_clean_portfolio_scores_zero_and_low():
    d = compute_drift(TARGET, TARGET, BAND)
    s = score_portfolio(d, BAND, W, days_past_due=-30, sla_days=30)
    assert s.score == 0 and s.label == "Low" and not s.sla_breached


def test_breakdown_returns_components_weights_and_contributions():
    d = compute_drift({"equity": 0.60, "bond": 0.35, "cash": 0.05}, TARGET, BAND)  # drift 15pp
    s = score_portfolio(d, BAND, W, days_past_due=15, sla_days=30)
    c = {x.name: x for x in s.components}
    assert set(c) == {"drift", "risk", "opportunity", "urgency"}
    assert (c["drift"].raw, c["drift"].weight, c["drift"].points) == (100, 0.4, 40)
    assert (c["risk"].raw, c["risk"].points) == (100, 30)
    assert (c["opportunity"].raw, c["opportunity"].points) == (0, 0)
    assert (c["urgency"].raw, c["urgency"].points) == (50, 5)
    assert s.score == 75 and s.label == "High"


def test_weights_are_respected():
    d = compute_drift({"equity": 0.60, "bond": 0.35, "cash": 0.05}, TARGET, BAND)
    only_urgency = PriorityWeights(drift=0, risk=0, opportunity=0, urgency=1)
    s = score_portfolio(d, BAND, only_urgency, days_past_due=15, sla_days=30)
    assert s.score == 50 and s.label == "Medium"


def test_urgency_only_counts_days_past_due_and_flags_sla_breach_at_sla_days():
    d = compute_drift(TARGET, TARGET, BAND)
    not_due = score_portfolio(d, BAND, W, days_past_due=-5, sla_days=30)
    late = score_portfolio(d, BAND, W, days_past_due=10, sla_days=30)
    breached = score_portfolio(d, BAND, W, days_past_due=45, sla_days=30)

    def urg(s):
        return next(c for c in s.components if c.name == "urgency")

    assert urg(not_due).raw == 0 and not not_due.sla_breached
    assert urg(late).raw == pytest.approx(100 / 3) and not late.sla_breached
    assert urg(breached).raw == 100 and breached.sla_breached


def test_opportunity_input_feeds_the_opportunity_component():
    d = compute_drift(TARGET, TARGET, BAND)
    s = score_portfolio(d, BAND, W, days_past_due=-1, sla_days=30, opportunity=50)
    assert next(c for c in s.components if c.name == "opportunity").points == 10


@pytest.mark.parametrize("score,label", [(100, "High"), (70, "High"), (69.9, "Medium"), (40, "Medium"), (39.9, "Low"), (0, "Low")])
def test_labels(score, label):
    assert label_for(score) == label


def test_drift_exactly_on_a_band_edge_is_classified_at_that_edge():
    d = compute_drift({"equity": 0.48, "bond": 0.42, "cash": 0.10}, TARGET, BAND)  # 0.48-0.45 is 2.9999999999999996 in floats
    assert {c.asset_class: c for c in d.classes}["equity"].status == "warn"
