"""Rent-vs-buy simulation model.

Two scenarios are simulated month by month over a horizon:

- BUY: pay down payment + one-time costs from capital, invest the rest.
  Pay mortgage P&I, property tax, insurance, maintenance, HOA, PMI.
- RENT: invest all capital, pay rent (grows annually).

Fairness rule: each month, whichever scenario has the lower housing outflow
invests the difference into its portfolio. Both scenarios therefore spend the
same total dollars every month; only the split between housing and investing
differs.

Simplifications (documented in the app):
- Investment taxes are split in two: a small annual drag on returns
  (dividends/turnover, r_after = r * (1 - drag)) plus capital-gains tax on
  embedded gains (value - cost basis) applied in all "if sold" values.
- Mortgage interest deduction: a single combined marginal rate applied to
  interest on the deductible share of the balance (cap / balance, <= 1).
  Assumes you itemize regardless (reasonable at CA incomes with SALT).
- Property tax assessed value grows at the Prop 13 cap, independent of market
  value.
- "Liquidation" net worth subtracts selling costs on the home but does not
  model capital-gains tax on the home sale (§121 exclusion ignores the first
  $250k/$500k of gain anyway).
"""

from dataclasses import dataclass, replace
import math


@dataclass
class Assumptions:
    # capital & horizon
    capital: float = 1_500_000
    horizon_years: int = 10

    # markets
    alt_return_annual: float = 0.035     # nominal pre-tax return on investments
    investment_tax_drag: float = 0.0     # annual drag: dividends/turnover taxed yearly
    cap_gains_rate: float = 0.25         # tax on unrealized gains when portfolio is sold
    inflation: float = 0.025

    # purchase
    price: float = 1_400_000
    down_pct: float = 0.50
    mortgage_rate: float = 0.065
    term_years: int = 30
    closing_buy_pct: float = 0.015       # escrow/title/origination, % of price
    other_onetime_costs: float = 10_000  # moving, immediate fixes, etc.
    selling_cost_pct: float = 0.06       # agent commissions + fees at exit

    # carrying costs
    home_appreciation: float = 0.055
    property_tax_rate: float = 0.0115    # of purchase price initially
    prop_tax_growth: float = 0.02        # Prop 13 assessed-value cap
    insurance_rate: float = 0.0025       # of current home value, annual
    maintenance_rate: float = 0.01       # of current home value, annual
    hoa_monthly: float = 250.0
    pmi_rate: float = 0.006              # of balance, annual, while LTV > 80%

    # taxes
    marginal_tax_rate: float = 0.42      # combined fed + CA marginal rate
    include_interest_deduction: bool = True
    interest_deduction_cap: float = 750_000

    # rent alternative
    monthly_rent: float = 4_167   # ~$1.4M / 28 / 12, consistent with p2r=28 default
    rent_growth: float = 0.04


@dataclass
class Result:
    feasible: bool
    months: list            # 0..N
    home_value: list
    loan_balance: list
    portfolio_buy: list
    portfolio_rent: list
    net_worth_buy: list     # mark-to-market: portfolio + home - balance
    net_worth_buy_liq: list # after home selling costs + cap-gains tax on portfolio
    net_worth_rent: list    # mark-to-market portfolio value
    net_worth_rent_liq: list  # after cap-gains tax on portfolio
    portfolio_buy_after_tax: list   # portfolio net of cap-gains tax if sold now
    portfolio_rent_after_tax: list
    outflow_buy: list       # monthly housing outflow, net of tax benefit
    outflow_rent: list
    interest_paid: list     # cumulative
    principal_paid: list    # cumulative
    breakeven_month: int    # first month buy (liq) >= rent and stays relevant; -1 if never
    # monthly components (index 0 is the closing month, all zeros)
    payment_m: list         # P&I
    interest_m: list
    principal_m: list
    prop_tax_m: list
    insurance_m: list
    maintenance_m: list
    hoa_m: list
    pmi_m: list
    tax_benefit_m: list
    contrib_buy_m: list     # surplus invested into the buy-side portfolio
    contrib_rent_m: list    # surplus invested into the rent-side portfolio


def monthly_payment(loan: float, annual_rate: float, years: int) -> float:
    if loan <= 0:
        return 0.0
    r = annual_rate / 12
    n = years * 12
    if r == 0:
        return loan / n
    return loan * r / (1 - (1 + r) ** -n)


def simulate(a: Assumptions) -> Result:
    n = a.horizon_years * 12
    down = a.price * a.down_pct
    upfront = down + a.price * a.closing_buy_pct + a.other_onetime_costs
    feasible = upfront <= a.capital

    loan0 = a.price - down
    pay = monthly_payment(loan0, a.mortgage_rate, a.term_years)
    r_m = a.mortgage_rate / 12

    # after-tax monthly investment growth
    r_after = a.alt_return_annual * (1 - a.investment_tax_drag)
    g_inv = (1 + r_after) ** (1 / 12) - 1
    g_home = (1 + a.home_appreciation) ** (1 / 12) - 1

    home = a.price
    assessed = a.price
    bal = loan0
    pf_buy = max(a.capital - upfront, 0.0)
    pf_rent = a.capital
    basis_buy = pf_buy    # cost basis: contributions; gains above this taxed at sale
    basis_rent = pf_rent
    rent = a.monthly_rent
    cum_int = 0.0
    cum_prin = 0.0

    months = [0]
    home_v = [home]
    bal_v = [bal]
    pfb_v = [pf_buy]
    pfr_v = [pf_rent]
    nwb_v = [pf_buy + home - bal]
    nwbl_v = [pf_buy + home * (1 - a.selling_cost_pct) - bal]
    nwr_v = [pf_rent]
    nwrl_v = [pf_rent]
    pbat_v = [pf_buy]
    prat_v = [pf_rent]
    ob_v = [0.0]
    or_v = [0.0]
    ci_v = [0.0]
    cp_v = [0.0]
    pay_v = [0.0]
    int_v = [0.0]
    prin_v = [0.0]
    ptax_v = [0.0]
    ins_v = [0.0]
    maint_v = [0.0]
    hoa_v = [0.0]
    pmi_v = [0.0]
    tb_v = [0.0]
    cb_v = [0.0]
    cr_v = [0.0]

    for m in range(1, n + 1):
        # grow portfolios first, then apply this month's contributions
        pf_buy *= 1 + g_inv
        pf_rent *= 1 + g_inv
        home *= 1 + g_home

        # mortgage
        interest = bal * r_m
        payment = min(pay, bal + interest)
        principal = payment - interest
        bal -= principal
        cum_int += interest
        cum_prin += principal

        # tax benefit of interest (deductible share limited by cap)
        tax_benefit = 0.0
        if a.include_interest_deduction and interest > 0:
            share = min(1.0, a.interest_deduction_cap / max(bal + principal, 1.0))
            tax_benefit = interest * share * a.marginal_tax_rate

        pmi = 0.0
        if loan0 > 0 and a.down_pct < 0.20 and bal / a.price > 0.78:
            pmi = bal * a.pmi_rate / 12

        prop_tax = assessed * a.property_tax_rate / 12
        insurance = home * a.insurance_rate / 12
        maintenance = home * a.maintenance_rate / 12
        carrying = prop_tax + insurance + maintenance + a.hoa_monthly + pmi
        outflow_buy = payment + carrying - tax_benefit
        outflow_rent = rent

        # fairness: lower-outflow scenario invests the difference
        diff = outflow_buy - outflow_rent
        contrib_buy = max(-diff, 0.0)
        contrib_rent = max(diff, 0.0)
        pf_buy += contrib_buy
        pf_rent += contrib_rent
        basis_buy += contrib_buy
        basis_rent += contrib_rent

        # "if sold now" portfolio values: cap-gains tax on embedded gains
        pf_buy_at = pf_buy - max(0.0, pf_buy - basis_buy) * a.cap_gains_rate
        pf_rent_at = pf_rent - max(0.0, pf_rent - basis_rent) * a.cap_gains_rate

        # annual steps
        if m % 12 == 0:
            assessed *= 1 + a.prop_tax_growth
            rent *= 1 + a.rent_growth

        months.append(m)
        home_v.append(home)
        bal_v.append(bal)
        pfb_v.append(pf_buy)
        pfr_v.append(pf_rent)
        nwb_v.append(pf_buy + home - bal)
        nwbl_v.append(pf_buy_at + home * (1 - a.selling_cost_pct) - bal)
        nwr_v.append(pf_rent)
        nwrl_v.append(pf_rent_at)
        pbat_v.append(pf_buy_at)
        prat_v.append(pf_rent_at)
        ob_v.append(outflow_buy)
        or_v.append(outflow_rent)
        ci_v.append(cum_int)
        cp_v.append(cum_prin)
        pay_v.append(payment)
        int_v.append(interest)
        prin_v.append(principal)
        ptax_v.append(prop_tax)
        ins_v.append(insurance)
        maint_v.append(maintenance)
        hoa_v.append(a.hoa_monthly)
        pmi_v.append(pmi)
        tb_v.append(tax_benefit)
        cb_v.append(contrib_buy)
        cr_v.append(contrib_rent)

    breakeven = -1
    for m in range(1, n + 1):
        if nwbl_v[m] >= nwrl_v[m]:
            breakeven = m
            break

    return Result(
        feasible=feasible,
        months=months,
        home_value=home_v,
        loan_balance=bal_v,
        portfolio_buy=pfb_v,
        portfolio_rent=pfr_v,
        net_worth_buy=nwb_v,
        net_worth_buy_liq=nwbl_v,
        net_worth_rent=nwr_v,
        net_worth_rent_liq=nwrl_v,
        portfolio_buy_after_tax=pbat_v,
        portfolio_rent_after_tax=prat_v,
        outflow_buy=ob_v,
        outflow_rent=or_v,
        interest_paid=ci_v,
        principal_paid=cp_v,
        breakeven_month=breakeven,
        payment_m=pay_v,
        interest_m=int_v,
        principal_m=prin_v,
        prop_tax_m=ptax_v,
        insurance_m=ins_v,
        maintenance_m=maint_v,
        hoa_m=hoa_v,
        pmi_m=pmi_v,
        tax_benefit_m=tb_v,
        contrib_buy_m=cb_v,
        contrib_rent_m=cr_v,
    )


def advantage_at_horizon(a: Assumptions) -> float:
    """Buy-minus-rent net worth (liquidation basis) at the horizon."""
    r = simulate(a)
    return r.net_worth_buy_liq[-1] - r.net_worth_rent_liq[-1]


def rent_from_price(price: float, price_to_rent: float) -> float:
    """Monthly rent for a comparable home given an annual price-to-rent ratio."""
    return price / price_to_rent / 12


def sweep(base: Assumptions, prices, down_pcts, price_to_rent: float):
    """Grid of (price, down%) -> dict with advantage and feasibility info.

    Rent scales with price via the price-to-rent ratio so each cell compares
    buying a home to renting the comparable home.
    """
    grid = []
    for p in prices:
        row = []
        for d in down_pcts:
            a = replace(
                base,
                price=p,
                down_pct=d,
                monthly_rent=rent_from_price(p, price_to_rent),
            )
            upfront = p * d + p * a.closing_buy_pct + a.other_onetime_costs
            if upfront > a.capital:
                row.append({"advantage": math.nan, "feasible": False,
                            "reserve": a.capital - upfront, "max_outflow": math.nan})
            else:
                res = simulate(a)
                row.append({
                    "advantage": res.net_worth_buy_liq[-1] - res.net_worth_rent_liq[-1],
                    "feasible": True,
                    "reserve": a.capital - upfront,
                    "max_outflow": max(res.outflow_buy[1:13]) if len(res.outflow_buy) > 1 else 0.0,
                })
        grid.append(row)
    return grid
