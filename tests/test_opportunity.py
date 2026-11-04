"""Seam: the Opportunity component as a pure function of look-through sector exposure and approved Insights."""
from types import SimpleNamespace as NS

import pytest

from app.opportunity import opportunity_raw

EXPOSURE = {"Energy": 20.0, "Information Technology": 10.0, "Utilities": 5.0}


def insight(subject, direction="positive", kind="sector"):
    return NS(subject_kind=kind, subject=subject, direction=direction)


def test_no_approved_insights_means_zero_opportunity():
    assert opportunity_raw(EXPOSURE, []) == 0


def test_opportunity_rises_with_exposure_to_sectors_with_a_view():
    small = opportunity_raw(EXPOSURE, [insight("Utilities")])
    large = opportunity_raw(EXPOSURE, [insight("Energy")])
    both = opportunity_raw(EXPOSURE, [insight("Energy"), insight("Utilities")])
    assert 0 < small < large < both


def test_a_view_in_either_direction_counts_but_a_neutral_view_does_not():
    assert opportunity_raw(EXPOSURE, [insight("Energy", "negative")]) == opportunity_raw(EXPOSURE, [insight("Energy")])
    assert opportunity_raw(EXPOSURE, [insight("Energy", "neutral")]) == 0


def test_a_sector_is_counted_once_however_many_insights_cover_it():
    assert opportunity_raw(EXPOSURE, [insight("Energy"), insight("Energy", "negative")]) == opportunity_raw(EXPOSURE, [insight("Energy")])


def test_insights_on_sectors_the_portfolio_does_not_hold_or_on_asset_classes_add_nothing():
    assert opportunity_raw(EXPOSURE, [insight("Financials"), insight("equity", kind="asset_class")]) == 0


def test_scales_to_100_at_the_full_exposure_and_is_capped():
    assert opportunity_raw({"Energy": 15.0}, [insight("Energy")]) == pytest.approx(50)
    assert opportunity_raw({"Energy": 30.0}, [insight("Energy")]) == pytest.approx(100)
    assert opportunity_raw({"Energy": 60.0}, [insight("Energy")]) == 100
