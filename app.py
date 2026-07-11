"""Rent vs. Buy tradeoff dashboard.

Run with: streamlit run app.py
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import scenarios as scenario_store
from model import Assumptions, simulate, sweep, rent_from_price

st.set_page_config(page_title="Rent vs. Buy", layout="wide")

# ------------------------------------------------------- scenario state
# Defaults for every persisted widget (raw widget values, pre-conversion).
DEFAULTS = {
    # sidebar
    "capital": 1_500_000, "horizon": 10,
    "alt_return": 3.5, "inv_tax": 0.0, "cap_gains": 25.0,
    "home_appr": 5.5, "rent_growth": 4.0,
    "mort_rate": 6.5, "term": 30,
    "closing_pct": 1.5, "onetime": 10_000, "selling_pct": 6.0,
    "prop_tax": 1.15, "insurance": 0.25, "maintenance": 1.0, "hoa": 250,
    "marginal": 42.0, "deduct": True,
    "p2r": 28.0,
    # single-scenario tab
    "price": 1_400_000, "down_pct": 50, "derive_rent": True, "rent0": 4_167,
    # sweep tab constraints
    "min_reserve": 300_000, "max_monthly": 0, "pmax": 1_500_000,
}
PERSISTED_KEYS = list(DEFAULTS)

# Apply a pending scenario load BEFORE any widget is instantiated, then
# fill in defaults for anything not yet in session state.
_pending = st.session_state.pop("_pending_scenario", None)
if _pending:
    for _k in PERSISTED_KEYS:
        if _k in _pending:
            st.session_state[_k] = _pending[_k]
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


def fmt(x):
    return f"${x:,.0f}"


# ---------------------------------------------------------------- sidebar
def _save_current_scenario():
    name = st.session_state.get("scenario_name", "").strip()
    if not name:
        st.toast("Enter a scenario name first", icon=":material/warning:")
        return
    values = {k: st.session_state[k] for k in PERSISTED_KEYS if k in st.session_state}
    scenario_store.save_scenario(name, values)
    st.toast(f"Saved scenario “{name}”", icon=":material/save:")


def _load_selected_scenario():
    name = st.session_state.get("scenario_sel")
    data = scenario_store.load_scenarios().get(name)
    if data:
        # Applied at the top of the next script run, before widgets exist.
        st.session_state["_pending_scenario"] = data
        st.toast(f"Loaded scenario “{name}”", icon=":material/check:")


def _delete_selected_scenario():
    name = st.session_state.get("scenario_sel")
    if name:
        scenario_store.delete_scenario(name)
        st.toast(f"Deleted scenario “{name}”", icon=":material/delete:")


with st.sidebar.expander("Scenarios", icon=":material/bookmark:"):
    st.text_input("Scenario name", key="scenario_name", placeholder="e.g. Base case")
    st.button("Save", icon=":material/save:", on_click=_save_current_scenario)
    _saved = scenario_store.load_scenarios()
    if _saved:
        st.selectbox("Saved scenarios", sorted(_saved), key="scenario_sel")
        _lc, _dc = st.columns(2)
        _lc.button("Load", icon=":material/upload:", on_click=_load_selected_scenario)
        _dc.button("Delete", icon=":material/delete:", on_click=_delete_selected_scenario)
    else:
        st.caption("No saved scenarios yet.")

st.sidebar.title("Assumptions")

# ---- Section 0: The move ----------------------------------------
st.sidebar.subheader("The move")
price = st.sidebar.number_input("Purchase price ($)", 200_000, 5_000_000,
                                step=25_000, key="price")
down_pct = st.sidebar.slider("Down payment (%)", 3, 100, step=1, key="down_pct") / 100
st.sidebar.caption(f"Down payment: {fmt(price * down_pct)}")

# ---- Section 1: The deal ----------------------------------------
st.sidebar.subheader("The deal")
mort_rate = st.sidebar.slider("Mortgage rate (%)", 3.0, 9.0,
                              step=0.125, key="mort_rate") / 100
term = st.sidebar.radio("Term (years)", [15, 30], horizontal=True, key="term")
closing_pct = st.sidebar.slider("Buy closing costs (% of price)", 0.0, 5.0,
                                step=0.25, key="closing_pct") / 100
onetime = st.sidebar.slider("Other one-time costs ($, moving etc.)", 0, 100_000,
                            step=5_000, key="onetime")
hoa = st.sidebar.number_input("HOA ($/mo)", 0, 3_000, step=50, key="hoa")

# ---- Section 2: The market --------------------------------------
st.sidebar.subheader("The market")
alt_return = st.sidebar.slider(
    "Investment return (nominal, pre-tax, %)", 0.0, 12.0,
    step=0.25, key="alt_return",
    help="Default (3.5%) represents a high-yield-savings-style safe return. "
         "If you plan to hold equities, raise this — historically stocks have "
         "returned ~7–10% nominal before tax.",
) / 100
home_appr = st.sidebar.slider("Home appreciation (%/yr)", 0.0, 10.0,
                              step=0.25, key="home_appr") / 100
rent_growth = st.sidebar.slider("Rent growth (%/yr)", 0.0, 10.0,
                                step=0.25, key="rent_growth") / 100
p2r = st.sidebar.slider(
    "Market price-to-rent ratio", 10.0, 45.0, step=0.5, key="p2r",
    help="Purchase price ÷ annual rent for comparable homes. "
         "Higher = buying is expensive relative to renting. "
         "San Diego is roughly 25–30.",
)
st.sidebar.caption(
    f"At ratio {p2r:.0f}, a {fmt(price)} home rents for "
    f"≈ {fmt(rent_from_price(price, p2r))}/mo"
)
prop_tax = st.sidebar.slider("Property tax (initial, % of price)", 0.5, 2.5,
                             step=0.05, key="prop_tax") / 100
insurance = st.sidebar.slider("Insurance (% of value/yr)", 0.0, 1.0,
                              step=0.05, key="insurance") / 100
maintenance = st.sidebar.slider("Maintenance (% of value/yr)", 0.0, 3.0,
                                step=0.25, key="maintenance") / 100
selling_pct = st.sidebar.slider("Selling costs at exit (% of value)", 0.0, 10.0,
                                step=0.5, key="selling_pct") / 100

# ---- Section 3: Personal ----------------------------------------
st.sidebar.subheader("Personal")
capital = st.sidebar.number_input("Investable capital ($)", 100_000, 10_000_000,
                                  step=50_000, key="capital")
horizon = st.sidebar.slider("Horizon (years)", 1, 30, key="horizon")
marginal = st.sidebar.slider("Combined marginal tax rate (%)", 0.0, 55.0,
                             step=1.0, key="marginal") / 100
deduct = st.sidebar.checkbox("Deduct mortgage interest (≤ $750k of balance)", key="deduct")
inv_tax = st.sidebar.slider(
    "Annual tax on investment income (%)", 0.0, 50.0, step=1.0,
    key="inv_tax",
    help="Applies yearly (like HYSA interest or dividends taxed each year). "
         "Leave at 0 to tax all growth at sale instead.",
) / 100
cap_gains = st.sidebar.slider("Capital gains tax at sale (%)", 0.0, 45.0, step=1.0,
                              key="cap_gains",
                              help="Applied to unrealized gains (value − contributions) in "
                                   "all 'if sold' figures, for both scenarios.") / 100

base = Assumptions(
    capital=capital, horizon_years=horizon,
    alt_return_annual=alt_return, investment_tax_drag=inv_tax, cap_gains_rate=cap_gains,
    mortgage_rate=mort_rate, term_years=term,
    closing_buy_pct=closing_pct, other_onetime_costs=onetime, selling_cost_pct=selling_pct,
    home_appreciation=home_appr, property_tax_rate=prop_tax,
    insurance_rate=insurance, maintenance_rate=maintenance, hoa_monthly=hoa,
    marginal_tax_rate=marginal, include_interest_deduction=deduct,
    rent_growth=rent_growth,
)

# ---------------------------------------------------------------- main
st.title("Rent vs. Buy")

tab1, tab2, tab3 = st.tabs(["Single scenario", "Price × down payment sweep", "Details"])

# ================================================================ tab 1
with tab1:
    c1, c2 = st.columns(2)
    derive_rent = c1.checkbox("Derive rent from price-to-rent ratio", key="derive_rent")
    if derive_rent:
        rent0 = rent_from_price(price, p2r)
        c1.caption(f"Comparable rent: **{fmt(rent0)}/mo**")
    else:
        rent0 = c2.number_input("Monthly rent ($)", 500, 30_000, step=100, key="rent0")

    a = replace(base, price=price, down_pct=down_pct, monthly_rent=rent0)
    res = simulate(a)

    down = price * down_pct
    upfront = down + price * closing_pct + onetime
    if not res.feasible:
        st.error(f"Infeasible: upfront cash needed ({fmt(upfront)}) exceeds capital ({fmt(capital)}).")
    else:
        nw_buy = res.net_worth_buy_liq[-1]
        nw_rent = res.net_worth_rent_liq[-1]
        delta = nw_buy - nw_rent

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Net worth in {horizon} yrs — BUY", fmt(nw_buy),
                  help="After-tax portfolio + home value net of selling costs − loan balance")
        m2.metric(f"Net worth in {horizon} yrs — RENT", fmt(nw_rent),
                  help="Portfolio net of capital-gains tax if sold")
        m3.metric("Buy advantage", fmt(delta), delta=f"{delta / nw_rent * 100:+.1f}% vs rent")
        if res.breakeven_month > 0:
            m4.metric("Breakeven", f"year {res.breakeven_month / 12:.1f}",
                      help="First month buying (after selling costs) beats renting")
        else:
            m4.metric("Breakeven", "never (in horizon)")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Cash at closing", fmt(upfront))
        m2.metric("Liquid reserve after closing", fmt(capital - upfront))
        m3.metric("First-year monthly cost (net)", fmt(res.outflow_buy[1]),
                  help="P&I + taxes/insurance/maintenance/HOA/PMI − interest-deduction benefit")
        m4.metric("vs. rent", fmt(res.outflow_buy[1] - res.outflow_rent[1]),
                  delta="buy costs more/mo" if res.outflow_buy[1] > res.outflow_rent[1] else "buy costs less/mo",
                  delta_color="off")

        yrs = np.array(res.months) / 12
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy_liq, name="Buy (if sold, after tax)",
                                 line=dict(width=3)))
        fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy, name="Buy (mark-to-market)",
                                 line=dict(dash="dot")))
        fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq, name="Rent (if sold, after tax)",
                                 line=dict(width=3)))
        fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent, name="Rent (mark-to-market)",
                                 line=dict(dash="dot")))
        fig.update_layout(title="Net worth over time", xaxis_title="Years",
                          yaxis_title="Net worth ($)", hovermode="x unified", height=450)
        st.plotly_chart(fig)

        # composition of buy-side net worth: investments vs property equity
        equity_liq = [h * (1 - selling_pct) - b
                      for h, b in zip(res.home_value, res.loan_balance)]
        figc = go.Figure()
        figc.add_trace(go.Scatter(x=yrs, y=res.portfolio_buy_after_tax,
                                  name="Investments (after tax)",
                                  stackgroup="buy", line=dict(width=0.5)))
        figc.add_trace(go.Scatter(x=yrs, y=equity_liq,
                                  name="Home equity (after selling costs)",
                                  stackgroup="buy", line=dict(width=0.5)))
        figc.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq,
                                  name="Rent & invest (after tax)",
                                  line=dict(dash="dash", color="gray")))
        figc.update_layout(title="What makes up the buy net worth",
                           xaxis_title="Years", yaxis_title="$",
                           hovermode="x unified", height=400)
        st.plotly_chart(figc)

        colA, colB = st.columns(2)
        with colA:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=yrs[1:], y=res.outflow_buy[1:], name="Own (net monthly cost)"))
            fig2.add_trace(go.Scatter(x=yrs[1:], y=res.outflow_rent[1:], name="Rent"))
            fig2.update_layout(title="Monthly housing outflow", xaxis_title="Years",
                               yaxis_title="$/month", hovermode="x unified", height=380)
            st.plotly_chart(fig2)
        with colB:
            # sensitivity: buy advantage vs investment return
            rates = np.arange(0.03, 0.111, 0.005)
            adv = []
            for r in rates:
                s = simulate(replace(a, alt_return_annual=float(r)))
                adv.append(s.net_worth_buy_liq[-1] - s.net_worth_rent_liq[-1])
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=rates * 100, y=adv, name="Buy advantage"))
            fig3.add_hline(y=0, line_dash="dash", line_color="gray")
            fig3.add_vline(x=alt_return * 100, line_dash="dot", line_color="green",
                           annotation_text="your assumption")
            fig3.update_layout(title="Sensitivity: buy advantage vs. investment return",
                               xaxis_title="Investment return (pre-tax, %)",
                               yaxis_title=f"Buy − rent at year {horizon} ($)", height=380)
            st.plotly_chart(fig3)

# ================================================================ tab 2
with tab2:
    st.markdown(
        "Each cell: **buy-minus-rent net worth** at the horizon, where the rent alternative "
        "is the comparable home (rent = price ÷ price-to-rent ratio). Blank cells need more "
        "cash at closing than you have."
    )
    cc1, cc2, cc3 = st.columns(3)
    min_reserve = cc1.number_input("Constraint: min liquid reserve after closing ($)",
                                   0, 2_000_000, step=25_000, key="min_reserve")
    max_monthly = cc2.number_input("Constraint: max net monthly cost ($, 0 = no limit)",
                                   0, 50_000, step=500, key="max_monthly")
    pmax = cc3.number_input("Max price to explore ($)", 500_000, 5_000_000,
                            step=50_000, key="pmax")

    prices = np.arange(800_000, pmax + 1, 50_000)
    if prices.size == 0:  # pmax below the sweep floor
        prices = np.array([int(pmax)])
    downs = np.arange(0.10, 1.001, 0.05)

    @st.cache_data(show_spinner="Running sweep...")
    def run_sweep(base_a: Assumptions, prices_t, downs_t, ratio):
        return sweep(base_a, list(prices_t), list(downs_t), ratio)

    grid = run_sweep(base, tuple(prices), tuple(downs), p2r)

    z = np.array([[c["advantage"] for c in row] for row in grid])
    reserve = np.array([[c["reserve"] for c in row] for row in grid])
    mout = np.array([[c["max_outflow"] for c in row] for row in grid])

    ok = ~np.isnan(z) & (reserve >= min_reserve)
    if max_monthly > 0:
        ok &= mout <= max_monthly

    fig = go.Figure(go.Heatmap(
        z=z, x=[f"{d:.0%}" for d in downs], y=[f"${p/1e6:.2f}M" for p in prices],
        colorscale="RdBu", zmid=0, colorbar_title="Buy − rent ($)",
        hovertemplate="Price %{y}, down %{x}<br>Advantage: %{z:$,.0f}<extra></extra>",
    ))
    fig.update_layout(title=f"Buy advantage vs. renting comparable home, year {horizon}",
                      xaxis_title="Down payment", yaxis_title="Purchase price", height=550)
    st.plotly_chart(fig)

    if ok.any():
        masked = np.where(ok, z, -np.inf)
        i, j = np.unravel_index(np.argmax(masked), masked.shape)
        best_p, best_d = prices[i], downs[j]
        st.success(
            f"**Best cell under your constraints:** buy at **{fmt(best_p)}** with "
            f"**{best_d:.0%} down** ({fmt(best_p * best_d)}) → advantage of "
            f"**{fmt(z[i, j])}** over renting at year {horizon}. "
            f"Reserve after closing: {fmt(reserve[i, j])}; "
            f"first-year net monthly cost ≈ {fmt(mout[i, j])}."
        )
        # best down per price
        rows = []
        for ii, p in enumerate(prices):
            row_ok = ok[ii]
            if row_ok.any():
                jj = int(np.nanargmax(np.where(row_ok, z[ii], -np.inf)))
                rows.append({"Price": fmt(p), "Best down %": f"{downs[jj]:.0%}",
                             "Down $": fmt(p * downs[jj]),
                             "Advantage vs rent": fmt(z[ii, jj]),
                             "Reserve": fmt(reserve[ii, jj]),
                             "Net monthly (yr 1)": fmt(mout[ii, jj])})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    else:
        st.warning("No (price, down) combination satisfies your constraints.")

    st.markdown(f"**Slice: advantage vs. down payment at a fixed price**")
    sp = st.select_slider("Price", options=[int(p) for p in prices], value=1_400_000
                          if 1_400_000 in prices else int(prices[len(prices)//2]),
                          format_func=fmt)
    ii = int(np.where(prices == sp)[0][0])
    figs = go.Figure()
    figs.add_trace(go.Scatter(x=downs * 100, y=z[ii], mode="lines+markers"))
    figs.add_hline(y=0, line_dash="dash", line_color="gray")
    figs.update_layout(xaxis_title="Down payment (%)",
                       yaxis_title=f"Buy − rent at year {horizon} ($)", height=380)
    st.plotly_chart(figs)

# ================================================================ tab 3
with tab3:
    st.markdown("Full mechanics of the scenario from the **Single scenario** tab, "
                "one row per period — like a spreadsheet.")
    gran = st.segmented_control("Granularity", ["Yearly", "Monthly"], default="Yearly",
                                label_visibility="collapsed")

    # row 0 = closing day: flows are zero, balances are the starting position
    df_m = pd.DataFrame({
        "Month": res.months,
        # --- what the owner pays each month
        "P&I payment": res.payment_m,
        "  of which interest": res.interest_m,
        "  of which principal": res.principal_m,
        "Property tax": res.prop_tax_m,
        "Insurance": res.insurance_m,
        "Maintenance": res.maintenance_m,
        "HOA": res.hoa_m,
        "PMI": res.pmi_m,
        "Interest tax benefit (−)": res.tax_benefit_m,
        "Own cost (net)": res.outflow_buy,
        # --- the rent alternative
        "Rent": res.outflow_rent,
        "Own − rent": [b - r for b, r in zip(res.outflow_buy, res.outflow_rent)],
        "Invested → buy portfolio": res.contrib_buy_m,
        "Invested → rent portfolio": res.contrib_rent_m,
        # --- balances (end of period)
        "Home value": res.home_value,
        "Loan balance": res.loan_balance,
        "Home equity (if sold)": [h * (1 - selling_pct) - b for h, b in
                                  zip(res.home_value, res.loan_balance)],
        "Portfolio (buy)": res.portfolio_buy,
        "Portfolio (buy, after tax if sold)": res.portfolio_buy_after_tax,
        "Portfolio (rent)": res.portfolio_rent,
        "Portfolio (rent, after tax if sold)": res.portfolio_rent_after_tax,
        "Net worth — buy (if sold)": res.net_worth_buy_liq,
        "Net worth — rent (if sold)": res.net_worth_rent_liq,
        "Buy advantage": [b - r for b, r in
                          zip(res.net_worth_buy_liq, res.net_worth_rent_liq)],
    })

    FLOWS = ["P&I payment", "  of which interest", "  of which principal", "Property tax",
             "Insurance", "Maintenance", "HOA", "PMI", "Interest tax benefit (−)",
             "Own cost (net)", "Rent", "Own − rent",
             "Invested → buy portfolio", "Invested → rent portfolio"]
    STOCKS = ["Home value", "Loan balance", "Home equity (if sold)",
              "Portfolio (buy)", "Portfolio (buy, after tax if sold)",
              "Portfolio (rent)", "Portfolio (rent, after tax if sold)",
              "Net worth — buy (if sold)", "Net worth — rent (if sold)", "Buy advantage"]

    if gran == "Yearly":
        df_m["Year"] = (df_m["Month"] - 1) // 12 + 1  # month 0 -> year 0 (closing)
        agg = {c: "sum" for c in FLOWS} | {c: "last" for c in STOCKS}
        df = df_m.groupby("Year", as_index=False).agg(agg)
        period_col = "Year"
        st.caption("Row 0 is **closing day** (starting balances, no flows). Flows are "
                   "**summed per year**; balances are **end of year**.")
    else:
        df = df_m
        period_col = "Month"

    st.dataframe(
        df,
        column_config={period_col: st.column_config.NumberColumn(pinned=True)}
        | {c: st.column_config.NumberColumn(format="$%d") for c in FLOWS + STOCKS},
        hide_index=True,
    )
    st.download_button("Download as CSV", df.to_csv(index=False),
                       "rent_vs_buy_mechanics.csv", "text/csv")

    with st.expander("How to read this table"):
        st.markdown("""
- **Row 0 is closing day** — reconcile it against your settings: Portfolio (buy) =
  capital − down payment − closing costs − one-time costs; Portfolio (rent) = capital;
  Home value = purchase price; Loan balance = price − down payment; Home equity already
  reflects the selling-cost haircut.
- **Own cost (net)** = P&I + property tax + insurance + maintenance + HOA + PMI − interest
  tax benefit. This is the owner's true monthly outflow.
- **Own − rent** is the cash-flow gap between the two lifestyles. Whichever side is cheaper
  invests that gap: positive → **Invested → rent portfolio** (renting is cheaper that month),
  negative → **Invested → buy portfolio**. Both scenarios spend identical total dollars.
- **Portfolio (buy)** starts at capital − down payment − closing costs and compounds at the
  investment return (net of annual drag), plus any invested surplus.
- **… after tax if sold** = portfolio − capital-gains tax on embedded gains (value minus
  contributed dollars). Applied identically to both scenarios.
- **Home equity (if sold)** = home value × (1 − selling costs) − loan balance: the property
  side of the buy scenario.
- **Net worth — buy (if sold)** = Portfolio (buy, after tax if sold) + Home equity (if sold).
  The two components are shown separately so you can see how much of the buy net worth is
  liquid investments vs. locked in the property. Home-sale capital gains are not modeled.
- **Buy advantage** is the headline number: buy minus rent net worth, both on an
  after-tax "if sold" basis.
""")

    with st.expander("Model assumptions & known simplifications"):
        st.markdown("""
- **Fair comparison:** both scenarios spend the same total each month — whichever has the
  lower housing outflow invests the difference in its portfolio.
- **Investment taxes:** an annual drag on returns (dividends/turnover) plus capital-gains
  tax on unrealized gains, applied in every "if sold" figure for **both** scenarios.
  Cost basis = dollars contributed; gains above basis are taxed at the sale rate.
- **Interest deduction:** combined marginal rate × interest on the deductible share of the
  balance (capped at $750k of balance). Assumes you itemize either way.
- **Prop 13:** assessed value (property tax base) grows at 2%/yr regardless of market value.
- **PMI:** charged when down < 20%, drops when the balance falls below 78% of purchase price.
- **Home sale:** "if sold" subtracts selling costs but **not** capital-gains tax on the home
  (§121 excludes the first $250k single / $500k married of gain; big appreciation beyond
  that is untaxed in this model, which flatters buying slightly).
- All figures are **nominal** dollars.
""")
