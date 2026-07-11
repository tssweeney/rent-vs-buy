"""Rent vs. Buy tradeoff dashboard.

Run with: streamlit run app.py
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from model import Assumptions, simulate, sweep, rent_from_price

st.set_page_config(page_title="Rent vs. Buy", page_icon=":material/home_work:",
                   layout="wide")

# Defaults for every widget (raw widget values, pre-conversion).
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
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


def fmt(x):
    return f"${x:,.0f}"


def fmtm(x):
    """Markdown-safe currency: `\\$` stops Streamlit treating $...$ as LaTeX math."""
    return f"\\${x:,.0f}"


def compact(fig, height=340, legend=True, **layout):
    """Dense chart layout: tight margins, small top legend, no plotly title."""
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=20, t=40, b=30),
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="left", x=0, font=dict(size=10)),
        **layout,
    )
    return fig


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Assumptions")

# ---- Section 0: The move ----------------------------------------
st.sidebar.subheader("The move")
price = st.sidebar.number_input("Purchase price ($)", 200_000, 5_000_000,
                                step=25_000, key="price",
                                help="Contract price of the home. Drives the loan size, "
                                     "property tax, and the comparable rent.")
down_pct = st.sidebar.slider("Down payment (%)", 3, 100, step=1, key="down_pct",
                             help="Share of the price paid in cash at closing; the rest "
                                  "is the mortgage. Below 20% adds PMI until you reach "
                                  "22% equity.") / 100
st.sidebar.caption(f"Down payment: {fmtm(price * down_pct)}")

# ---- Section 1: The deal ----------------------------------------
st.sidebar.subheader("The deal")
mort_rate = st.sidebar.slider("Mortgage rate (%)", 3.0, 9.0,
                              step=0.125, key="mort_rate",
                              help="Fixed note rate from your lender quote (not APR — "
                                   "lender fees belong in closing costs).") / 100
term = st.sidebar.segmented_control("Term (years)", [15, 30], key="term",
                                    help="Loan length. 15-year loans usually price 0.5–0.75% "
                                         "below 30-year but roughly double the principal "
                                         "portion of P&I.") or DEFAULTS["term"]
closing_pct = st.sidebar.slider("Closing costs (% of price)", 0.0, 5.0,
                                step=0.25, key="closing_pct",
                                help="Escrow, title, origination, inspection etc., paid in "
                                     "cash at closing on top of the down payment.") / 100
onetime = st.sidebar.slider("One-time costs ($)", 0, 100_000,
                            step=5_000, key="onetime",
                            help="Movers, immediate repairs, furniture — cash spent once "
                                 "at move-in, gone from the buy-side portfolio.")
hoa = st.sidebar.number_input("HOA ($/mo)", 0, 3_000, step=50, key="hoa",
                              help="Monthly homeowners-association dues, if any. Flat — "
                                   "does not grow in this model.")

# ---- Section 2: The market --------------------------------------
st.sidebar.subheader("The market")
alt_return = st.sidebar.slider(
    "Investment return (%, pre-tax)", 0.0, 12.0,
    step=0.25, key="alt_return",
    help="Default (3.5%) represents a high-yield-savings-style safe return. "
         "If you plan to hold equities, raise this — historically stocks have "
         "returned ~7–10% nominal before tax.",
) / 100
home_appr = st.sidebar.slider("Home appreciation (%/yr)", 0.0, 10.0,
                              step=0.25, key="home_appr",
                              help="Nominal annual growth of the home's market value. "
                                   "Case-Shiller San Diego compounded ≈5.8%/yr over "
                                   "1987–2025; default is a slightly conservative 5.5%.") / 100
rent_growth = st.sidebar.slider("Rent growth (%/yr)", 0.0, 10.0,
                                step=0.25, key="rent_growth",
                                help="Annual rent increases in the rent scenario. San Diego "
                                     "long run ≈4%; recent years 2.5–3.5%.") / 100
p2r = st.sidebar.slider(
    "Price-to-rent ratio", 10.0, 45.0, step=0.5, key="p2r",
    help="Purchase price ÷ annual rent for comparable homes. "
         "Higher = buying is expensive relative to renting. "
         "San Diego is roughly 25–30.",
)
st.sidebar.caption(
    f"At ratio {p2r:.0f}, a {fmtm(price)} home rents for "
    f"≈ {fmtm(rent_from_price(price, p2r))}/mo"
)
prop_tax = st.sidebar.slider("Property tax (% of price)", 0.5, 2.5,
                             step=0.05, key="prop_tax",
                             help="First-year effective rate on the purchase price "
                                  "(San Diego ≈1.1–1.25% incl. Mello-Roos/bonds). The "
                                  "assessed value then grows only 2%/yr under Prop 13.") / 100
insurance = st.sidebar.slider("Insurance (% of value/yr)", 0.0, 1.0,
                              step=0.05, key="insurance",
                              help="Homeowners insurance as a share of current market "
                                   "value, per year.") / 100
maintenance = st.sidebar.slider("Maintenance (% of value/yr)", 0.0, 3.0,
                                step=0.25, key="maintenance",
                                help="Repairs and upkeep as a share of current market "
                                     "value per year; 1% is the common rule of thumb.") / 100
selling_pct = st.sidebar.slider("Selling costs (% of value)", 0.0, 10.0,
                                step=0.5, key="selling_pct",
                                help="Agent commissions + seller closing costs, subtracted "
                                     "from home value in every 'if sold' figure.") / 100

# ---- Section 3: Personal ----------------------------------------
st.sidebar.subheader("Personal")
capital = st.sidebar.number_input("Investable capital ($)", 100_000, 10_000_000,
                                  step=50_000, key="capital",
                                  help="Total cash you're deploying. Buy: pays down payment "
                                       "+ closing + one-time costs, remainder is invested. "
                                       "Rent: all of it is invested.")
horizon = st.sidebar.slider("Horizon (years)", 1, 30, key="horizon",
                            help="When the two scenarios are compared: both are valued "
                                 "'if sold' at this point.")
marginal = st.sidebar.slider("Marginal tax rate (%)", 0.0, 55.0,
                             step=1.0, key="marginal",
                             help="Federal + California rate on your last dollar of income; "
                                  "sets the value of the mortgage-interest deduction. "
                                  "~42% around $300k single in CA.") / 100
deduct = st.sidebar.checkbox("Deduct mortgage interest", key="deduct",
                             help="Reduces the owner's monthly cost by marginal rate × "
                                  "interest on the first $750k of loan balance. Assumes "
                                  "you itemize.")
inv_tax = st.sidebar.slider(
    "Annual tax on returns (%)", 0.0, 50.0, step=1.0,
    key="inv_tax",
    help="Applies yearly (like HYSA interest or dividends taxed each year). "
         "Leave at 0 to tax all growth at sale instead.",
) / 100
cap_gains = st.sidebar.slider("Capital gains at sale (%)", 0.0, 45.0, step=1.0,
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

tab1, tab2, tab3, tab4 = st.tabs(
    ["Single scenario", "Price × down payment sweep", "Details", "Methodology"])

# ================================================================ tab 1
with tab1:
    c1, c2 = st.columns(2, vertical_alignment="center")
    derive_rent = c1.checkbox("Derive rent from price-to-rent ratio", key="derive_rent",
                              help="On: rent for the comparable home = price ÷ ratio ÷ 12, "
                                   "so it tracks the purchase price. Off: type a rent "
                                   "you've actually seen on the market.")
    if derive_rent:
        rent0 = rent_from_price(price, p2r)
        c1.caption(f"Comparable rent: {fmtm(rent0)}/mo")
    else:
        rent0 = c2.number_input("Monthly rent ($)", 500, 30_000, step=100, key="rent0",
                                help="Starting monthly rent for the comparable home; grows "
                                     "at the rent-growth rate each year.")

    a = replace(base, price=price, down_pct=down_pct, monthly_rent=rent0)
    res = simulate(a)

    down = price * down_pct
    upfront = down + price * closing_pct + onetime
    if not res.feasible:
        st.error(f"Infeasible: upfront cash needed ({fmtm(upfront)}) exceeds capital ({fmtm(capital)}).")
    else:
        nw_buy = res.net_worth_buy_liq[-1]
        nw_rent = res.net_worth_rent_liq[-1]
        delta = nw_buy - nw_rent

        # yearly snapshots (evenly spaced) for metric sparklines
        yearly_idx = range(0, len(res.months), 12)
        spark_buy = [res.net_worth_buy_liq[i] for i in yearly_idx]
        spark_rent = [res.net_worth_rent_liq[i] for i in yearly_idx]

        with st.container(horizontal=True):
            st.metric(f"Buy net worth (yr {horizon})", fmt(nw_buy), border=True,
                      chart_data=spark_buy, chart_type="line",
                      help="After-tax portfolio + home value net of selling costs − loan "
                           "balance. Sparkline: yearly values.")
            st.metric(f"Rent net worth (yr {horizon})", fmt(nw_rent), border=True,
                      chart_data=spark_rent, chart_type="line",
                      help="Portfolio net of capital-gains tax if sold. Sparkline: yearly "
                           "values.")
            st.metric("Buy advantage", fmt(delta), delta=f"{delta / nw_rent * 100:+.1f}% vs rent",
                      border=True,
                      help="Buy net worth minus rent net worth at the horizon, both after "
                           "taxes and selling costs. Positive = buying wins.")
            if res.breakeven_month > 0:
                st.metric("Breakeven", f"year {res.breakeven_month / 12:.1f}", border=True,
                          help="First month buying (after selling costs) beats renting")
            else:
                st.metric("Breakeven", "never (in horizon)", border=True,
                          help="Buying never catches renting within the horizon; extend the "
                               "horizon or change assumptions to see where it would.")

        with st.container(horizontal=True):
            st.metric("Cash at closing", fmt(upfront), border=True,
                      help="Down payment + closing costs + one-time costs — leaves your "
                           "capital on day one")
            st.metric("Reserve after closing", fmt(capital - upfront), border=True,
                      help="Capital left invested after closing — your emergency cushion in "
                           "the buy scenario")
            st.metric("Net monthly cost (yr 1)", fmt(res.outflow_buy[1]), border=True,
                      help="P&I + taxes/insurance/maintenance/HOA/PMI − interest-deduction benefit")
            st.metric("vs. rent (mo 1)", fmt(res.outflow_buy[1] - res.outflow_rent[1]),
                      delta="buy costs more/mo" if res.outflow_buy[1] > res.outflow_rent[1]
                      else "buy costs less/mo",
                      delta_color="off", border=True,
                      help="Owner's net monthly cost minus rent in month 1. Whichever side is "
                           "cheaper invests this difference every month.")

        yrs = np.array(res.months) / 12

        r1c1, r1c2 = st.columns(2)
        with r1c1.container(border=True):
            st.markdown("**Net worth over time**")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy_liq, name="Buy (if sold)",
                                     line=dict(width=3)))
            fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy, name="Buy (mark-to-market)",
                                     line=dict(dash="dot")))
            fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq, name="Rent (if sold)",
                                     line=dict(width=3)))
            fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent, name="Rent (mark-to-market)",
                                     line=dict(dash="dot")))
            st.plotly_chart(compact(fig, xaxis_title="Years", yaxis_title="$"))
            st.caption("Solid = if sold today (after selling costs and cap-gains tax); "
                       "dotted = mark-to-market.")

        with r1c2.container(border=True):
            st.markdown("**Buy net worth composition**")
            equity_liq = [h * (1 - selling_pct) - b
                          for h, b in zip(res.home_value, res.loan_balance)]
            figc = go.Figure()
            figc.add_trace(go.Scatter(x=yrs, y=res.portfolio_buy_after_tax,
                                      name="Investments (after tax)",
                                      stackgroup="buy", line=dict(width=0.5)))
            figc.add_trace(go.Scatter(x=yrs, y=equity_liq,
                                      name="Home equity (net)",
                                      stackgroup="buy", line=dict(width=0.5)))
            figc.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq,
                                      name="Rent (after tax)",
                                      line=dict(dash="dash", color="gray")))
            st.plotly_chart(compact(figc, xaxis_title="Years", yaxis_title="$"))
            st.caption("Bands sum to the buy 'if sold' line; home equity is only "
                       "accessible by selling or borrowing.")

        r2c1, r2c2 = st.columns(2)
        with r2c1.container(border=True):
            st.markdown("**Monthly housing outflow**")
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=yrs[1:], y=res.outflow_buy[1:], name="Own (net)"))
            fig2.add_trace(go.Scatter(x=yrs[1:], y=res.outflow_rent[1:], name="Rent"))
            st.plotly_chart(compact(fig2, xaxis_title="Years", yaxis_title="$/mo"))
            st.caption("Owning steps down when PMI drops off; rent compounds yearly.")

        with r2c2.container(border=True):
            st.markdown("**Sensitivity: buy advantage vs. investment return**")
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
            st.plotly_chart(compact(fig3, legend=False,
                                    xaxis_title="Investment return (pre-tax, %)",
                                    yaxis_title=f"Buy − rent, yr {horizon} ($)"))
            st.caption("Zero crossing = investment return at which renting starts to win.")

# ================================================================ tab 2
with tab2:
    st.caption("Each cell: buy − rent net worth at the horizon, renting the comparable "
               "home (rent = price ÷ price-to-rent ratio ÷ 12). Blank cells need more "
               "cash at closing than you have.")
    cc1, cc2, cc3 = st.columns(3)
    min_reserve = cc1.number_input("Min reserve after closing ($)",
                                   0, 2_000_000, step=25_000, key="min_reserve",
                                   help="Cells leaving less cash than this after down "
                                        "payment + closing are excluded from the "
                                        "recommendation (still shown on the heatmap).")
    max_monthly = cc2.number_input("Max monthly cost ($, 0 = no limit)",
                                   0, 50_000, step=500, key="max_monthly",
                                   help="Excludes cells whose first-year net monthly owner "
                                        "cost exceeds this comfort ceiling.")
    pmax = cc3.number_input("Max price to explore ($)", 500_000, 5_000_000,
                            step=50_000, key="pmax",
                            help="Top of the price range swept on the heatmap (bottom is "
                                 "$800k, in $50k steps).")

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

    left, right = st.columns([3, 2])

    with left.container(border=True):
        st.markdown(f"**Buy advantage vs. renting comparable home, year {horizon}**")
        fig = go.Figure(go.Heatmap(
            z=z, x=[f"{d:.0%}" for d in downs], y=[f"${p/1e6:.2f}M" for p in prices],
            colorscale="RdBu", zmid=0,
            colorbar=dict(title=dict(text="Buy − rent ($)", font=dict(size=11)),
                          thickness=12),
            hovertemplate="Price %{y}, down %{x}<br>Advantage: %{z:$,.0f}<extra></extra>",
        ))
        fig.update_layout(height=480, margin=dict(l=70, r=20, t=10, b=40),
                          xaxis_title="Down payment", yaxis_title="Purchase price")
        st.plotly_chart(fig)

    with right:
        if ok.any():
            masked = np.where(ok, z, -np.inf)
            i, j = np.unravel_index(np.argmax(masked), masked.shape)
            best_p, best_d = prices[i], downs[j]
            st.success(
                f"Best cell under constraints: {fmtm(best_p)} at {best_d:.0%} down "
                f"({fmtm(best_p * best_d)}) → {fmtm(z[i, j])} advantage over renting at "
                f"year {horizon}. Reserve after closing {fmtm(reserve[i, j])}; first-year "
                f"net monthly ≈ {fmtm(mout[i, j])}.",
                icon=":material/check_circle:",
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
            with st.container(border=True):
                st.markdown("**Best down payment per price**")
                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    height=390,
                    column_config={
                        "Price": st.column_config.TextColumn(
                            help="Purchase price for this row"),
                        "Best down %": st.column_config.TextColumn(
                            help="Down payment maximizing the buy advantage at this price, "
                                 "under your constraints"),
                        "Down $": st.column_config.TextColumn(
                            help="That down payment in dollars"),
                        "Advantage vs rent": st.column_config.TextColumn(
                            help="Buy minus rent net worth at the horizon, after taxes and "
                                 "selling costs"),
                        "Reserve": st.column_config.TextColumn(
                            help="Liquid cash left after closing"),
                        "Net monthly (yr 1)": st.column_config.TextColumn(
                            help="First-year net monthly owner cost"),
                    },
                )
        else:
            st.warning("No (price, down) combination satisfies your constraints.")

    with left.container(border=True):
        st.markdown("**Slice: advantage vs. down payment at a fixed price**")
        sp = st.select_slider("Price", options=[int(p) for p in prices], value=1_400_000
                              if 1_400_000 in prices else int(prices[len(prices)//2]),
                              format_func=fmt,
                              help="Pick a price to see how the advantage changes with "
                                   "down payment alone.")
        ii = int(np.where(prices == sp)[0][0])
        figs = go.Figure()
        figs.add_trace(go.Scatter(x=downs * 100, y=z[ii], mode="lines+markers"))
        figs.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(compact(figs, height=300, legend=False,
                                xaxis_title="Down payment (%)",
                                yaxis_title=f"Buy − rent, yr {horizon} ($)"))

# ================================================================ tab 3
with tab3:
    st.caption("Month-by-month trace of the Single scenario inputs — one row per period, "
               "like a spreadsheet.")
    gran = st.segmented_control("Granularity", ["Yearly", "Monthly"], default="Yearly",
                                label_visibility="collapsed",
                                help="Yearly sums the flows and shows end-of-year "
                                     "balances; Monthly shows every row.")

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

    COL_HELP = {
        "Month": "Month number; row 0 is closing day (starting balances, no flows).",
        "Year": "Year number; row 0 is closing day (starting balances, no flows).",
        "P&I payment": "Fixed monthly principal & interest on the mortgage.",
        "  of which interest": "Interest portion of the P&I payment (shrinks over time).",
        "  of which principal": "Principal portion of the P&I payment — builds equity.",
        "Property tax": "Tax on the assessed value, which grows 2%/yr under Prop 13.",
        "Insurance": "Homeowners insurance: a share of current market value per year.",
        "Maintenance": "Repairs and upkeep: a share of current market value per year.",
        "HOA": "Flat monthly homeowners-association dues.",
        "PMI": "Mortgage insurance while down < 20%; drops at 78% of purchase price.",
        "Interest tax benefit (−)": "Marginal rate × deductible interest (≤ 750k of "
                                    "balance); reduces the owner's net cost.",
        "Own cost (net)": "P&I + property tax + insurance + maintenance + HOA + PMI − "
                          "interest tax benefit: the owner's true outflow.",
        "Rent": "Rent for the comparable home; grows at the rent-growth rate yearly.",
        "Own − rent": "Cash-flow gap between the two lifestyles; the cheaper side "
                      "invests this difference.",
        "Invested → buy portfolio": "Surplus invested by the owner when owning is "
                                    "cheaper than renting that period.",
        "Invested → rent portfolio": "Surplus invested by the renter when renting is "
                                     "cheaper than owning that period.",
        "Home value": "Market value, compounding at the home-appreciation rate.",
        "Loan balance": "Remaining mortgage principal at the end of the period.",
        "Home equity (if sold)": "Home value × (1 − selling costs) − loan balance.",
        "Portfolio (buy)": "Owner's investments: capital left after closing, "
                           "compounding plus any invested surplus.",
        "Portfolio (buy, after tax if sold)": "Portfolio (buy) minus capital-gains tax "
                                              "on gains above contributed dollars.",
        "Portfolio (rent)": "Renter's investments: all capital compounding plus any "
                            "invested surplus.",
        "Portfolio (rent, after tax if sold)": "Portfolio (rent) minus capital-gains "
                                               "tax on gains above contributed dollars.",
        "Net worth — buy (if sold)": "Portfolio (buy, after tax if sold) + "
                                     "Home equity (if sold).",
        "Net worth — rent (if sold)": "Portfolio (rent, after tax if sold).",
        "Buy advantage": "Buy minus rent net worth, both after-tax 'if sold' — "
                         "the headline number.",
    }

    if gran == "Yearly":
        df_m["Year"] = (df_m["Month"] - 1) // 12 + 1  # month 0 -> year 0 (closing)
        agg = {c: "sum" for c in FLOWS} | {c: "last" for c in STOCKS}
        df = df_m.groupby("Year", as_index=False).agg(agg)
        period_col = "Year"
        st.caption("Row 0 = closing day (starting balances, no flows). Flows summed per "
                   "year; balances at end of year.")
    else:
        df = df_m
        period_col = "Month"

    st.dataframe(
        df,
        column_config={period_col: st.column_config.NumberColumn(
            pinned=True, help=COL_HELP.get(period_col))}
        | {c: st.column_config.NumberColumn(format="$%d", help=COL_HELP.get(c))
           for c in FLOWS + STOCKS},
        hide_index=True,
    )
    st.download_button("Download as CSV", df.to_csv(index=False),
                       "rent_vs_buy_mechanics.csv", "text/csv",
                       help="Download the table above (at the current granularity) "
                            "for your own spreadsheet analysis.")

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

# ================================================================ tab 4
with tab4:
    st.caption("Every figure is produced by a month-by-month simulation of the formulas "
               "below; the worked example evaluates them at your current inputs and "
               "reconciles exactly with the Details table.")

    st.subheader("Formulas")
    f1, f2 = st.columns(2)

    with f1.container(border=True):
        st.markdown("**Monthly mortgage payment (P&I)** — standard annuity")
        st.latex(r"M = L \cdot \frac{r/12}{1 - (1 + r/12)^{-12T}}")
        st.caption("L = loan (price − down payment), r = mortgage rate, T = term in years. "
                   "Each month: interest = balance × r/12; principal = M − interest.")

    with f2.container(border=True):
        st.markdown("**Owner monthly cost, net of tax benefit**")
        st.latex(r"C_{own} = M + tax + ins + maint + HOA + PMI"
                 r" - \tau_{marg} \cdot i_{\le 750k}")
        st.caption("i≤750k = month's interest × min(1, 750,000 ÷ balance). Property tax "
                   "uses the Prop-13 assessed value (+2%/yr); insurance and maintenance "
                   "use current market value; PMI while down < 20% until 78% LTV.")

    with f1.container(border=True):
        st.markdown("**Fairness rule** — both scenarios spend the same total")
        st.latex(r"spend = \max(C_{own},\ rent);\quad"
                 r" invest_{cheaper} = |C_{own} - rent|")
        st.caption("Whichever side has the lower housing outflow invests the difference "
                   "into its portfolio that month, so only the housing/investing split "
                   "differs.")

    with f2.container(border=True):
        st.markdown("**Portfolio growth** — monthly, after annual tax drag")
        st.latex(r"P_m = P_{m-1}\,\big(1 + r_{alt}(1 - \tau_{ann})\big)^{1/12}"
                 r" + contrib_m")
        st.caption("r_alt = investment return (pre-tax), τ_ann = annual tax on returns.")

    with f1.container(border=True):
        st.markdown("**After-tax portfolio if sold today**")
        st.latex(r"P^{AT} = P - \tau_{cg} \cdot \max(0,\ P - contributions)")
        st.caption("Cost basis = all dollars ever contributed; gains above basis are "
                   "taxed at the capital-gains rate. Applied identically to both sides.")

    with f2.container(border=True):
        st.markdown("**Net worth (both on an if-sold, after-tax basis)**")
        st.latex(r"NW_{buy} = P^{AT}_{buy} + H(1 - s) - B \qquad"
                 r" NW_{rent} = P^{AT}_{rent}")
        st.caption("H = home value, s = selling costs, B = loan balance. "
                   "Buy advantage = NW_buy − NW_rent.")

    st.subheader("Worked example at current inputs")
    if not res.feasible:
        st.warning("The single-scenario inputs are infeasible (upfront cash exceeds "
                   "capital), so there is no worked example. Lower the price or down "
                   "payment.")
    else:
        w1, w2, w3 = st.columns(3)

        with w1.container(border=True, height="stretch"):
            st.markdown("**1 · Closing day** (row 0 in Details)")
            st.dataframe(pd.DataFrame([
                ["Investable capital", fmt(capital)],
                [f"− Down payment ({down_pct:.0%} × price)", fmt(down)],
                [f"− Closing costs ({closing_pct:.2%} × price)", fmt(price * closing_pct)],
                ["− One-time costs", fmt(onetime)],
                ["= Buy portfolio, day 0", fmt(res.portfolio_buy[0])],
                ["Rent portfolio, day 0 (= capital)", fmt(res.portfolio_rent[0])],
                ["Home value (= price)", fmt(res.home_value[0])],
                ["Loan balance (= price − down)", fmt(res.loan_balance[0])],
            ], columns=["Item", "Amount"]), hide_index=True)

        with w2.container(border=True, height="stretch"):
            st.markdown("**2 · Month 1 cash flows**")
            gap = res.outflow_buy[1] - res.outflow_rent[1]
            flows_to = ("rent" if res.contrib_rent_m[1] > 0 else "buy")
            st.dataframe(pd.DataFrame([
                ["P&I payment", fmt(res.payment_m[1])],
                ["· of which interest", fmt(res.interest_m[1])],
                ["· of which principal", fmt(res.principal_m[1])],
                ["+ Property tax", fmt(res.prop_tax_m[1])],
                ["+ Insurance", fmt(res.insurance_m[1])],
                ["+ Maintenance", fmt(res.maintenance_m[1])],
                ["+ HOA", fmt(res.hoa_m[1])],
                ["+ PMI", fmt(res.pmi_m[1])],
                ["− Interest tax benefit", fmt(res.tax_benefit_m[1])],
                ["= Own cost (net)", fmt(res.outflow_buy[1])],
                ["Rent", fmt(res.outflow_rent[1])],
                ["Own − rent", f"{'−' if gap < 0 else ''}{fmt(abs(gap))}"],
                [f"→ invested into {flows_to} portfolio",
                 fmt(max(res.contrib_buy_m[1], res.contrib_rent_m[1]))],
            ], columns=["Item", "Amount"]), hide_index=True)

        with w3.container(border=True, height="stretch"):
            st.markdown(f"**3 · Year {horizon}** (last row in Details)")
            adv = res.net_worth_buy_liq[-1] - res.net_worth_rent_liq[-1]
            st.dataframe(pd.DataFrame([
                ["Buy portfolio (after tax if sold)", fmt(res.portfolio_buy_after_tax[-1])],
                [f"+ Home value × (1 − {selling_pct:.0%})",
                 fmt(res.home_value[-1] * (1 - selling_pct))],
                ["− Loan balance", fmt(res.loan_balance[-1])],
                ["= Net worth — buy", fmt(res.net_worth_buy_liq[-1])],
                ["Rent portfolio (after tax if sold)", fmt(res.portfolio_rent_after_tax[-1])],
                ["= Net worth — rent", fmt(res.net_worth_rent_liq[-1])],
                ["Buy advantage", f"{'−' if adv < 0 else ''}{fmt(abs(adv))}"],
            ], columns=["Item", "Amount"]), hide_index=True)

        st.caption("Every value above is read from the same simulation as the charts and "
                   "the Details table (Yearly granularity: rows 0, 1 and the last row).")

    with st.expander("Model assumptions & known simplifications", icon=":material/info:"):
        st.markdown("""
- **Fair comparison:** both scenarios spend the same total each month — whichever has the
  lower housing outflow invests the difference in its portfolio.
- **Investment taxes:** an annual drag on returns (dividends/turnover) plus capital-gains
  tax on unrealized gains, applied in every "if sold" figure for **both** scenarios.
  Cost basis = dollars contributed; gains above basis are taxed at the sale rate.
- **Interest deduction:** combined marginal rate × interest on the deductible share of the
  balance (capped at \\$750k of balance). Assumes you itemize either way.
- **Prop 13:** assessed value (property tax base) grows at 2%/yr regardless of market value.
- **PMI:** charged when down < 20%, drops when the balance falls below 78% of purchase price.
- **Home sale:** "if sold" subtracts selling costs but **not** capital-gains tax on the home
  (§121 excludes the first \\$250k single / \\$500k married of gain; big appreciation beyond
  that is untaxed in this model, which flatters buying slightly).
- All figures are **nominal** dollars.
""")
