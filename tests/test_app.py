"""Smoke tests for the Streamlit app via AppTest (no server)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
sys.path.insert(0, str(ROOT))

TIMEOUT = 600


def _run(overrides=None):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    for k, v in (overrides or {}).items():
        at.session_state[k] = v
    at.run()
    return at


def test_tabs_and_defaults():
    at = _run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["Overview", "Scenario Explorer", "Calculations",
                                          "Charts"]
    labels = [m.label for m in at.metric]
    assert "Buy advantage" in labels and "Net worth breakeven" in labels


OVERRIDES = [
    {"horizon": 1},
    {"horizon": 30},
    {"down_pct": 3},
    {"down_pct": 100},
    {"alt_return": 0.0},
    {"alt_return": 12.0},
    {"home_appr": 0.0},
    {"mort_rate": 3.0},
    {"p2r": 10.0},
    {"p2r": 45.0},
    {"monthly_income": 20000},
    {"capital": 100000},                            # infeasible
    {"price": 5_000_000, "capital": 10_000_000},
    {"derive_rent": False, "rent0": 500},
    {"filing_status": "Married"},
    {"sweep_x": "mort_rate", "sweep_y": "alt_return"},
    {"sweep_x": "term", "sweep_y": "horizon"},
    {"sweep_x": "price", "sweep_y": "price"},       # same-axis warning
]


@pytest.mark.parametrize("overrides", OVERRIDES, ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items()))
def test_no_exception(overrides):
    at = _run(overrides)
    assert not at.exception, [e.value for e in at.exception]


def test_infeasible_shows_error():
    at = _run({"capital": 100000})
    assert any("Infeasible" in e.value for e in at.error)
    assert not at.tabs[2].dataframe
    assert not at.get("download_button")
    at.number_input(key="capital").set_value(1_500_000).run()
    assert at.tabs[2].dataframe
    assert at.get("download_button")


def test_same_axis_warning():
    at = _run({"sweep_x": "price", "sweep_y": "price"})
    assert any("same input" in w.value for w in at.warning)


def test_married_increases_buy_advantage():
    def adv(at):
        v = next(m.value for m in at.metric if m.label == "Buy advantage")
        return float(v.replace("$", "").replace(",", ""))
    assert adv(_run({"filing_status": "Married"})) > adv(_run())


def test_rerun_sequence_no_crash():
    """run -> price 1.2M -> run -> down 70% -> run. Runs in a subprocess so a
    segfault (exit 139 / -11; seen with pyarrow 25.0.0) fails the test instead
    of killing pytest."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file({APP!r}, default_timeout={TIMEOUT})
        at.run()
        at.number_input(key="price").set_value(1_200_000).run()
        at.slider(key="down_pct").set_value(70).run()
        assert not at.exception, [e.value for e in at.exception]
        print("OK")
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=TIMEOUT, cwd=ROOT)
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    assert "OK" in proc.stdout


@pytest.mark.parametrize("overrides, expected, delta", [
    ({"down_pct": 31}, "0 yrs", "same depletion month"),
    ({"monthly_income": 20_000}, "> 885 mo", "buy lasts longer"),
    ({"monthly_income": 20_000, "alt_return": 12.0}, "—", "both funded through year 100"),
])
def test_runway_comparison(overrides, expected, delta):
    at = _run(overrides)
    card = next(m for m in at.metric if m.label == "Buy runway advantage")
    assert (card.value, card.delta) == (expected, delta)
    if "monthly_income" in overrides:
        assert next(m.value for m in at.metric if m.label == "Forced sale") == "None in 100 yrs"


def test_manual_rent_matches_explorer_and_wealth_trace():
    at = _run({"derive_rent": False, "rent0": 500, "price": 200_000, "down_pct": 100})
    overview = next(m.value for m in at.metric if m.label == "Buy advantage")
    best = at.tabs[1].dataframe[0].value.iloc[0]
    assert best["Purchase price ($)"] == "$200,000"
    assert best["Best Down payment (%)"] == "100%"
    assert best["Buy advantage ($, maximize)"] == overview
    trace = at.tabs[2].dataframe[-1].value
    assert f"${trace.iloc[-1]['Buy advantage']:,.0f}" == overview
    assert trace.iloc[1]["Rent"] == 12 * 500
