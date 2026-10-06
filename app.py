"""Rent vs. Buy tradeoff dashboard.

Run with: streamlit run app.py
"""

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from model import (Assumptions, simulate, rent_from_price, runway,
                   cashflow_breakeven_month)

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
    "marginal": 42.0, "deduct": True, "filing_status": "Single",
    "p2r": 28.0,
    "monthly_income": 0,
    "price": 1_400_000, "down_pct": 50, "derive_rent": True, "rent0": 4_167,
    # scenario explorer tab
    "sweep_x": "price", "sweep_y": "down_pct",
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


# ---------------------------------------------------------------- chart helpers
# Each helper builds a Plotly Figure from simulation results; callers pass a
# unique key= to st.plotly_chart to avoid duplicate-element-ID errors.

def networth_fig(res, yrs, height=340):
    """Net worth over time: buy (if sold & mark-to-market) vs rent."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy_liq, name="Buy (if sold)",
                             line=dict(width=3)))
    fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_buy, name="Buy (mark-to-market)",
                             line=dict(dash="dot")))
    fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq, name="Rent (if sold)",
                             line=dict(width=3)))
    fig.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent, name="Rent (mark-to-market)",
                             line=dict(dash="dot")))
    return compact(fig, height=height, xaxis_title="Years", yaxis_title="$")


def networth_composition_fig(res, yrs, selling_pct):
    """Buy net worth stacked: investments + home equity vs rent line.

    Equity is after selling costs AND home-sale tax, so the bands sum to the
    buy 'if sold' line."""
    equity_liq = [h * (1 - selling_pct) - b - t
                  for h, b, t in zip(res.home_value, res.loan_balance, res.home_sale_tax)]
    figc = go.Figure()
    figc.add_trace(go.Scatter(x=yrs, y=res.portfolio_buy_after_tax,
                              name="Investments (after tax)",
                              stackgroup="buy", line=dict(width=0.5)))
    figc.add_trace(go.Scatter(x=yrs, y=equity_liq,
                              name="Home equity (after selling costs & tax)",
                              stackgroup="buy", line=dict(width=0.5)))
    figc.add_trace(go.Scatter(x=yrs, y=res.net_worth_rent_liq,
                              name="Rent (after tax)",
                              line=dict(dash="dash", color="gray")))
    return compact(figc, xaxis_title="Years", yaxis_title="$")


def monthly_cost_fig(res, yrs, height=340):
    """Stacked monthly owner cost breakdown with rent overlay."""
    fig2 = go.Figure()
    _x = yrs[1:]
    _components = [
        ("Interest",      res.interest_m[1:]),
        ("Principal",     res.principal_m[1:]),
        ("Property tax",  res.prop_tax_m[1:]),
        ("Insurance",     res.insurance_m[1:]),
        ("Maintenance",   res.maintenance_m[1:]),
        ("HOA",           res.hoa_m[1:]),
        ("PMI",           res.pmi_m[1:]),
    ]
    for _name, _series in _components:
        if max(_series) > 0:
            fig2.add_trace(go.Scatter(
                x=_x, y=_series, name=_name,
                stackgroup="own", line=dict(width=0.5),
                hovertemplate="%{y:$,.0f}",
            ))
    fig2.add_trace(go.Scatter(
        x=_x, y=res.outflow_buy[1:], name="Own cost (net of tax benefit & income)",
        line=dict(width=2, color="black"),
        hovertemplate="%{y:$,.0f}",
    ))
    if max(res.income_m[1:]) > 0:
        # Show income as a dashed negative-side line so users can see its effect
        _neg_income = [-v for v in res.income_m[1:]]
        fig2.add_trace(go.Scatter(
            x=_x, y=_neg_income, name="Income (offsets cost)",
            line=dict(width=2, dash="dash", color="green"),
            hovertemplate="Income: %{customdata:$,.0f}",
            customdata=res.income_m[1:],
        ))
    fig2.add_trace(go.Scatter(
        x=_x, y=res.outflow_rent[1:], name="Rent",
        line=dict(width=2, dash="dash", color="gray"),
        hovertemplate="%{y:$,.0f}",
    ))
    return compact(fig2, height=height, xaxis_title="Years", yaxis_title="$/mo")


def sensitivity_fig(a, alt_return, horizon):
    """Buy advantage vs. investment return sensitivity line."""
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
    return compact(fig3, legend=False,
                   xaxis_title="Investment return (pre-tax, %)",
                   yaxis_title=f"Buy − rent, yr {horizon} ($)")


def liquid_portfolio_fig(rwy, fmt_fn, height=340):
    """Liquid portfolio over time for the runway scenario."""
    buy_dep = rwy.depleted_buy_month
    rent_dep = rwy.depleted_rent_month
    later_dep = max(
        buy_dep if buy_dep is not None else 0,
        rent_dep if rent_dep is not None else 0,
    )
    if buy_dep is None and rent_dep is None:
        cutoff_m = 40 * 12
    else:
        cutoff_m = min(later_dep + 3 * 12, len(rwy.months) - 1)

    plot_months = [m for m in rwy.months if m <= cutoff_m]
    plot_yrs = [m / 12 for m in plot_months]
    plot_buy = rwy.liquid_buy[:len(plot_months)]
    plot_rent = rwy.liquid_rent[:len(plot_months)]

    fig_rwy = go.Figure()
    fig_rwy.add_trace(go.Scatter(
        x=plot_yrs, y=plot_buy, name="Buy portfolio",
        line=dict(width=3),
        hovertemplate="Year %{x:.1f}<br>Buy portfolio: %{y:$,.0f}<extra></extra>",
    ))
    fig_rwy.add_trace(go.Scatter(
        x=plot_yrs, y=plot_rent, name="Rent portfolio",
        line=dict(width=3, dash="dash"),
        hovertemplate="Year %{x:.1f}<br>Rent portfolio: %{y:$,.0f}<extra></extra>",
    ))

    if rwy.sale_month is not None and rwy.sale_month <= cutoff_m:
        sale_idx = rwy.sale_month
        sale_portfolio_val = rwy.liquid_buy[sale_idx] if sale_idx < len(rwy.liquid_buy) else 0
        fig_rwy.add_trace(go.Scatter(
            x=[rwy.sale_month / 12], y=[sale_portfolio_val],
            mode="markers+text",
            marker=dict(size=12, symbol="diamond", color="orange"),
            text=[f"sold house<br>{fmt_fn(rwy.sale_proceeds)}"],
            textposition="top center",
            showlegend=False,
            hovertemplate=f"Yr {{x:.1f}}: house sold, proceeds {fmt_fn(rwy.sale_proceeds)}<extra></extra>",
        ))

    if buy_dep is not None and buy_dep <= cutoff_m:
        fig_rwy.add_trace(go.Scatter(
            x=[buy_dep / 12], y=[0],
            mode="markers+text",
            marker=dict(size=10, symbol="x", color="blue"),
            text=[f"Buy depleted<br>yr {buy_dep / 12:.1f}"],
            textposition="top center",
            showlegend=False,
            hoverinfo="skip",
        ))
    if rent_dep is not None and rent_dep <= cutoff_m:
        fig_rwy.add_trace(go.Scatter(
            x=[rent_dep / 12], y=[0],
            mode="markers+text",
            marker=dict(size=10, symbol="x", color="red"),
            text=[f"Rent depleted<br>yr {rent_dep / 12:.1f}"],
            textposition="top center",
            showlegend=False,
            hoverinfo="skip",
        ))

    return compact(fig_rwy, height=height, xaxis_title="Years", yaxis_title="$"), cutoff_m


def runway_sweep_fig(sweep_data, rent_runway_months, height=320):
    """Runway vs down-payment sweep chart. Returns (fig, peak_down, peak_yrs) or None."""
    valid = [(d, y) for d, y in sweep_data if y is not None]
    if not valid:
        return None, None, None
    sweep_x = [d for d, _ in valid]
    sweep_y = [y for _, y in valid]

    fig_sweep = go.Figure()
    fig_sweep.add_trace(go.Scatter(
        x=sweep_x, y=sweep_y, mode="lines+markers",
        line=dict(width=2),
        hovertemplate="Down %{x:.0f}%<br>Buy runway: %{y:.1f} yrs<extra></extra>",
        name="Buy runway",
    ))
    fig_sweep.add_hline(y=rent_runway_months / 12
                        if rent_runway_months is not None else 100.0,
                        line_dash="dash", line_color="gray",
                        annotation_text="Rent runway",
                        annotation_position="right")

    peak_idx = int(max(range(len(sweep_y)), key=lambda i: sweep_y[i]))
    peak_down = sweep_x[peak_idx]
    peak_yrs = sweep_y[peak_idx]
    fig_sweep.add_trace(go.Scatter(
        x=[peak_down], y=[peak_yrs],
        mode="markers",
        marker=dict(size=12, symbol="star", color="gold"),
        name=f"Peak: {peak_down:.0f}% down → {peak_yrs:.1f} yrs",
        hovertemplate=f"Peak runway: {peak_yrs:.1f} yrs at {peak_down:.0f}% down<extra></extra>",
    ))

    return compact(fig_sweep, height=height,
                   xaxis_title="Down payment (%)",
                   yaxis_title="Buy runway (years)"), peak_down, peak_yrs


@st.cache_data(show_spinner="Computing down-payment optimization curves...")
def _down_pct_sweep(base_a: Assumptions, price_v: float, rent_v: float):
    """Sweep down payment 0–100% in 5% steps at the current price.

    Returns three parallel lists (one entry per feasible down %):
      wealth_curve  : list of (down_pct_int, breakeven_yr | None)
      cashflow_curve: list of (down_pct_int, gross_cashflow_breakeven_yr | None)
      runway_curve  : list of (down_pct_int, buy_runway_yr | None)

    None means 'never within horizon' / infeasible.
    """
    wealth_curve = []
    cashflow_curve = []
    runway_curve = []

    for d_int in range(0, 101, 5):
        d = d_int / 100
        upfront_d = price_v * d + price_v * base_a.closing_buy_pct + base_a.other_onetime_costs
        if upfront_d > base_a.capital:
            # infeasible — skip (gap in the chart)
            continue

        a_d = replace(base_a, price=price_v, down_pct=d, monthly_rent=rent_v)

        # simulate() — wealth breakeven + gross cash-flow breakeven
        r = simulate(a_d)
        # wealth breakeven
        be_yr = r.breakeven_month / 12 if r.breakeven_month > 0 else None
        wealth_curve.append((d_int, be_yr))

        # gross cash-flow breakeven (gross own cost ≤ rent from here on)
        cf_be_month = cashflow_breakeven_month(r)
        cf_be_yr = cf_be_month / 12 if cf_be_month > 0 else None
        cashflow_curve.append((d_int, cf_be_yr))

        # runway() — buy runway
        rr = runway(a_d)
        buy_yrs = (rr.depleted_buy_month / 12
                   if rr.depleted_buy_month is not None else 100.0)
        runway_curve.append((d_int, min(buy_yrs, 100.0)))

    return wealth_curve, cashflow_curve, runway_curve


def _down_sweep_line_fig(curve, yaxis_title, hover_label, height=240, best="min"):
    """Compact line+marker chart for a single down-payment optimization curve.

    curve: list of (down_pct_int, value | None)
    Gaps (None values) are excluded; a connected line is drawn through valid points.
    best: "min" (earlier breakeven is better) or "max" — the optimum gets a gold star.
    """
    xs = [d for d, v in curve if v is not None]
    ys = [v for d, v in curve if v is not None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        line=dict(width=2),
        marker=dict(size=6),
        showlegend=False,
        hovertemplate=f"Down %{{x:.0f}}%<br>{hover_label}: %{{y:.1f}} yrs<extra></extra>",
    ))
    if xs:
        i = ys.index(min(ys) if best == "min" else max(ys))
        fig.add_trace(go.Scatter(
            x=[xs[i]], y=[ys[i]], mode="markers",
            marker=dict(size=12, symbol="star", color="gold"),
            name=f"Best: {xs[i]:.0f}% down → {ys[i]:.1f} yrs",
            hovertemplate=(f"Best {hover_label.lower()}: {ys[i]:.1f} yrs "
                           f"at {xs[i]:.0f}% down<extra></extra>"),
        ))
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=20, t=30, b=30),
        hovermode="x unified",
        showlegend=bool(xs),
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="left", x=0, font=dict(size=10)),
        xaxis_title="Down payment (%)",
        yaxis_title=yaxis_title,
    )
    return fig


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Assumptions")

# ---- Section 0: Investment --------------------------------------
st.sidebar.subheader("Investment")
capital = st.sidebar.number_input("Investable capital ($)", 100_000, 10_000_000,
                                  step=50_000, key="capital",
                                  help="Total cash you're deploying. Buy: pays down payment "
                                       "+ closing + one-time costs, remainder is invested. "
                                       "Rent: all of it is invested.")
alt_return = st.sidebar.slider(
    "Investment return (%, pre-tax)", 0.0, 12.0,
    step=0.25, key="alt_return",
    help="Default (3.5%) represents a high-yield-savings-style safe return. "
         "If you plan to hold equities, raise this — historically stocks have "
         "returned ~7–10% nominal before tax.",
) / 100

# ---- Section 1: The property ------------------------------------
st.sidebar.subheader("The property")
price = st.sidebar.number_input("Purchase price ($)", 200_000, 5_000_000,
                                step=25_000, key="price",
                                help="Contract price of the home. Drives the loan size, "
                                     "property tax, and the comparable rent.")
onetime = st.sidebar.slider("One-time costs ($)", 0, 100_000,
                            step=5_000, key="onetime",
                            help="Movers, immediate repairs, furniture — cash spent once "
                                 "at move-in, gone from the buy-side portfolio.")
hoa = st.sidebar.number_input("HOA ($/mo)", 0, 3_000, step=50, key="hoa",
                              help="Monthly homeowners-association dues, if any. Flat — "
                                   "does not grow in this model.")
monthly_income = st.sidebar.number_input(
    "Monthly income ($)", 0, 20_000, step=100, key="monthly_income",
    help="Income the property generates for you as the owner — e.g. ADU or room rent. "
         "Buy-side only, grows with rent growth, stops at a forced sale. "
         "Enter net of taxes.",
)
derive_rent = st.sidebar.checkbox("Derive rent from price-to-rent ratio", key="derive_rent",
                                  help="On: rent for the comparable home = price ÷ ratio ÷ 12, "
                                       "so it tracks the purchase price. Off: type a rent "
                                       "you've actually seen on the market.")
if derive_rent:
    rent0 = rent_from_price(price, st.session_state["p2r"])
else:
    rent0 = st.sidebar.number_input("Monthly rent ($)", 500, 30_000, step=100, key="rent0",
                                    help="Starting monthly rent for the comparable home; grows "
                                         "at the rent-growth rate each year.")
st.sidebar.caption(f"Comparable rent: {fmtm(rent0)}/mo")

# ---- Section 2: Financing ---------------------------------------
st.sidebar.subheader("Financing")
down_pct = st.sidebar.slider("Down payment (%)", 3, 100, step=1, key="down_pct",
                             help="Share of the price paid in cash at closing; the rest "
                                  "is the mortgage. Below 20% adds PMI until you reach "
                                  "22% equity.") / 100
st.sidebar.caption(f"Down payment: {fmtm(price * down_pct)}")
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

# ---- Section 3: The market --------------------------------------
st.sidebar.subheader("The market")
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

# ---- Section 4: Personal ----------------------------------------
st.sidebar.subheader("Personal")
horizon = st.sidebar.slider("Horizon (years)", 1, 30, key="horizon",
                            help="When the two scenarios are compared: both are valued "
                                 "'if sold' at this point.")
filing_status = st.sidebar.segmented_control(
    "Filing status", ["Single", "Married"], key="filing_status",
    help="Sets the §121 home-sale exclusion: the first \\$250k (single) / \\$500k "
         "(married filing jointly) of gain on your home is tax-free once you've owned "
         "and lived in it for 2 years. Gain above that is taxed at the capital-gains "
         "rate in every 'if sold' figure.") or DEFAULTS["filing_status"]
home_gain_exclusion = 500_000 if filing_status == "Married" else 250_000
marginal = st.sidebar.slider("Marginal tax rate (%)", 0.0, 55.0,
                             step=1.0, key="marginal",
                             help="Federal + California rate on your last dollar of income; "
                                  "sets the value of the mortgage-interest deduction. Should "
                                  "match your filing status: ~42% around \\$300k single in CA, "
                                  "~33% around \\$300k married filing jointly.") / 100
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
                              help="Applied in all 'if sold' figures to unrealized portfolio "
                                   "gains (value − contributions) in both scenarios, and to the "
                                   "home's gain above the §121 exclusion in the buy scenario.") / 100

base = Assumptions(
    capital=capital, horizon_years=horizon,
    alt_return_annual=alt_return, investment_tax_drag=inv_tax, cap_gains_rate=cap_gains,
    home_gain_exclusion=home_gain_exclusion,
    mortgage_rate=mort_rate, term_years=term,
    closing_buy_pct=closing_pct, other_onetime_costs=onetime, selling_cost_pct=selling_pct,
    home_appreciation=home_appr, property_tax_rate=prop_tax,
    insurance_rate=insurance, maintenance_rate=maintenance, hoa_monthly=hoa,
    marginal_tax_rate=marginal, include_interest_deduction=deduct,
    rent_growth=rent_growth,
    monthly_income=monthly_income,
)

# ---------------------------------------------------------------- shared scenario
# The sidebar scenario, simulated once at module scope; every tab reads these.
a = replace(base, price=price, down_pct=down_pct, monthly_rent=rent0)
res = simulate(a)
rwy = runway(a)
down = price * down_pct
upfront = down + price * closing_pct + onetime

_yrs = np.array(res.months) / 12
MCH = 115   # uniform metric-card height (Overview and Charts tabs)
_tax_benefit_m1 = res.tax_benefit_m[1]
_principal_m1 = res.principal_m[1]
_burn_buy_m1 = rwy.monthly_need_buy[1] if len(rwy.monthly_need_buy) > 1 else 0.0
_burn_rent_m1 = rwy.monthly_need_rent[1] if len(rwy.monthly_need_rent) > 1 else 0.0


def _runway_label(depleted_month, max_years=100):
    if depleted_month is None:
        return f"{max_years}+ yrs"
    return f"{depleted_month / 12:.1f} yrs"


# ---------------------------------------------------------------- main
st.subheader("Rent vs. Buy")

tab_overview, tab_explorer, tab_calc, tab_charts = st.tabs(
    ["Overview", "Scenario Explorer", "Calculations", "Charts"])

# ================================================================ Overview
with tab_overview:
    if not res.feasible:
        st.error(f"Infeasible: upfront cash needed ({fmtm(upfront)}) "
                 f"exceeds capital ({fmtm(capital)}).")
    else:
        # ---- Hero grid: 3-category summary (Wealth / Cash flow / Retirement) ----
        # --- Metric 1: Buy advantage ---
        _nw_buy = res.net_worth_buy_liq[-1]
        _nw_rent = res.net_worth_rent_liq[-1]
        _delta = _nw_buy - _nw_rent

        # --- Metric 2: Net worth breakeven ---
        if res.breakeven_month > 0:
            _be_label = f"year {res.breakeven_month / 12:.1f}"
        else:
            _be_label = "never (in horizon)"

        # --- Metric 3: Monthly cost vs rent (mo 1) — GROSS (before interest deduction) ---
        _cost_diff = (res.outflow_buy[1] + res.tax_benefit_m[1]) - res.outflow_rent[1]

        # --- Metric 4: Monthly cost breakeven — GROSS ---
        _cash_be_month = cashflow_breakeven_month(res)
        if _cash_be_month < 0:
            _cash_be_label = "never (in horizon)"
        elif _cash_be_month == 1:
            _cash_be_label = "immediately"
        else:
            _cash_be_label = f"year {_cash_be_month / 12:.1f}"

        # --- Metric 5: Forced sale ---
        _sale_label = f"yr {rwy.sale_month / 12:.1f}" if rwy.sale_month is not None else "never"

        # --- Metric 6: Buy runway advantage ---
        _CAP = 1200  # 100-year cap in months
        _buy_runway_m = rwy.depleted_buy_month if rwy.depleted_buy_month is not None else _CAP
        _rent_runway_m = rwy.depleted_rent_month if rwy.depleted_rent_month is not None else _CAP
        _runway_adv_yrs = (_buy_runway_m - _rent_runway_m) / 12
        _both_sustainable = (rwy.depleted_buy_month is None and rwy.depleted_rent_month is None)
        if _both_sustainable:
            _runway_adv_label = "—"
            _runway_adv_delta = "both sustainable"
            _runway_adv_delta_color = "off"
        else:
            _runway_adv_label = f"{_runway_adv_yrs:+.1f} yrs"
            _runway_adv_delta = "buy lasts longer" if _runway_adv_yrs > 0 else "rent lasts longer"
            _runway_adv_delta_color = "normal" if _runway_adv_yrs > 0 else "inverse"

        # ================================================================ Overview — unified single-screen columns
        _W_CHART_H = 380   # Wealth chart height
        _CF_CHART_H = 380  # Cash flow chart height
        _RT_CHART_H = 380  # Retirement chart height
        _OPT_H = 240       # optimization sub-chart height

        # Down-payment sweep for per-category optimization charts
        _dp_wealth_curve, _dp_cashflow_curve, _dp_runway_curve = _down_pct_sweep(base, price, rent0)

        # Cash flow derived values
        _own_cost_m1_gross = res.outflow_buy[1] + res.tax_benefit_m[1]  # gross: add back the deduction
        _rent_m1 = res.outflow_rent[1]

        # Retirement derived values
        _buy_label = _runway_label(rwy.depleted_buy_month)
        _rent_label = _runway_label(rwy.depleted_rent_month)

        ov_col_w, ov_col_cf, ov_col_rt = st.columns(3, gap="medium")

        # ---- Wealth column ----
        with ov_col_w:
            st.markdown("**Wealth**")
            st.caption("Where does my net worth end up?")
            # Hero pair
            _w_h1, _w_h2 = st.columns(2, gap="small")
            _w_h1.metric("Buy advantage", fmt(_delta),
                         delta=f"{_delta / _nw_rent * 100:+.1f}% vs rent",
                         border=True, height=MCH,
                         help="Liquid net worth difference at the horizon (buy minus rent), "
                              "after taxes and selling costs. Positive = buying wins.")
            _w_h2.metric("Net worth breakeven", _be_label, border=True, height=MCH,
                         help="First month from which buy net worth (after selling costs "
                              "and taxes) is at or above rent net worth and stays ahead "
                              "through the horizon. 'never' = buying is behind at the "
                              "horizon, even if it was briefly ahead earlier.")
            # Supplementary row (1×2)
            _w_r1c1, _w_r1c2 = st.columns(2, gap="small")
            _w_r1c1.metric(f"Buy net worth (yr {horizon})", fmt(_nw_buy), border=True, height=MCH,
                           help="After-tax portfolio + home value net of selling costs − loan balance "
                                "− home-sale capital-gains tax (gain above the §121 exclusion)")
            _w_r1c2.metric(f"Rent net worth (yr {horizon})", fmt(_nw_rent), border=True, height=MCH,
                           help="Portfolio net of capital-gains tax if sold")
            with st.container(border=True):
                st.markdown("**Net worth over time**")
                st.plotly_chart(networth_fig(res, _yrs, height=_W_CHART_H), key="ov_networth")
                with st.expander("About this chart"):
                    st.markdown("Solid = if sold today (after selling costs, home-sale tax "
                                "and portfolio cap-gains tax); dotted = mark-to-market "
                                "(untaxed, no selling costs).")
            with st.container(border=True):
                st.markdown("**Net worth breakeven vs. down payment**")
                _w_opt_fig = _down_sweep_line_fig(
                    _dp_wealth_curve, "Breakeven (yrs)", "Breakeven", height=_OPT_H)
                st.plotly_chart(_w_opt_fig, key="ov_wealth_dp_sweep")
                with st.expander("About this chart"):
                    st.markdown(
                        "Year from which buy net worth (after selling costs and taxes) "
                        "stays at or above rent net worth through the horizon, as a "
                        "function of down payment at the current price. Gaps = infeasible "
                        "(upfront cash exceeds capital) or buying behind at the horizon. "
                        "Read the current sidebar down payment off the x-axis to compare "
                        "with the breakeven card above."
                    )

        # ---- Cash flow column ----
        with ov_col_cf:
            st.markdown("**Cash flow**")
            st.caption("What does each month cost me?")
            # Hero pair
            _cf_h1, _cf_h2 = st.columns(2, gap="small")
            _cf_h1.metric("Monthly cost vs rent (mo 1)", fmt(_cost_diff),
                          delta="buy costs more/mo" if _cost_diff > 0 else "buy costs less/mo",
                          delta_color="off", border=True, height=MCH,
                          help="Gross owner cost minus rent in month 1 — cash actually out the door. "
                               "The interest deduction arrives at tax filing and is counted in net worth, "
                               "not netted into this monthly figure.")
            _cf_h2.metric("Monthly cost breakeven", _cash_be_label, border=True, height=MCH,
                          help="First month from which the gross owner cost (before the interest "
                               "deduction) stays at or below rent through the horizon — i.e., when "
                               "owning becomes and stays cheaper month-to-month "
                               "on a cash-out-the-door basis. The deduction arrives annually at "
                               "tax time and is counted in net worth, not subtracted here.")
            # Supplementary row (1×2)
            _cf_r1c1, _cf_r1c2 = st.columns(2, gap="small")
            _cf_r1c1.metric("Own cost (mo 1)", fmt(_own_cost_m1_gross), border=True, height=MCH,
                            help="P&I + property tax + insurance + maintenance + HOA + PMI, "
                                 "before the interest deduction (which arrives annually at tax "
                                 "time and is counted in net worth). When monthly income is set, "
                                 "it is already netted into the 'Own cost (net)' line and flows "
                                 "through all charts and the net worth calculation.")
            _cf_r1c2.metric("Rent (mo 1)", fmt(_rent_m1), border=True, height=MCH,
                            help="Month-1 rent for the comparable home. Grows at the rent-growth "
                                 "rate each year.")
            with st.container(border=True):
                st.markdown("**Monthly owner cost breakdown**")
                st.plotly_chart(monthly_cost_fig(res, _yrs, height=_CF_CHART_H), key="ov_monthly_cost")
                with st.expander("About this chart"):
                    st.markdown("Bands stack to gross cost; the net line subtracts the "
                                "interest deduction. Principal builds equity — cash out, "
                                "but not lost.")
            with st.container(border=True):
                st.markdown("**Monthly cost breakeven vs. down payment**")
                _cf_opt_fig = _down_sweep_line_fig(
                    _dp_cashflow_curve, "Breakeven (yrs)", "Cash-flow breakeven", height=_OPT_H)
                st.plotly_chart(_cf_opt_fig, key="ov_cashflow_dp_sweep")
                with st.expander("About this chart"):
                    st.markdown(
                        "Year from which the gross owner cost (before the interest deduction) "
                        "stays at or below rent through the horizon, as a function of down "
                        "payment at the "
                        "current price. A larger down payment means a smaller mortgage, so "
                        "the gross cost breakeven typically comes sooner. "
                        "Gaps = infeasible (upfront cash exceeds capital)."
                    )

        # ---- Retirement column ----
        with ov_col_rt:
            st.markdown("**Retirement**")
            st.caption("How long could I survive with no income?")
            # Hero pair
            _rt_h1, _rt_h2 = st.columns(2, gap="small")
            _rt_h1.metric("Forced sale", _sale_label, border=True, height=MCH,
                          help="Year the owner's liquid portfolio runs dry and the house must "
                               "be sold; the proceeds (after selling costs, loan payoff and "
                               "home-sale tax) then fund renting. 'never' means the portfolio "
                               "sustains ownership costs indefinitely (no income, housing "
                               "costs drawn from portfolio).")
            _rt_h2.metric("Buy runway advantage", _runway_adv_label,
                          delta=_runway_adv_delta, delta_color=_runway_adv_delta_color,
                          border=True, height=MCH,
                          help="Total buy runway minus rent runway, in years. "
                               "A positive value means buying survives longer in retirement. "
                               "Neither-depleted scenarios are treated as the 100-year cap "
                               "(1,200 months) for this arithmetic — if both are sustainable "
                               "the card shows '—'.")
            # Supplementary row (1×2)
            _rt_r1c1, _rt_r1c2 = st.columns(2, gap="small")
            _rt_r1c1.metric("Total buy runway", _buy_label, border=True, height=MCH,
                            help="How long the buy scenario's combined portfolio lasts — first as an "
                                 "owner, then (after the forced sale) as a renter at then-current market "
                                 "rent. '100+ yrs' = sustainable over the full simulation horizon.")
            _rt_r1c2.metric("Rent runway", _rent_label, border=True, height=MCH,
                            help="How long the renter's portfolio (all investable capital) lasts paying "
                                 "rent. '100+ yrs' = sustainable withdrawal rate over 100 years.")
            _fig_rwy, _cutoff_m = liquid_portfolio_fig(rwy, fmt, height=_RT_CHART_H)
            with st.container(border=True):
                st.markdown("**Liquid portfolio over time**")
                st.plotly_chart(_fig_rwy, key="ov_liquid_portfolio")
                _sale_note_ov = (
                    f" Orange diamond: forced sale at yr {rwy.sale_month / 12:.1f} — "
                    f"after-tax proceeds ({fmtm(rwy.sale_proceeds)}) injected, owner becomes renter."
                    if rwy.sale_month is not None else ""
                )
                with st.expander("About this chart"):
                    st.markdown(
                        "Each portfolio is drawn down by its own housing costs with no "
                        "income. Growth continues until the portfolio hits zero. "
                        "Buy starts with less cash (down payment + closing already spent) "
                        "but may have lower ongoing costs depending on loan size."
                        + _sale_note_ov
                    )
            with st.container(border=True):
                st.markdown("**Runway vs. down payment**")
                _rt_opt_fig, _rt_opt_peak_down, _rt_opt_peak_yrs = runway_sweep_fig(
                    _dp_runway_curve, rwy.depleted_rent_month, height=_OPT_H)
                if _rt_opt_fig is not None:
                    st.plotly_chart(_rt_opt_fig, key="ov_runway_sweep")
                    with st.expander("About this chart"):
                        st.markdown(
                            "Total buy runway (owner phase + post-sale renter phase) at each "
                            "down payment level. Peak buy runway at "
                            f"{_rt_opt_peak_down:.0f}% down → {_rt_opt_peak_yrs:.1f} yrs. "
                            "Dashed line = rent runway. Gaps = infeasible (upfront > capital). "
                            "Capped at 100 yrs."
                        )
                else:
                    st.info("No feasible down payments at the current price and capital.")

# ================================================================ Calculations
with tab_calc:
    st.caption("Every figure is produced by a month-by-month simulation; the formulas, "
               "worked examples, and raw data below all reconcile with each other.")

    # ---- Section 1: Formulas ----
    st.subheader("Formulas")
    f1, f2 = st.columns(2)

    with f1.container(border=True):
        st.markdown("**Monthly mortgage payment (P&I)** — standard annuity")
        st.latex(r"M = L \cdot \frac{r/12}{1 - (1 + r/12)^{-12T}}")
        st.caption("L = loan (price − down payment), r = mortgage rate, T = term in years. "
                   "Each month: interest = balance × r/12; principal = M − interest.")

    with f2.container(border=True):
        st.markdown("**Owner monthly cost, net of tax benefit and income**")
        st.latex(r"C_{own} = M + tax + ins + maint + HOA + PMI"
                 r" - \tau_{marg} \cdot i_{\le 750k} - income")
        st.caption("i≤750k = month's interest × min(1, 750,000 ÷ balance). Property tax "
                   "uses the Prop-13 assessed value (+2%/yr); insurance and maintenance "
                   "use current market value; PMI while down < 20% until 78% LTV. "
                   "Income (e.g. ADU rent) offsets the owner's outflow; grows with rent "
                   "growth; enter net of taxes.")

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
                   "taxed at the capital-gains rate. Applied identically to both "
                   "portfolios.")

    with f2.container(border=True):
        st.markdown("**Net worth (both on an if-sold, after-tax basis)**")
        st.latex(r"NW_{buy} = P^{AT}_{buy} + H(1 - s) - B - T_{home} \qquad"
                 r" NW_{rent} = P^{AT}_{rent}")
        st.latex(r"T_{home} = \tau_{cg} \cdot \max\big(0,\ H(1 - s) - basis - X_{121}\big)")
        st.caption("H = home value, s = selling costs, B = loan balance. Home basis = "
                   "price + closing costs. X₁₂₁ = §121 exclusion (\\$250k single / "
                   "\\$500k married), only after 24 months of ownership; 0 before. "
                   "Buy advantage = NW_buy − NW_rent.")

    # ---- Section 2: Worked example ----
    st.subheader("Worked example at current inputs")
    if not res.feasible:
        st.warning("The sidebar inputs are infeasible (upfront cash exceeds "
                   "capital), so there is no worked example. Lower the price or down "
                   "payment.")
    else:
        w1, w2, w3 = st.columns(3)

        with w1.container(border=True, height="stretch"):
            st.markdown("**1 · Closing day** (row 0 in the month-by-month trace)")
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
                ["− Income", fmt(res.income_m[1])],
                ["= Own cost (net)", fmt(res.outflow_buy[1])],
                ["Rent", fmt(res.outflow_rent[1])],
                ["Own − rent", f"{'−' if gap < 0 else ''}{fmt(abs(gap))}"],
                [f"→ invested into {flows_to} portfolio",
                 fmt(max(res.contrib_buy_m[1], res.contrib_rent_m[1]))],
            ], columns=["Item", "Amount"]), hide_index=True)

        with w3.container(border=True, height="stretch"):
            st.markdown(f"**3 · Year {horizon}** (last row in the month-by-month trace)")
            adv = res.net_worth_buy_liq[-1] - res.net_worth_rent_liq[-1]
            st.dataframe(pd.DataFrame([
                ["Buy portfolio (after tax if sold)", fmt(res.portfolio_buy_after_tax[-1])],
                [f"+ Home value × (1 − {selling_pct:.0%})",
                 fmt(res.home_value[-1] * (1 - selling_pct))],
                ["− Loan balance", fmt(res.loan_balance[-1])],
                ["− Home sale tax", fmt(res.home_sale_tax[-1])],
                ["= Net worth — buy", fmt(res.net_worth_buy_liq[-1])],
                ["Rent portfolio (after tax if sold)", fmt(res.portfolio_rent_after_tax[-1])],
                ["= Net worth — rent", fmt(res.net_worth_rent_liq[-1])],
                ["Buy advantage", f"{'−' if adv < 0 else ''}{fmt(abs(adv))}"],
            ], columns=["Item", "Amount"]), hide_index=True)

        st.caption("Every value above is read from the same simulation as the charts and "
                   "the month-by-month trace (Yearly granularity: rows 0, 1 and the last row).")

    # ---- Section 3: Month-by-month trace ----
    st.subheader("Month-by-month trace")
    st.caption("One row per period, like a spreadsheet — the raw data behind every chart.")
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
        "Income (−)": res.income_m,
        "Own cost (net)": res.outflow_buy,
        # --- the rent alternative
        "Rent": res.outflow_rent,
        "Own − rent": [b - r for b, r in zip(res.outflow_buy, res.outflow_rent)],
        "Invested → buy portfolio": res.contrib_buy_m,
        "Invested → rent portfolio": res.contrib_rent_m,
        # --- balances (end of period)
        "Home value": res.home_value,
        "Loan balance": res.loan_balance,
        "Home sale tax (if sold)": res.home_sale_tax,
        "Home equity (if sold)": [h * (1 - selling_pct) - b - t for h, b, t in
                                  zip(res.home_value, res.loan_balance,
                                      res.home_sale_tax)],
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
             "Income (−)",
             "Own cost (net)", "Rent", "Own − rent",
             "Invested → buy portfolio", "Invested → rent portfolio"]
    STOCKS = ["Home value", "Loan balance", "Home sale tax (if sold)",
              "Home equity (if sold)",
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
        "Income (−)": "Property income (e.g. ADU rent) received by the owner — buy side "
                      "only. Grows with rent growth annually. Stops at a forced sale. "
                      "Enter net of taxes.",
        "Own cost (net)": "P&I + property tax + insurance + maintenance + HOA + PMI − "
                          "interest tax benefit − income: the owner's true outflow.",
        "Rent": "Rent for the comparable home; grows at the rent-growth rate yearly.",
        "Own − rent": "Cash-flow gap between the two lifestyles; the cheaper side "
                      "invests this difference.",
        "Invested → buy portfolio": "Surplus invested by the owner when owning is "
                                    "cheaper than renting that period.",
        "Invested → rent portfolio": "Surplus invested by the renter when renting is "
                                     "cheaper than owning that period.",
        "Home value": "Market value, compounding at the home-appreciation rate.",
        "Loan balance": "Remaining mortgage principal at the end of the period.",
        "Home sale tax (if sold)": "Capital-gains rate × max(0, home value × (1 − selling "
                                   "costs) − (price + closing costs) − §121 exclusion). "
                                   "No exclusion before 24 months of ownership.",
        "Home equity (if sold)": "Home value × (1 − selling costs) − loan balance − "
                                 "home sale tax.",
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
  tax benefit − income. This is the owner's true monthly outflow.
- **Own − rent** is the cash-flow gap between the two lifestyles. Whichever side is cheaper
  invests that gap: positive → **Invested → rent portfolio** (renting is cheaper that month),
  negative → **Invested → buy portfolio**. Both scenarios spend identical total dollars.
- **Portfolio (buy)** starts at capital − down payment − closing costs and compounds at the
  investment return (net of annual drag), plus any invested surplus.
- **… after tax if sold** = portfolio − capital-gains tax on embedded gains (value minus
  contributed dollars). Applied identically to both portfolios.
- **Home sale tax (if sold)** = capital-gains rate × the home's gain above the §121
  exclusion. Gain = home value × (1 − selling costs) − (price + closing costs). The
  exclusion (\\$250k single / \\$500k married) applies only after 24 months of ownership.
- **Home equity (if sold)** = home value × (1 − selling costs) − loan balance − home sale
  tax: the property side of the buy scenario.
- **Net worth — buy (if sold)** = Portfolio (buy, after tax if sold) + Home equity (if sold).
  The two components are shown separately so you can see how much of the buy net worth is
  liquid investments vs. locked in the property.
- **Buy advantage** is the headline number: buy minus rent net worth, both on an
  after-tax "if sold" basis.
""")

    # ---- Model assumptions (bottom of tab) ----
    with st.expander("Model assumptions & known simplifications", icon=":material/info:"):
        st.markdown("""
- **Fair comparison:** both scenarios spend the same total each month — whichever has the
  lower housing outflow invests the difference in its portfolio.
- **Investment taxes:** an annual drag on returns (dividends/turnover) plus capital-gains
  tax on unrealized portfolio gains, applied in every "if sold" figure for **both**
  scenarios' portfolios.
  Cost basis = dollars contributed; gains above basis are taxed at the sale rate.
- **Interest deduction:** combined marginal rate × interest on the deductible share of the
  balance (capped at \\$750k of balance). Assumes you itemize either way.
- **Prop 13:** assessed value (property tax base) grows at 2%/yr regardless of market value.
- **PMI:** charged when down < 20%, drops when the balance falls below 78% of purchase price.
- **Home sale:** "if sold" subtracts selling costs **and** capital-gains tax on the home.
  Basis = price + closing costs (one-time/moving costs are not basis); gain = value ×
  (1 − selling costs) − basis. The §121 exclusion (\\$250k single / \\$500k married, set
  by filing status) applies only once the home has been owned for 24 months — before that
  the whole gain is taxed (partial/hardship exclusions are ignored). Gain above the
  exclusion is taxed at the capital-gains rate. Mark-to-market net worth is untaxed. The
  retirement forced sale uses the same rule.
- **Monthly income:** Buy-side only (e.g. ADU or room rent). Grows with the rent-growth
  rate each year. Stops at a forced sale (the ADU sells with the house). Enter net of
  taxes — tax on rental income is not modeled here.
- All figures are **nominal** dollars.
""")

# ================================================================ Scenario Explorer
# ---- registries: sweepable inputs and output metrics -------------


def _mdsafe(s: str) -> str:
    """Escape every $ so Streamlit markdown never pairs them up as LaTeX math."""
    return s.replace("$", "\\$")


def _lin_axis(lo, hi, n=13):
    """~n evenly spaced values over a bounded (slider-range) axis, rounded for labels."""
    return tuple(dict.fromkeys(round(float(v), 2) for v in np.linspace(lo, hi, n)))


def _int_axis(lo, hi, n=13):
    """~n integer values over a bounded axis (deduplicated after rounding)."""
    return tuple(dict.fromkeys(int(round(v)) for v in np.linspace(lo, hi, n)))


def _dollar_axis(floor_v, sane_max, current, n=13):
    """Open-ended dollar axis: floor .. max(sane_max, 2 × current sidebar value),
    in nice rounded steps (the exact cap is appended so the axis always reaches it)."""
    cap = max(sane_max, 2 * current)
    raw = (cap - floor_v) / (n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    vals = [float(floor_v + i * step) for i in range(n) if floor_v + i * step <= cap]
    if vals[-1] < cap:
        vals.append(float(cap))
    return tuple(vals)


def _pct(v):
    return f"{v:g}%"


def _num(v):
    return f"{v:g}"


@dataclass(frozen=True)
class SweepParam:
    """A sweepable input: the Assumptions field it drives and its automatic axis."""
    key: str
    label: str
    field: str | None   # Assumptions field; None = special-cased in _cell_assumptions
    to_field: object    # transform: axis (widget) units -> Assumptions units
    values: tuple       # axis values, in widget units
    fmt: object         # axis-tick / table formatter


SWEEP_PARAMS = {p.key: p for p in [
    SweepParam("price", "Purchase price ($)", "price", float,
               _dollar_axis(200_000, 2_000_000, price), fmt),
    SweepParam("down_pct", "Down payment (%)", "down_pct", lambda v: v / 100,
               _lin_axis(3, 100), _pct),
    SweepParam("mort_rate", "Mortgage rate (%)", "mortgage_rate", lambda v: v / 100,
               _lin_axis(3, 9), _pct),
    SweepParam("term", "Term (years)", "term_years", int, (15, 30), _num),
    SweepParam("closing_pct", "Closing costs (% of price)", "closing_buy_pct",
               lambda v: v / 100, _lin_axis(0, 5), _pct),
    SweepParam("onetime", "One-time costs ($)", "other_onetime_costs", float,
               _dollar_axis(0, 50_000, onetime), fmt),
    SweepParam("hoa", "HOA ($/mo)", "hoa_monthly", float,
               _dollar_axis(0, 1_000, hoa), fmt),
    SweepParam("alt_return", "Investment return (%)", "alt_return_annual",
               lambda v: v / 100, _lin_axis(0, 12), _pct),
    SweepParam("home_appr", "Home appreciation (%/yr)", "home_appreciation",
               lambda v: v / 100, _lin_axis(0, 10), _pct),
    SweepParam("rent_growth", "Rent growth (%/yr)", "rent_growth",
               lambda v: v / 100, _lin_axis(0, 10), _pct),
    SweepParam("p2r", "Price-to-rent ratio", None, None, _lin_axis(10, 45), _num),
    SweepParam("prop_tax", "Property tax (% of price)", "property_tax_rate",
               lambda v: v / 100, _lin_axis(0.5, 2.5), _pct),
    SweepParam("insurance", "Insurance (% of value/yr)", "insurance_rate",
               lambda v: v / 100, _lin_axis(0, 1), _pct),
    SweepParam("maintenance", "Maintenance (% of value/yr)", "maintenance_rate",
               lambda v: v / 100, _lin_axis(0, 3), _pct),
    SweepParam("selling_pct", "Selling costs (% of value)", "selling_cost_pct",
               lambda v: v / 100, _lin_axis(0, 10), _pct),
    SweepParam("capital", "Investable capital ($)", "capital", float,
               _dollar_axis(100_000, 3_000_000, capital), fmt),
    SweepParam("horizon", "Horizon (years)", "horizon_years", int,
               _int_axis(1, 30), _num),
    SweepParam("marginal", "Marginal tax rate (%)", "marginal_tax_rate",
               lambda v: v / 100, _lin_axis(0, 55), _pct),
    SweepParam("inv_tax", "Annual tax on returns (%)", "investment_tax_drag",
               lambda v: v / 100, _lin_axis(0, 50), _pct),
    SweepParam("cap_gains", "Capital gains at sale (%)", "cap_gains_rate",
               lambda v: v / 100, _lin_axis(0, 45), _pct),
    SweepParam("monthly_income", "Monthly income ($)", "monthly_income", float,
               _dollar_axis(0, 5_000, monthly_income), fmt),
]}


def _fmt_years(v):
    return f"{v:.1f} yrs"


def _fmt_runway(v):
    return "100+ yrs" if v >= 100 else f"{v:.1f} yrs"


# Fixed set of 4 metrics shown in the Scenario Explorer tab, in display order.
# Each entry: (key, label, direction, fmt_fn, hoverfmt, colorscale, zmid)
FIXED_METRICS = [
    ("buy_adv",     "Buy advantage ($, maximize)",         "max", fmt,        "$,.0f", "RdBu",    0.0),
    ("breakeven",   "Breakeven (yrs, minimize)",            "min", _fmt_years, ".1f",   "Viridis", None),
    ("monthly_cost","Monthly cost, mo 1 ($, minimize)",     "min", fmt,        "$,.0f", "Viridis", None),
    ("buy_runway",  "Total buy runway (yrs, maximize)",     "max", _fmt_runway,".1f",   "Viridis", None),
]
# Index by key for convenient lookup
FIXED_METRIC_KEYS = [m[0] for m in FIXED_METRICS]


def _cell_assumptions(base_a: Assumptions, x_key, xv, y_key, yv, ratio):
    """Assumptions for one grid cell: the sidebar scenario with the two swept
    fields overridden. If price or the price-to-rent ratio is swept, the cell's
    rent is re-derived as price ÷ ratio ÷ 12 (same convention as the sidebar's
    derived rent); otherwise the sidebar scenario's rent is kept."""
    overrides = {}
    price_v, ratio_v, derive = base_a.price, ratio, False
    for key, val in ((x_key, xv), (y_key, yv)):
        p = SWEEP_PARAMS[key]
        if key == "price":
            price_v, derive = float(val), True
        elif key == "p2r":
            ratio_v, derive = float(val), True
        if p.field is not None:
            overrides[p.field] = p.to_field(val)
    if derive:
        overrides["monthly_rent"] = rent_from_price(price_v, ratio_v)
    return replace(base_a, **overrides)


@st.cache_data(show_spinner="Running custom sweep...")
def run_custom_sweep(base_a: Assumptions, x_key: str, y_key: str,
                     x_vals: tuple, y_vals: tuple, ratio: float):
    """All-metrics grid over y_vals × x_vals (rows = Y). One simulate() + one runway()
    call per cell; unaffordable cells stay NaN across all metric grids.

    Returns a dict keyed by metric key, each value a 2-D np.ndarray of shape
    (len(y_vals), len(x_vals)).
    """
    shape = (len(y_vals), len(x_vals))
    grids = {k: np.full(shape, np.nan) for k in FIXED_METRIC_KEYS}

    for i, yv in enumerate(y_vals):
        for j, xv in enumerate(x_vals):
            cell_a = _cell_assumptions(base_a, x_key, xv, y_key, yv, ratio)
            upfront_c = (cell_a.price * cell_a.down_pct
                         + cell_a.price * cell_a.closing_buy_pct
                         + cell_a.other_onetime_costs)
            if upfront_c > cell_a.capital:
                continue

            # --- single simulate() call ---
            r = simulate(cell_a)
            grids["buy_adv"][i, j] = r.net_worth_buy_liq[-1] - r.net_worth_rent_liq[-1]
            be = r.breakeven_month
            grids["breakeven"][i, j] = be / 12 if be > 0 else math.nan
            # gross owner cost (before the interest deduction), same as the Overview
            grids["monthly_cost"][i, j] = (r.outflow_buy[1] + r.tax_benefit_m[1]
                                           if len(r.outflow_buy) > 1 else math.nan)

            # --- single runway() call ---
            rr = runway(cell_a)
            grids["buy_runway"][i, j] = (
                min(rr.depleted_buy_month / 12, 100.0)
                if rr.depleted_buy_month is not None else 100.0
            )

    return grids


with tab_explorer:
    st.caption("Ranges are automatic — full natural range for bounded inputs, 2× the "
               "current value for open-ended dollar inputs. Rent scales with price via "
               "the price-to-rent ratio; blank cells are unaffordable.")

    sc1, sc2 = st.columns(2)
    x_key = sc1.selectbox("X axis", list(SWEEP_PARAMS), key="sweep_x",
                          format_func=lambda k: SWEEP_PARAMS[k].label,
                          help="Input swept along the horizontal axis. Bounded inputs "
                               "sweep their full slider range; open-ended dollar "
                               "inputs sweep from a sane floor up to 2× the current "
                               "sidebar value.")
    y_key = sc2.selectbox("Y axis", list(SWEEP_PARAMS), key="sweep_y",
                          format_func=lambda k: SWEEP_PARAMS[k].label,
                          help="Input swept along the vertical axis; same automatic "
                               "ranges as the X axis.")

    if x_key == y_key:
        st.warning("X and Y are the same input — pick two different parameters.")
    else:
        xp, yp = SWEEP_PARAMS[x_key], SWEEP_PARAMS[y_key]
        x_vals, y_vals = xp.values, yp.values

        grids = run_custom_sweep(a, x_key, y_key, x_vals, y_vals, p2r)

        x_labels = [xp.fmt(v) for v in x_vals]
        y_labels = [yp.fmt(v) for v in y_vals]

        for m_key, m_label, m_dir, m_fmt, m_hoverfmt, m_colorscale, m_zmid in FIXED_METRICS:
            z = grids[m_key]
            st.markdown(f"**{_mdsafe(m_label)}**")
            left, right = st.columns([3, 2])

            with left.container(border=True):
                fig = go.Figure(go.Heatmap(
                    z=z, x=x_labels, y=y_labels,
                    colorscale=m_colorscale, zmid=m_zmid,
                    reversescale=(m_dir == "min"),
                    colorbar=dict(title=dict(text=_mdsafe(m_label), font=dict(size=11)),
                                  thickness=12),
                    hovertemplate=(f"{_mdsafe(xp.label)}: %{{x}}<br>"
                                   f"{_mdsafe(yp.label)}: %{{y}}<br>"
                                   f"{_mdsafe(m_label)}: %{{z:{m_hoverfmt}}}"
                                   f"<extra></extra>"),
                ))
                fig.update_layout(height=400, margin=dict(l=70, r=20, t=10, b=40),
                                  xaxis_title=_mdsafe(xp.label),
                                  yaxis_title=_mdsafe(yp.label))
                st.plotly_chart(fig)

            with right.container(border=True):
                verb = "maximizing" if m_dir == "max" else "minimizing"
                rows = []
                for j, xv in enumerate(x_vals):
                    col = z[:, j]
                    if np.isfinite(col).any():
                        ii = int(np.nanargmax(col) if m_dir == "max"
                                 else np.nanargmin(col))
                        rows.append({
                            xp.label: xp.fmt(xv),
                            f"Best {yp.label}": yp.fmt(y_vals[ii]),
                            m_label: m_fmt(col[ii]),
                        })
                st.markdown(_mdsafe(f"**Best {yp.label} per {xp.label}**"))
                if rows:
                    st.dataframe(
                        pd.DataFrame(rows), hide_index=True, height=360,
                        column_config={
                            xp.label: st.column_config.TextColumn(
                                help=f"Swept value of {_mdsafe(xp.label)} for this row"),
                            f"Best {yp.label}": st.column_config.TextColumn(
                                help=f"{_mdsafe(yp.label)} value {verb} {_mdsafe(m_label)} "
                                     f"at this {_mdsafe(xp.label)}; unaffordable or "
                                     f"undefined cells are skipped"),
                            m_label: st.column_config.TextColumn(
                                help="Metric value at that best cell"),
                        },
                    )
                else:
                    st.warning("Every cell is either unaffordable or has no defined "
                               "value for this metric.")

# ================================================================ Charts
with tab_charts:
    st.caption("Supplementary views for the scenario configured in the sidebar.")

    if not res.feasible:
        st.error(f"Infeasible: upfront cash needed ({fmtm(upfront)}) "
                 f"exceeds capital ({fmtm(capital)}).")
    else:
        # ---- Moved cards band: six secondary cards from Overview ----
        _ch_col_w, _ch_col_cf, _ch_col_rt = st.columns(3, gap="medium")

        with _ch_col_w:
            st.markdown("**Wealth**")
            _ch_w1, _ch_w2 = st.columns(2, gap="small")
            _ch_w1.metric("Cash at closing", fmt(upfront), border=True, height=MCH,
                          help="Down payment + closing costs + one-time costs — leaves your capital on day one")
            _ch_w2.metric("Reserve after closing", fmt(capital - upfront), border=True, height=MCH,
                          help="Capital left invested after closing — your emergency cushion in the buy scenario")

        with _ch_col_cf:
            st.markdown("**Cash flow**")
            _ch_cf1, _ch_cf2 = st.columns(2, gap="small")
            _ch_cf1.metric("Interest deduction (mo 1)", fmt(_tax_benefit_m1), border=True, height=MCH,
                           help="Marginal rate × deductible interest in month 1. Reduces the "
                                "owner's net outflow; shrinks over time as the loan amortises.")
            _ch_cf2.metric("Principal portion (mo 1)", fmt(_principal_m1), border=True, height=MCH,
                           help="Principal repaid in month 1 — cash out of your pocket, but it "
                                "builds equity rather than being a pure cost.")

        with _ch_col_rt:
            st.markdown("**Retirement**")
            _ch_rt1, _ch_rt2 = st.columns(2, gap="small")
            _ch_rt1.metric("Buy burn (mo 1)", fmt(_burn_buy_m1), border=True, height=MCH,
                           help="Owner's total month-1 outflow: P&I + property tax + insurance + "
                                "maintenance + HOA + PMI. No interest-deduction benefit (no income).")
            _ch_rt2.metric("Rent burn (mo 1)", fmt(_burn_rent_m1), border=True, height=MCH,
                           help="Renter's month-1 outflow: the rent payment.")

        sup_col1, sup_col2 = st.columns(2)
        with sup_col1.container(border=True):
            st.markdown("**Buy net worth composition**")
            st.plotly_chart(networth_composition_fig(res, _yrs, selling_pct),
                            key="sup_networth_comp")
            st.caption("Bands sum to the buy 'if sold' line; home equity is only "
                       "accessible by selling or borrowing.")

        with sup_col2.container(border=True):
            st.markdown("**Sensitivity: buy advantage vs. investment return**")
            st.plotly_chart(sensitivity_fig(a, alt_return, horizon), key="sup_sensitivity")
            st.caption("Zero crossing = investment return at which renting starts to win.")
