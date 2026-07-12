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

from dataclasses import dataclass, field, replace
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

    # property-generated income (buy side only)
    monthly_income: float = 0.0   # e.g. ADU rent; grows with rent_growth; stops at forced sale


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
    outflow_buy: list       # monthly housing outflow, net of tax benefit and income
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
    income_m: list          # property income (buy side only; grows with rent_growth)
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
    income = a.monthly_income   # property income; grows with rent_growth annually
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
    inc_v = [0.0]
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
        outflow_buy = payment + carrying - tax_benefit - income
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
            income *= 1 + a.rent_growth

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
        inc_v.append(income)
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
        income_m=inc_v,
        contrib_buy_m=cb_v,
        contrib_rent_m=cr_v,
    )


def rent_from_price(price: float, price_to_rent: float) -> float:
    """Monthly rent for a comparable home given an annual price-to-rent ratio."""
    return price / price_to_rent / 12


@dataclass
class RunwayResult:
    """Result of a retirement-drawdown runway simulation.

    Both scenarios draw housing costs (plus extra_monthly living expenses)
    from their respective liquid investment portfolios until depletion.
    No fairness rule — each side is fully independent.

    Buy scenario sell-and-rent phase:
        When the buy-side liquid portfolio can no longer cover the month's
        housing need as an owner, the house is sold.  Sale proceeds
        (home_value × (1 − selling_cost_pct) − loan_balance) are injected
        into the liquid portfolio and the owner becomes a renter at the
        then-current market rent.  Home-sale capital gains are NOT modeled
        (§121 exclusion covers a large portion; consistent with the rest of
        the app).  The runway clock continues until this combined portfolio
        also depletes.

    sale_month: month the house was sold (None if the owner never ran out
        of cash while owning).
    sale_proceeds: net proceeds added to the portfolio at sale_month (None
        if sale_month is None).
    depleted_buy_month: FINAL depletion month (after the rent phase), or
        None if the portfolio survives all of max_years.
    liquid_buy: shows the jump at sale_month from the proceeds injection.
    monthly_need_buy: switches from owner costs to (rent + extra_monthly)
        the month after sale_month.
    home_equity: 0 from sale_month onward.
    """
    months: list                  # 0..N month indices
    liquid_buy: list              # buy-side portfolio value each month (0 after final depletion)
    liquid_rent: list             # rent-side portfolio value each month (0 after depletion)
    monthly_need_buy: list        # gross housing outflow for buy each month (no tax benefit)
    monthly_need_rent: list       # gross housing outflow for rent each month
    home_equity: list             # home*(1-selling_cost_pct) - loan_balance each month; 0 after sale
    depleted_buy_month: int | None   # FINAL month portfolio hit zero (None = survives max_years)
    depleted_rent_month: int | None  # month portfolio hit zero (None = survives max_years)
    sale_month: int | None        # month house was sold (None = owner never ran out as owner)
    sale_proceeds: float | None   # net proceeds injected at sale_month (None if no sale)


def runway(a: Assumptions, extra_monthly: float = 0.0, max_years: int = 100) -> RunwayResult:
    """Simulate retirement drawdown of housing costs from the liquid portfolio.

    Both scenarios are simulated independently (no fairness rule).  The
    owner and renter each draw their housing costs — plus extra_monthly
    non-housing spending — out of their own starting liquid portfolio.
    No income, so no mortgage-interest deduction benefit.

    Buy scenario starting liquid portfolio:
        max(capital - down - closing - one_time, 0)

    Rent scenario starting liquid portfolio:
        capital

    Withdrawal mechanics each month (both scenarios):
    1. Grow: value *= (1 + g_inv)
    2. Gross up for embedded capital-gains tax:
           gain_frac = max(0, 1 - basis/value)  if value > 0 else 0
           sell = need / (1 - cap_gains_rate * gain_frac)
    3. If sell >= value: depleted — record month, stop drawing.
    4. Else: basis -= basis * (sell / value);  value -= sell.
    """
    n = max_years * 12

    # --- Buy setup ---
    down = a.price * a.down_pct
    closing = a.price * a.closing_buy_pct
    one_time = a.other_onetime_costs
    upfront = down + closing + one_time

    loan0 = a.price - down
    pay = monthly_payment(loan0, a.mortgage_rate, a.term_years)
    r_m = a.mortgage_rate / 12

    # --- Shared investment growth ---
    r_after = a.alt_return_annual * (1 - a.investment_tax_drag)
    g_inv = (1 + r_after) ** (1 / 12) - 1
    g_home = (1 + a.home_appreciation) ** (1 / 12) - 1

    # Buy starting state
    liq_buy = max(a.capital - upfront, 0.0)
    basis_buy = liq_buy
    home = a.price
    assessed = a.price
    bal = loan0
    income = a.monthly_income   # property income; grows with rent_growth; stops at sale

    # Rent starting state
    liq_rent = a.capital
    basis_rent = a.capital
    rent = a.monthly_rent

    # Output series (month 0 = starting state, no flows yet)
    months_v = [0]
    lb_v = [liq_buy]
    lr_v = [liq_rent]
    nb_v = [0.0]      # month 0: no outflow
    nr_v = [0.0]
    he_v = [home * (1 - a.selling_cost_pct) - bal]

    depleted_buy_month: int | None = None
    depleted_rent_month: int | None = None
    sale_month: int | None = None
    sale_proceeds_val: float | None = None
    # Track whether we're in the post-sale renting phase for the buy scenario
    sold_house: bool = False

    for m in range(1, n + 1):
        # ---- grow home & compute buy housing need ----
        if not sold_house:
            home *= 1 + g_home

            interest = bal * r_m
            payment = min(pay, bal + interest)
            principal = payment - interest
            bal = max(bal - principal, 0.0)

            pmi = 0.0
            if loan0 > 0 and a.down_pct < 0.20 and (bal / a.price) > 0.78:
                pmi = bal * a.pmi_rate / 12

            prop_tax = assessed * a.property_tax_rate / 12
            insurance = home * a.insurance_rate / 12
            maintenance = home * a.maintenance_rate / 12

            # No interest-deduction benefit (no income to deduct against)
            gross_cost_buy = payment + prop_tax + insurance + maintenance + a.hoa_monthly + pmi + extra_monthly
            # Income offsets the gross cost; need can go <= 0 (portfolio just grows)
            need_buy = gross_cost_buy - income
        else:
            # Post-sale: buy scenario now rents at the same rent rate the rent scenario uses
            # Income stops when the house is sold (ADU sells with the house)
            need_buy = rent + extra_monthly

        need_rent = rent + extra_monthly

        # Annual steps (rent, assessed value, income)
        if m % 12 == 0:
            if not sold_house:
                assessed *= 1 + a.prop_tax_growth
                income *= 1 + a.rent_growth
            rent *= 1 + a.rent_growth

        # ---- buy portfolio withdrawal ----
        if depleted_buy_month is None:
            liq_buy *= 1 + g_inv
            if need_buy <= 0:
                # Income exceeds gross costs — no withdrawal needed; portfolio just grows.
                # The surplus is NOT deposited (conservative/simple).
                pass
            else:
                if liq_buy > 0:
                    gain_frac = max(0.0, 1.0 - basis_buy / liq_buy)
                    sell_buy = need_buy / (1.0 - a.cap_gains_rate * gain_frac)
                else:
                    sell_buy = need_buy

                if sell_buy >= liq_buy and not sold_house:
                    # Owner's cash insufficient — sell the house and become a renter
                    leftover = max(liq_buy, 0.0)
                    proceeds = home * (1.0 - a.selling_cost_pct) - bal
                    # Edge case: proceeds may be negative (underwater), clamp to 0
                    proceeds = max(proceeds, 0.0)
                    total = leftover + proceeds
                    sale_month = m
                    sale_proceeds_val = proceeds
                    sold_house = True
                    bal = 0.0

                    # Post-sale need is rent (updated to current market rent)
                    need_buy = rent + extra_monthly

                    # Can the combined total cover this month's need as a renter?
                    if total > 0:
                        gain_frac2 = max(0.0, 1.0 - basis_buy / total) if total > 0 else 0.0
                        sell_buy2 = need_buy / (1.0 - a.cap_gains_rate * gain_frac2)
                    else:
                        sell_buy2 = need_buy

                    if sell_buy2 >= total:
                        # Depleted immediately (absurdly rare edge case)
                        liq_buy = 0.0
                        basis_buy = 0.0
                        depleted_buy_month = m
                    else:
                        # Inject proceeds into portfolio; sale cash is post-tax, add to basis
                        basis_buy = basis_buy + proceeds  # leftover basis preserved + post-tax proceeds
                        liq_buy = total
                        # Withdraw this month's rent need
                        basis_buy -= basis_buy * (sell_buy2 / liq_buy)
                        liq_buy -= sell_buy2

                elif sell_buy >= liq_buy and sold_house:
                    # Already a renter (post-sale phase) — final depletion
                    depleted_buy_month = m
                    liq_buy = 0.0
                    basis_buy = 0.0
                else:
                    basis_buy -= basis_buy * (sell_buy / liq_buy)
                    liq_buy -= sell_buy

        # ---- rent portfolio withdrawal ----
        if depleted_rent_month is None:
            liq_rent *= 1 + g_inv
            if liq_rent > 0:
                gain_frac = max(0.0, 1.0 - basis_rent / liq_rent)
                sell_rent = need_rent / (1.0 - a.cap_gains_rate * gain_frac)
            else:
                sell_rent = need_rent
            if sell_rent >= liq_rent:
                depleted_rent_month = m
                liq_rent = 0.0
                basis_rent = 0.0
            else:
                basis_rent -= basis_rent * (sell_rent / liq_rent)
                liq_rent -= sell_rent

        months_v.append(m)
        lb_v.append(liq_buy)
        lr_v.append(liq_rent)
        nb_v.append(need_buy)
        nr_v.append(need_rent)
        # home_equity is 0 once the house is sold
        if sold_house:
            he_v.append(0.0)
        else:
            he_v.append(home * (1 - a.selling_cost_pct) - bal)

        # Stop early once both are depleted
        if depleted_buy_month is not None and depleted_rent_month is not None:
            break

    return RunwayResult(
        months=months_v,
        liquid_buy=lb_v,
        liquid_rent=lr_v,
        monthly_need_buy=nb_v,
        monthly_need_rent=nr_v,
        home_equity=he_v,
        depleted_buy_month=depleted_buy_month,
        depleted_rent_month=depleted_rent_month,
        sale_month=sale_month,
        sale_proceeds=sale_proceeds_val,
    )
