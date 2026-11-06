"""Seam: `run_analysis` with a progress reporter. The run tells the reporter about each Run Step as it goes (ADR-0005).
The HTTP contract that publishes this progress is covered through the API; this file covers only the reporter calls."""
import pytest

from app import audit
from app.analysis import run_analysis
from app.market_data import MarketData
from app.run_steps import RUN_STEPS
from tests.test_market_data import LOOKTHROUGH, SNAPSHOT
from tests.test_queue import seeded  # noqa: F401  (fixture)

KEYS = ["load_inputs", "score_portfolios", "record_run", "priority_narratives", "recommendation_narratives"]


class Recorder:
    def __init__(self):
        self.calls = []

    def step_started(self, key):
        self.calls.append(("started", key))

    def step_finished(self, key):
        self.calls.append(("finished", key))

    def step_skipped(self, key):
        self.calls.append(("skipped", key))

    def step_failed(self, key):
        self.calls.append(("failed", key))

    def portfolios_scored(self, done, total):
        self.calls.append(("scored", done, total))


@pytest.fixture
def market():
    return MarketData.load(SNAPSHOT, LOOKTHROUGH)


def run(app, market, reporter=None, llm=None):
    with app.state.session_factory() as db:
        return run_analysis(db, market, audit.Actor.system("test"), llm, reporter=reporter)


def test_run_step_keys_and_labels_are_fixed_and_ordered():
    assert [s.key for s in RUN_STEPS] == KEYS
    assert [s.label for s in RUN_STEPS] == [
        "Load inputs", "Score Portfolios", "Record run", "Priority narratives", "Recommendation narratives",
    ]


def test_a_run_without_an_llm_reports_every_step_in_order_and_skips_the_narratives(seeded, market):  # noqa: F811
    r = Recorder()
    run(seeded, market, r)
    steps = [c for c in r.calls if c[0] != "scored"]
    assert steps == [
        ("started", "load_inputs"), ("finished", "load_inputs"),
        ("started", "score_portfolios"), ("finished", "score_portfolios"),
        ("started", "record_run"), ("finished", "record_run"),
        ("skipped", "priority_narratives"), ("skipped", "recommendation_narratives"),
    ]


def test_score_portfolios_reports_the_count_after_each_portfolio(seeded, market):  # noqa: F811
    r = Recorder()
    run(seeded, market, r)
    start, end = r.calls.index(("started", "score_portfolios")), r.calls.index(("finished", "score_portfolios"))
    assert r.calls[start + 1:end] == [("scored", n, 25) for n in range(26)]


def test_a_run_with_an_llm_reports_both_narrative_steps(seeded, market):  # noqa: F811
    r = Recorder()
    run(seeded, market, r, llm=seeded.state.llm)
    assert r.calls[-4:] == [
        ("started", "priority_narratives"), ("finished", "priority_narratives"),
        ("started", "recommendation_narratives"), ("finished", "recommendation_narratives"),
    ]


def test_a_failing_step_is_reported_failed_the_rest_skipped_and_the_error_still_raised(seeded, market):  # noqa: F811
    class Broken(MarketData):
        def instrument(self, symbol):
            raise RuntimeError("market data is broken")

    broken = Broken(market.as_of, market.source, {}, {})
    r = Recorder()
    with pytest.raises(RuntimeError, match="market data is broken"):
        run(seeded, broken, r)
    steps = [c for c in r.calls if c[0] != "scored"]
    assert steps[-5:] == [
        ("started", "score_portfolios"), ("failed", "score_portfolios"),
        ("skipped", "record_run"), ("skipped", "priority_narratives"), ("skipped", "recommendation_narratives"),
    ]


def test_without_a_reporter_the_run_returns_the_run_id_and_portfolio_count(seeded, market):  # noqa: F811
    run_id, n = run(seeded, market)
    assert n == 25 and run_id >= 1
