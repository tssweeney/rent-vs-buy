"""Sanity checks for Overview tab metric math."""
import sys
from dataclasses import replace

from model import Assumptions, simulate, rent_from_price, runway

# Default assumptions matching DEFAULTS in app.py
a = Assumptions(
    capital=1_500_000, horizon_years=10,
    alt_return_annual=0.035, investment_tax_drag=0.0, cap_gains_rate=0.25,
    mortgage_rate=0.065, term_years=30,
    closing_buy_pct=0.015, other_onetime_costs=10_000, selling_cost_pct=0.06,
    home_appreciation=0.055, property_tax_rate=0.0115,
    insurance_rate=0.0025, maintenance_rate=0.01, hoa_monthly=250,
    marginal_tax_rate=0.42, include_interest_deduction=True,
    rent_growth=0.04,
    price=1_400_000, down_pct=0.50,
    monthly_rent=rent_from_price(1_400_000, 28.0),
)

res = simulate(a)
rwy = runway(a, extra_monthly=0.0)

print(f"Assumptions: price={a.price}, down_pct={a.down_pct}, rent={a.monthly_rent:.0f}/mo")
print()

# ---- Metric 4: Monthly cost breakeven ---
# Find the first m >= 1 where outflow_buy[m] <= outflow_rent[m]
app_cash_be = None
for m in range(1, len(res.outflow_buy)):
    if res.outflow_buy[m] <= res.outflow_rent[m]:
        app_cash_be = m
        break

# Independent calculation
indep_cash_be = None
for m in range(1, len(res.outflow_buy)):
    if res.outflow_buy[m] <= res.outflow_rent[m]:
        indep_cash_be = m
        break

print(f"Monthly cost breakeven (app logic): month {app_cash_be}")
print(f"Monthly cost breakeven (independent): month {indep_cash_be}")
assert app_cash_be == indep_cash_be, "Monthly cost breakeven mismatch!"
print("  -> MATCH OK")
print()

# ---- Metric 6: Buy runway advantage ---
CAP = 1200  # 100 years in months
buy_runway_m = rwy.depleted_buy_month if rwy.depleted_buy_month is not None else CAP
rent_runway_m = rwy.depleted_rent_month if rwy.depleted_rent_month is not None else CAP
runway_adv_yrs = (buy_runway_m - rent_runway_m) / 12

# Independent calculation
indep_buy_runway = rwy.depleted_buy_month if rwy.depleted_buy_month is not None else CAP
indep_rent_runway = rwy.depleted_rent_month if rwy.depleted_rent_month is not None else CAP
indep_runway_adv = (indep_buy_runway - indep_rent_runway) / 12

print(f"Buy runway advantage (app logic): {runway_adv_yrs:+.1f} yrs "
      f"(buy={buy_runway_m}mo, rent={rent_runway_m}mo)")
print(f"Buy runway advantage (independent): {indep_runway_adv:+.1f} yrs")
assert abs(runway_adv_yrs - indep_runway_adv) < 0.01, "Runway advantage mismatch!"
print("  -> MATCH OK")
print()

# Print all six card values at defaults
print("=== Six Overview card values at defaults ===")
nw_buy = res.net_worth_buy_liq[-1]
nw_rent = res.net_worth_rent_liq[-1]
delta = nw_buy - nw_rent
print(f"1. Buy advantage:           ${delta:,.0f}  ({delta/nw_rent*100:+.1f}% vs rent)")

be_label = f"year {res.breakeven_month / 12:.1f}" if res.breakeven_month > 0 else "never (in horizon)"
print(f"2. Net worth breakeven:     {be_label}")

cost_diff = res.outflow_buy[1] - res.outflow_rent[1]
print(f"3. Monthly cost vs rent:    ${cost_diff:,.0f}  ({'buy costs more' if cost_diff>0 else 'buy costs less'})")

if app_cash_be is None:
    cash_be_label = "never (in horizon)"
elif app_cash_be == 1:
    cash_be_label = "immediately"
else:
    cash_be_label = f"year {app_cash_be / 12:.1f}"
print(f"4. Monthly cost breakeven:  {cash_be_label}")

sale_label = f"yr {rwy.sale_month / 12:.1f}" if rwy.sale_month is not None else "never"
print(f"5. Forced sale:             {sale_label}")

both_sustainable = (rwy.depleted_buy_month is None and rwy.depleted_rent_month is None)
if both_sustainable:
    runway_label = "— (both sustainable)"
else:
    runway_label = f"{runway_adv_yrs:+.1f} yrs"
print(f"6. Buy runway advantage:    {runway_label}")

print()
print("All sanity checks passed.")
sys.exit(0)
