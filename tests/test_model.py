"""Invariants of the rent-vs-buy simulation (no pinned magic numbers)."""

import itertools
import math
from dataclasses import replace

import pytest

from model import (
    Assumptions,
    cashflow_breakeven_month,
    home_sale_tax,
    rent_from_price,
    runway,
    simulate,
    sustained_crossing,
)

BASE = Assumptions(monthly_rent=rent_from_price(1_400_000, 28))


def _close(x, y, tol=1e-6):
    return math.isclose(x, y, rel_tol=1e-9, abs_tol=tol)


def test_net_worth_identity_every_month():
    r = simulate(BASE)
    s = BASE.selling_cost_pct
    for pb, h, b, t, nw in zip(r.portfolio_buy_after_tax, r.home_value, r.loan_balance,
                               r.home_sale_tax, r.net_worth_buy_liq):
        assert _close(pb + h * (1 - s) - b - t, nw)
    for pr, nw in zip(r.portfolio_rent_after_tax, r.net_worth_rent_liq):
        assert _close(pr, nw)
    # mark-to-market stays untaxed
    for pb, h, b, nw in zip(r.portfolio_buy, r.home_value, r.loan_balance, r.net_worth_buy):
        assert _close(pb + h - b, nw)


@pytest.mark.parametrize("a", [
    BASE,
    replace(BASE, down_pct=0.05, monthly_income=1_500),
    replace(BASE, include_interest_deduction=False, term_years=15),
])
def test_outflow_components_identity(a):
    r = simulate(a)
    for m in range(len(r.months)):
        total = (r.payment_m[m] + r.prop_tax_m[m] + r.insurance_m[m] + r.maintenance_m[m]
                 + r.hoa_m[m] + r.pmi_m[m] - r.tax_benefit_m[m] - r.income_m[m])
        assert _close(total, r.outflow_buy[m])


def test_zero_monthly_income_equals_default():
    r0 = simulate(BASE)
    r1 = simulate(replace(BASE, monthly_income=0.0))
    assert r0 == r1


def test_breakeven_reversal_returns_never():
    # Buying pulls ahead early but falls behind by the horizon.
    a = replace(BASE, down_pct=0.10, alt_return_annual=0.10, horizon_years=30,
                monthly_rent=rent_from_price(1_400_000, 20))
    r = simulate(a)
    diffs = [b - x for b, x in zip(r.net_worth_buy_liq, r.net_worth_rent_liq)]
    assert any(d >= 0 for d in diffs[1:]), "fixture should cross at some point"
    assert diffs[-1] < 0
    assert r.breakeven_month == -1


def test_breakeven_stays_ahead_when_found():
    r = simulate(BASE)
    be = r.breakeven_month
    assert be > 0
    assert all(r.net_worth_buy_liq[m] >= r.net_worth_rent_liq[m]
               for m in range(be, len(r.months)))
    assert r.net_worth_buy_liq[be - 1] < r.net_worth_rent_liq[be - 1] or be == 1


def test_sustained_crossing_helper():
    assert sustained_crossing([0, -1, 1, -1, 2, 3]) == 4
    assert sustained_crossing([0, 1, 2]) == 1
    assert sustained_crossing([0, 1, -1]) == -1
    assert sustained_crossing([0]) == -1


def test_cashflow_breakeven_stays_at_or_below_rent():
    a = replace(BASE, horizon_years=30, mortgage_rate=0.03)
    r = simulate(a)
    m = cashflow_breakeven_month(r)
    assert m > 0
    for k in range(m, len(r.months)):
        assert r.outflow_buy[k] + r.tax_benefit_m[k] <= r.outflow_rent[k]
    assert r.outflow_buy[m - 1] + r.tax_benefit_m[m - 1] > r.outflow_rent[m - 1] or m == 1


def test_home_sale_tax_zero_when_gain_within_exclusion():
    a = replace(BASE, home_appreciation=0.02, horizon_years=10)
    r = simulate(a)
    gain = r.home_value[-1] * (1 - a.selling_cost_pct) - a.price * (1 + a.closing_buy_pct * a.closing_basis_share)
    assert 0 < gain <= a.home_gain_exclusion
    assert r.home_sale_tax[-1] == 0.0


def test_home_sale_tax_matches_formula_at_default():
    r = simulate(BASE)
    gain = r.home_value[-1] * (1 - BASE.selling_cost_pct) - BASE.price * (1 + BASE.closing_buy_pct * BASE.closing_basis_share)
    expected = max(0.0, gain - BASE.home_gain_exclusion) * BASE.cap_gains_rate
    assert expected > 0
    assert _close(r.home_sale_tax[-1], expected)
    untaxed = simulate(replace(BASE, home_gain_exclusion=1e12))
    assert _close(untaxed.net_worth_buy_liq[-1] - r.net_worth_buy_liq[-1], r.home_sale_tax[-1])


def test_no_exclusion_before_24_months():
    a = replace(BASE, home_appreciation=0.10, horizon_years=3, home_gain_exclusion=500_000)
    r = simulate(a)
    for m in (12, 23):
        gain = r.home_value[m] * (1 - a.selling_cost_pct) - a.price * (1 + a.closing_buy_pct * a.closing_basis_share)
        assert gain > 0
        assert _close(r.home_sale_tax[m], gain * a.cap_gains_rate)
        assert _close(home_sale_tax(a, r.home_value[m], m), r.home_sale_tax[m])
    assert r.home_sale_tax[24] == 0.0   # gain now inside the exclusion


def test_married_exclusion_reduces_tax():
    single = simulate(BASE)
    married = simulate(replace(BASE, home_gain_exclusion=500_000))
    assert married.home_sale_tax[-1] < single.home_sale_tax[-1]
    assert married.net_worth_buy_liq[-1] > single.net_worth_buy_liq[-1]


def test_runway_proceeds_reduced_by_home_sale_tax():
    taxed = runway(BASE)
    untaxed = runway(replace(BASE, home_gain_exclusion=1e12))
    assert taxed.sale_month is not None and taxed.sale_month == untaxed.sale_month
    m = taxed.sale_month
    g_home = (1 + BASE.home_appreciation) ** (1 / 12) - 1
    home_at_sale = BASE.price * (1 + g_home) ** m
    expected_tax = home_sale_tax(BASE, home_at_sale, m)
    assert expected_tax > 0
    assert math.isclose(untaxed.sale_proceeds - taxed.sale_proceeds, expected_tax, rel_tol=1e-6)


FUZZ = list(itertools.product(
    [0.03, 0.20, 0.50, 1.00],      # down
    [0.0, 0.035, 0.10],            # investment return
    [0.0, 0.055, 0.08],            # appreciation
    [15, 30],                      # term
    [5, 30],                       # horizon
))


@pytest.mark.parametrize("down,ret,appr,term,horizon", FUZZ)
def test_fuzz_no_nan_or_negative_portfolio(down, ret, appr, term, horizon):
    a = replace(BASE, down_pct=down, alt_return_annual=ret, home_appreciation=appr,
                term_years=term, horizon_years=horizon)
    r = simulate(a)
    assert r.feasible
    for series in (r.portfolio_buy, r.portfolio_rent, r.portfolio_buy_after_tax,
                   r.portfolio_rent_after_tax, r.net_worth_buy_liq, r.net_worth_rent_liq,
                   r.home_sale_tax):
        assert all(math.isfinite(v) for v in series)
    for series in (r.portfolio_buy, r.portfolio_rent, r.portfolio_buy_after_tax,
                   r.portfolio_rent_after_tax, r.home_sale_tax):
        assert min(series) >= 0
    w = runway(a)
    assert all(math.isfinite(v) and v >= 0 for v in w.liquid_buy + w.liquid_rent)


@pytest.mark.parametrize("sale_month", [1, 12])
def test_forced_sale_settles_owner_bills_then_rents_next_month(sale_month):
    a = replace(BASE, price=120_000, down_pct=0.5, mortgage_rate=0,
                term_years=10, closing_buy_pct=0, other_onetime_costs=0,
                selling_cost_pct=0, home_appreciation=0, property_tax_rate=0,
                insurance_rate=0, maintenance_rate=0, hoa_monthly=100,
                alt_return_annual=0, monthly_rent=400, rent_growth=0.10,
                capital=60_000 + (sale_month - 1) * 600 + 50)
    w = runway(a, max_years=2)
    assert w.sale_month == sale_month
    assert w.sale_proceeds == 60_000 + 500 * sale_month
    assert w.monthly_need_buy[sale_month] == 600
    assert w.liquid_buy[sale_month] == 50 + w.sale_proceeds - 600
    next_rent = w.monthly_need_rent[sale_month + 1]
    assert w.monthly_need_buy[sale_month + 1] == next_rent
    assert w.liquid_buy[sale_month + 1] == pytest.approx(w.liquid_buy[sale_month] - next_rent)


def test_underwater_forced_sale_reports_shortfall():
    a = replace(BASE, down_pct=0.03, closing_buy_pct=0, other_onetime_costs=0,
                capital=BASE.price * 0.03, home_appreciation=0)
    w = runway(a)
    assert w.sale_month == w.depleted_buy_month == 1
    assert w.sale_proceeds < 0
    assert w.liquid_buy[1] == 0


@pytest.mark.parametrize("income_share", [0.0, 0.4, 1.0])
def test_portfolio_taxes_apply_once_by_source(income_share):
    # No mortgage, no housing bills, no contributions. Each side grows its initial cash.
    a = replace(BASE, down_pct=1, capital=3_000_000, monthly_rent=0,
                property_tax_rate=0, maintenance_rate=0, insurance_rate=0, hoa_monthly=0,
                horizon_years=1, alt_return_annual=0.10, investment_tax_drag=0.30,
                investment_income_share=income_share, cap_gains_rate=0.20)
    r = simulate(a)
    for portfolio, after_tax in [(r.portfolio_buy, r.portfolio_buy_after_tax),
                                 (r.portfolio_rent, r.portfolio_rent_after_tax)]:
        income = portfolio[0] * 0.10 * income_share
        appreciation = portfolio[0] * 0.10 * (1 - income_share)
        expected = portfolio[0] + income * 0.70 + appreciation
        assert portfolio[-1] == pytest.approx(expected)
        assert after_tax[-1] == pytest.approx(expected - appreciation * 0.20)


def test_runway_spends_reinvested_interest_without_another_tax():
    a = replace(BASE, investment_income_share=1.0, investment_tax_drag=0.3)
    w = runway(a, max_years=2)
    untaxed_sale = runway(replace(a, cap_gains_rate=0), max_years=2)
    assert w.sale_month is None
    assert w.liquid_buy == pytest.approx(untaxed_sale.liquid_buy)
    assert w.liquid_rent == pytest.approx(untaxed_sale.liquid_rent)


def test_full_closing_cash_is_paid_with_partial_eligible_basis():
    a = replace(BASE, closing_basis_share=0.4)
    r = simulate(a)
    closing = a.price * a.closing_buy_pct
    assert r.portfolio_buy[0] == a.capital - a.price * a.down_pct - closing - a.other_onetime_costs
    gain = r.home_value[-1] * (1 - a.selling_cost_pct) - a.price - 0.4 * closing
    assert r.home_sale_tax[-1] == pytest.approx((gain - a.home_gain_exclusion) * a.cap_gains_rate)


def test_runway_invests_property_income_left_after_owner_costs():
    w = runway(replace(BASE, monthly_income=20_000, alt_return_annual=0), max_years=1)
    assert w.monthly_need_buy[1] < 0
    assert w.liquid_buy[1] == pytest.approx(w.liquid_buy[0] - w.monthly_need_buy[1])
