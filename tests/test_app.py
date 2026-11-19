"""Smoke tests for the Streamlit app via AppTest (no server)."""

import json
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
                                          "Supplemental Analysis", "Assumptions"]
    labels = [m.label for m in at.metric]
    assert "Buy advantage" in labels and "Net worth breakeven" in labels


OVERRIDES = [
    {"horizon": 1},
    {"horizon": 30},
    {"financing_mode": "Down payment (%)", "down_pct": 3},
    {"financing_mode": "Down payment (%)", "down_pct": 100},
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
        at.radio(key="financing_mode").set_value("Down payment (%)").run()
        at.slider(key="down_pct").set_value(70).run()
        assert not at.exception, [e.value for e in at.exception]
        print("OK")
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=TIMEOUT, cwd=ROOT)
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    assert "OK" in proc.stdout


@pytest.mark.parametrize("overrides, expected, delta", [
    ({"financing_mode": "Down payment (%)", "down_pct": 31}, "0 yrs", "same depletion month"),
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
    at = _run({"derive_rent": False, "rent0": 500, "price": 200_000, "financing_mode": "Down payment (%)",
               "down_pct": 100, "sweep_y": "down_pct"})
    overview = next(m.value for m in at.metric if m.label == "Buy advantage")
    best = at.tabs[1].dataframe[0].value.iloc[0]
    assert best["Purchase price ($)"] == "$200,000"
    assert best["Best Down payment (%)"] == "100%"
    assert best["Buy advantage ($, maximize)"] == overview
    trace = at.tabs[2].dataframe[-1].value
    assert f"${trace.iloc[-1]['Buy advantage']:,.0f}" == overview
    assert trace.iloc[1]["Rent"] == 12 * 500


def test_charts_include_every_selectable_down_payment_and_return():
    at = _run({"financing_mode": "Down payment (%)", "down_pct": 31, "alt_return": 11.75})
    charts = {chart.proto.id.rsplit("-", 1)[-1]: json.loads(chart.proto.spec)["data"][0]
              for chart in at.get("plotly_chart")}
    for key in ("ov_wealth_dp_sweep", "ov_cashflow_dp_sweep", "ov_runway_sweep"):
        assert charts[key]["x"] == list(range(3, 101))
    sensitivity = charts["sup_sensitivity"]
    assert sensitivity["x"] == [step / 4 for step in range(49)]
    selected = sensitivity["x"].index(11.75)
    headline = next(m.value for m in at.metric if m.label == "Buy advantage")
    assert f"${sensitivity['y'][selected]:,.0f}" == headline


def test_default_decision_summary_reconciles_with_alternative_inputs():
    at = _run()
    overview = at.tabs[0]
    assert any("**3.25% per year**" in item.value for item in overview.markdown)
    targets, ranking, exits = [frame.value for frame in overview.dataframe]
    assert targets["Starting rent / month"].tolist() == [
        "From $2,185", "$2,185–$2,190", "$3,794", "$7,797",
    ]
    assert [item.label for item in overview.expander][-2:] == [
        "Break-even rent by outcome", "Which assumptions change the decision?",
    ]
    assert ranking.iloc[0]["Change tested"] == "Home appreciation +1 percentage point"
    assert ranking.iloc[0]["Effect on buy advantage"] == "+153,344 USD"
    headline = next(m.value for m in overview.metric if m.label == "Buy advantage")
    assert exits.iloc[2]["After selling"] == f"Buy ahead by {headline}"
    assert exits.iloc[-1]["After selling"].startswith("Rent ahead")
    at.number_input(key="annual_tax_limit").set_value(0).run()
    capped = next(m.value for m in at.metric if m.label == "Buy advantage")
    at.checkbox(key="deduct").uncheck().run()
    assert next(m.value for m in at.metric if m.label == "Buy advantage") == capped


def test_assumptions_tab_reflects_active_inputs():
    at = _run({"derive_rent": False, "rent0": 3200, "mort_rate": 6.125,
               "filing_status": "Married", "annual_tax_limit": 0})
    def summary():
        tables = [table.value for table in at.tabs[-1].table]
        assert all(list(table.columns) == ["Assumption", "Value/Formula", "Real Value", "Comment"]
                   for table in tables)
        return {row["Assumption"]: row for table in tables for row in table.to_dict("records")}

    values = summary()
    assert values["Starting comparable rent"]["Value/Formula"] == "$3,200/month"
    assert values["Starting comparable rent"]["Real Value"] == "$38,400"
    assert values["Mortgage rate"]["Value/Formula"] == "6.125% fixed"
    assert values["Mortgage rate"]["Real Value"] == f"${at.tabs[2].dataframe[-1].value.iloc[1]['  of which interest']:,.0f}"
    assert values["HOA dues"]["Real Value"] == "$3,000"
    assert values["Initial investment"]["Real Value"].splitlines() == [
        r"Buy \$819,000" + "  ", r"Rent \$1,500,000",
    ]
    assert values["Home-sale gain exclusion"]["Value/Formula"] == "$500,000"
    assert values["Home-sale gain exclusion"]["Real Value"] == "$0"
    assert values["Mortgage tax savings limit"]["Real Value"] == "$0"
    at.checkbox(key="deduct").uncheck().run()
    assert summary()["Mortgage tax savings limit"]["Value/Formula"] == "Inactive"


def test_fixed_financing_tracks_price_changes_and_explorer():
    at = _run({"home_appr": 10.0})
    def opening_loan():
        return at.tabs[2].dataframe[-1].value.iloc[0]["Loan balance"]

    assert opening_loan() == 750_000
    at.number_input(key="price").set_value(1_200_000).run()
    assert opening_loan() == 750_000
    grid = at.tabs[1].dataframe[0].value
    row = grid.loc[grid["Purchase price ($)"] == "$1,200,000"].iloc[0]
    assert row["Buy advantage ($, maximize)"] == next(m.value for m in at.metric if m.label == "Buy advantage")
    at.radio(key="financing_mode").set_value("Fixed down payment").run()
    at.number_input(key="fixed_down").set_value(450_000).run()
    assert opening_loan() == 750_000
    at.number_input(key="price").set_value(1_400_000).run()
    assert opening_loan() == 950_000
    at.radio(key="financing_mode").set_value("Fixed loan size").run()
    assert opening_loan() == 750_000
    at.radio(key="financing_mode").set_value("Fixed down payment").run()
    assert opening_loan() == 950_000
    at.number_input(key="fixed_down").set_value(1_500_000).run()
    assert not at.exception
    assert any("exceeds the purchase price" in msg.value for msg in at.error)


def test_concessions_show_offered_and_applied_credit():
    at = _run({"seller_credit": 30_000})
    assert not at.exception
    deal = at.tabs[-1].table[0].value.set_index("Assumption")
    assert deal.loc["Seller concessions", "Value/Formula"] == "$30,000"
    assert deal.loc["Seller concessions", "Real Value"] == "$21,000"
    assert deal.loc["Buyer-paid closing costs", "Real Value"] == "$0"
    closing = at.tabs[2].dataframe[0].value.set_index("Item")
    assert closing.loc["+ Seller credit applied", "Amount"] == "$21,000"


@pytest.mark.parametrize("overrides", [
    {"p2r": 19.5, "filing_status": "Married", "term": 15, "seller_credit": 8000,
     "fixed_loan": 600_000, "annual_tax_limit": 0, "sweep_x": "term", "sweep_y": "cap_gains"},
    {"derive_rent": False, "rent0": 3150, "deduct": False, "financing_mode": "Fixed down payment",
     "fixed_down": 530_000, "granularity": "Monthly", "sweep_x": "mort_rate"},
    {"financing_mode": "Down payment (%)", "down_pct": 36, "horizon": 6},
])
def test_shared_link_restores_scenario_in_fresh_session(overrides):
    from urllib.parse import parse_qs, urlsplit

    original = _run(overrides)
    link = json.loads(original.sidebar.get("bidi_component")[0].proto.json)
    restored = AppTest.from_file(APP, default_timeout=TIMEOUT)
    restored.query_params.update(parse_qs(urlsplit(link).query))
    restored.run()
    assert not restored.exception
    assert json.loads(restored.sidebar.get("bidi_component")[0].proto.json) == link
    for key, value in overrides.items():
        assert restored.session_state[key] == value
    assert [m.value for m in restored.metric] == [m.value for m in original.metric]


def test_monthly_rent_tracks_ratio_and_preserves_manual_entry():
    at = _run({"derive_rent": False, "rent0": 3200})
    assert not at.number_input(key="rent0").disabled
    at.checkbox(key="derive_rent").check().run()
    at.slider(key="p2r").set_value(20.0).run()
    rent, = [field for field in at.sidebar.number_input if field.label == "Monthly rent ($)"]
    assert rent.disabled
    assert rent.value == pytest.approx(at.number_input(key="price").value / 20 / 12)
    at.checkbox(key="derive_rent").uncheck().run()
    assert at.number_input(key="rent0").value == 3200
