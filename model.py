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
  on distributed income, which is reinvested after tax, plus capital-gains tax on
  embedded gains (value - cost basis) applied in all "if sold" values.
- Mortgage interest deduction: separate federal and California marginal rates applied to
  interest on each jurisdiction’s eligible opening balance.
  Assumes you itemize regardless (reasonable at CA incomes with SALT).
- Property tax assessed value grows at the Prop 13 cap, independent of market
  value.
- "Liquidation" net worth subtracts selling costs on the home AND capital-gains
  tax on the home sale. Home cost basis = price + eligible closing costs (one-time /
  moving costs are not basis). Gain = value x (1 - selling costs) - basis. The
  Sec. 121 exclusion ($250k single / $500k married, `home_gain_exclusion`)
  applies only once the home has been owned and used for >= 24 months; before
  that the exclusion is zero (partial / hardship exclusions are ignored). Tax =
  max(0, gain - exclusion) x cap_gains_rate (same rate as the portfolio).
  Mark-to-market net worth stays untaxed.
"""

from bisect import bisect_left
from dataclasses import dataclass, replace
from functools import cache


@dataclass
class Assumptions:
    # capital & horizon
    capital: float = 1_500_000
    horizon_years: int = 10

    # markets
    alt_return_annual: float = 0.035     # nominal pre-tax return on investments
    investment_tax_drag: float = 0.0     # annual drag: dividends/turnover taxed yearly
    cap_gains_rate: float = 0.25         # tax on unrealized gains (portfolio and home) when sold
    home_gain_exclusion: float = 250_000  # Sec. 121: 250k single / 500k married (after 24 months)

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
    marginal_tax_rate: float = 0.42      # federal marginal rate (legacy single-rate scenarios use this alone)
    include_interest_deduction: bool = True
    interest_deduction_cap: float = 750_000

    # rent alternative
    monthly_rent: float = 4_167   # ~$1.4M / 28 / 12, consistent with p2r=28 default
    rent_growth: float = 0.04

    # property-generated income (buy side only)
    monthly_income: float = 0.0   # e.g. ADU rent; grows with rent_growth; stops at forced sale

    closing_basis_share: float = 0.0  # fraction of total closing costs eligible for basis
    investment_income_share: float | None = None  # fraction of return distributed as income
    annual_interest_savings_limit: float | None = None  # optional annualized ceiling, applied monthly

    fixed_down_payment: float | None = None
    fixed_loan_size: float | None = None
    ca_marginal_tax_rate: float = 0.0
    ca_interest_deduction_cap: float = 1_000_000
    seller_closing_credit: float = 0.0

    @property
    def down_payment(self) -> float:
        if self.fixed_loan_size is not None:
            if self.fixed_down_payment is not None:
                raise ValueError("Select only one fixed financing amount")
            return self.price - self.fixed_loan_size
        if self.fixed_down_payment is not None:
            return self.fixed_down_payment
        return self.price * self.down_pct

    @property
    def applied_seller_credit(self) -> float:
        return min(max(0.0, self.seller_closing_credit), self.price * self.closing_buy_pct)

    @property
    def buyer_paid_closing_costs(self) -> float:
        return self.price * self.closing_buy_pct - self.applied_seller_credit

    @property
    def cash_to_close(self) -> float:
        return self.down_payment + self.buyer_paid_closing_costs + self.other_onetime_costs


def monthly_portfolio_rates(a: Assumptions) -> tuple[float, float]:
    """Monthly net growth and reinvested income, each per dollar of opening value."""
    share = a.investment_income_share
    if share is None:
        # Legacy scenarios specified only an annual tax rate.
        share = 1.0 if a.investment_tax_drag else 0.0
    net_fraction = 1 - share * a.investment_tax_drag
    growth = (1 + a.alt_return_annual * net_fraction) ** (1 / 12) - 1
    if net_fraction == 0:
        return 0.0, 0.0
    reinvested = growth * share * (1 - a.investment_tax_drag) / net_fraction
    return growth, reinvested



@dataclass
class Result:
    feasible: bool
    months: list            # 0..N
    home_value: list
    loan_balance: list
    portfolio_buy: list
    portfolio_rent: list
    net_worth_buy: list     # mark-to-market: portfolio + home - balance
    net_worth_buy_liq: list # after home selling costs, home-sale tax + cap-gains tax on portfolio
    net_worth_rent: list    # mark-to-market portfolio value
    net_worth_rent_liq: list  # after cap-gains tax on portfolio
    portfolio_buy_after_tax: list   # portfolio net of cap-gains tax if sold now
    portfolio_rent_after_tax: list
    home_sale_tax: list     # cap-gains tax on the home if sold this month (after Sec. 121)
    outflow_buy: list       # monthly housing outflow, net of tax benefit and income
    outflow_rent: list
    interest_paid: list     # cumulative
    principal_paid: list    # cumulative
    breakeven_month: int    # first month buy (liq) >= rent and stays ahead to the horizon; -1 if never
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


MONTHS_FOR_121 = 24   # Sec. 121 ownership + use test (2 of the last 5 years)


def home_basis(a: Assumptions) -> float:
    """Home cost basis: purchase price + eligible buy-side closing costs."""
    return a.price + a.buyer_paid_closing_costs * a.closing_basis_share


def home_sale_tax(a: Assumptions, home_value: float, months_held: int) -> float:
    """Capital-gains tax owed if the home is sold for `home_value` after
    `months_held` months. Sec. 121 exclusion applies only at >= 24 months
    (partial exclusions ignored)."""
    gain = home_value * (1 - a.selling_cost_pct) - home_basis(a)
    exclusion = a.home_gain_exclusion if months_held >= MONTHS_FOR_121 else 0.0
    return max(0.0, gain - exclusion) * a.cap_gains_rate


def sustained_crossing(diffs: list) -> int:
    """First index m >= 1 such that diffs[k] >= 0 for every k from m through the
    end of the series; -1 if diffs[-1] < 0 (or the series has no month 1).

    "Crosses AND stays": a series that turns non-negative and later goes
    negative again does not count from its first crossing.
    """
    if len(diffs) < 2 or diffs[-1] < 0:
        return -1
    m = len(diffs) - 1
    while m - 1 >= 1 and diffs[m - 1] >= 0:
        m -= 1
    return m


def cashflow_breakeven_month(res: "Result") -> int:
    """First month m >= 1 from which the GROSS owner cost (outflow_buy +
    tax_benefit_m, i.e. before the interest deduction) stays at or below rent
    through the horizon; -1 if owning still costs more than rent at the horizon."""
    return sustained_crossing([
        r - (b + t) for b, t, r in zip(res.outflow_buy, res.tax_benefit_m, res.outflow_rent)
    ])


def simulate(a: Assumptions) -> Result:
    n = a.horizon_years * 12
    down = a.down_payment
    if not 0 <= down <= a.price:
        raise ValueError("Financing amount exceeds purchase price or is negative")
    upfront = a.cash_to_close
    feasible = upfront <= a.capital

    loan0 = a.price - down
    pay = monthly_payment(loan0, a.mortgage_rate, a.term_years)
    r_m = a.mortgage_rate / 12

    # after-tax monthly investment growth
    g_inv, income_rate = monthly_portfolio_rates(a)
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
    hst0 = home_sale_tax(a, home, 0)
    hst_v = [hst0]
    nwbl_v = [pf_buy + home * (1 - a.selling_cost_pct) - bal - hst0]
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
        basis_buy += pf_buy * income_rate
        basis_rent += pf_rent * income_rate
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
            opening_balance = bal + principal
            federal = min(opening_balance, a.interest_deduction_cap) * a.marginal_tax_rate
            california = min(opening_balance, a.ca_interest_deduction_cap) * a.ca_marginal_tax_rate
            tax_benefit = (federal + california) * r_m
            if a.annual_interest_savings_limit is not None:
                tax_benefit = min(tax_benefit, a.annual_interest_savings_limit / 12)

        pmi = 0.0
        if loan0 > 0 and down < a.price * 0.20 and bal / a.price > 0.78:
            pmi = bal * a.pmi_rate / 12

        prop_tax = assessed * a.property_tax_rate / 12
        insurance = home * a.insurance_rate / 12
        maintenance = home * a.maintenance_rate / 12
        carrying = prop_tax + insurance + maintenance + a.hoa_monthly + pmi
        income_m = income   # this month's income (before any year-end growth)
        outflow_buy = payment + carrying - tax_benefit - income_m
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
        hst = home_sale_tax(a, home, m)
        hst_v.append(hst)
        nwbl_v.append(pf_buy_at + home * (1 - a.selling_cost_pct) - bal - hst)
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
        inc_v.append(income_m)
        cb_v.append(contrib_buy)
        cr_v.append(contrib_rent)

    breakeven = sustained_crossing([b - r for b, r in zip(nwbl_v, nwrl_v)])

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
        home_sale_tax=hst_v,
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
        (home_value × (1 − selling_cost_pct) − loan_balance − home-sale tax)
        are injected into the liquid portfolio and the owner becomes a renter
        at the then-current market rent.  Home-sale tax uses the same rule as
        simulate(): gain above basis (price + eligible closing costs), less the Sec. 121
        exclusion if months held (= sale_month) >= 24, times cap_gains_rate.
        The runway clock continues until this combined portfolio also depletes.

    sale_month: month the house was sold (None if the owner never ran out
        of cash while owning).
    sale_proceeds: net after-tax proceeds added to the portfolio at sale_month (None
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
    down = a.down_payment
    if not 0 <= down <= a.price:
        raise ValueError("Financing amount exceeds purchase price or is negative")
    upfront = a.cash_to_close

    loan0 = a.price - down
    pay = monthly_payment(loan0, a.mortgage_rate, a.term_years)
    r_m = a.mortgage_rate / 12

    # --- Shared investment growth ---
    g_inv, income_rate = monthly_portfolio_rates(a)
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
            if loan0 > 0 and down < a.price * 0.20 and (bal / a.price) > 0.78:
                pmi = bal * a.pmi_rate / 12

            prop_tax = assessed * a.property_tax_rate / 12
            insurance = home * a.insurance_rate / 12
            maintenance = home * a.maintenance_rate / 12

            # No interest-deduction benefit (no income to deduct against)
            gross_cost_buy = payment + prop_tax + insurance + maintenance + a.hoa_monthly + pmi + extra_monthly
            # Income offsets the gross cost; a negative need is invested
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
            basis_buy += liq_buy * income_rate
            liq_buy *= 1 + g_inv
            if need_buy <= 0:
                # Net property income left after bills is new investment capital.
                liq_buy -= need_buy
                basis_buy -= need_buy
            else:
                if liq_buy > 0:
                    gain_frac = max(0.0, 1.0 - basis_buy / liq_buy)
                    sell_buy = need_buy / (1.0 - a.cap_gains_rate * gain_frac)
                else:
                    sell_buy = need_buy

                if sell_buy > liq_buy and not sold_house:
                    # Liquidate the existing portfolio, paying tax only on its gains.
                    cash = liq_buy - max(0.0, liq_buy - basis_buy) * a.cap_gains_rate
                    proceeds = (home * (1.0 - a.selling_cost_pct) - bal
                                - home_sale_tax(a, home, m))
                    sale_month = m
                    sale_proceeds_val = proceeds
                    sold_house = True
                    # The month-end loan balance already reflects this month's
                    # payment. Settle the owner's full bill before investing the
                    # remaining after-tax cash. Rent begins next month.
                    liq_buy = max(0.0, cash + proceeds - need_buy)
                    basis_buy = liq_buy
                    if liq_buy == 0:
                        depleted_buy_month = m

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
            basis_rent += liq_rent * income_rate
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


def breakeven_rents(a: Assumptions, max_rent: int = 50_000):
    """Whole-dollar starting rents, with every other assumption held fixed.

    Return the first rent where buying matches or beats renting at the horizon,
    the interval where the last month is the first sustained crossing, and all
    intervals where the portfolios actually deplete in the same month.
    """
    rents = range(max_rent + 1)

    def first_buy_win(month):
        def gap(rent):
            r = simulate(replace(a, monthly_rent=rent))
            return r.net_worth_buy_liq[month] - r.net_worth_rent_liq[month]

        # Higher rent increases buy-side contributions or reduces rent-side ones.
        return bisect_left(rents, 0, key=gap)

    horizon = a.horizon_years * 12
    first = first_buy_win(horizon)
    final_month_band = None
    if first <= max_rent:
        # A sustained crossing starts in the last month exactly when the
        # preceding month is negative and the final month is nonnegative.
        upper = first_buy_win(horizon - 1) - 1
        if upper >= first:
            final_month_band = (first, upper)

    @cache
    def depletion_months(rent):
        r = runway(replace(a, monthly_rent=rent))
        # Infinity denotes a censored observation, never an observed tie.
        return (r.depleted_buy_month or float("inf"), r.depleted_rent_month or float("inf"))

    ties = []

    def collect_ties(low, high):
        # Each portfolio's depletion month can only move earlier as rent
        # rises. The owner's sale month is independent of comparable rent.
        # The difference need not be monotone, so retain disjoint tie bands.
        buy_low, rent_low = depletion_months(low)
        buy_high, rent_high = depletion_months(high)
        if buy_high > rent_low or rent_high > buy_low:
            return
        if buy_low == buy_high and rent_low == rent_high:
            if buy_low == rent_low and buy_low != float("inf"):
                if ties and ties[-1][1] + 1 == low:
                    ties[-1] = (ties[-1][0], high)
                else:
                    ties.append((low, high))
            return
        mid = (low + high) // 2
        collect_ties(low, mid)
        collect_ties(mid + 1, high)

    collect_ties(0, max_rent)
    return first if first <= max_rent else None, final_month_band, ties
