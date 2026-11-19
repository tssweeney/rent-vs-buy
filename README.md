# Rent vs. Buy

A Streamlit dashboard that compares buying a home with renting a comparable one and
investing the difference. It answers three questions:

1. **Wealth** — where does my net worth end up at the horizon, after selling costs and
   taxes, and when does buying stay ahead through the selected horizon?
2. **Cash flow** — what does each month cost me as an owner vs. a renter?
3. **Retirement** — without earned income, how long does my portfolio last paying housing costs
   (and when would I be forced to sell the house)?

[Open the hosted dashboard on Streamlit](https://rent-vs-buy-zkayae2krysdjweasvgqpv.streamlit.app/).

Use **Copy share link** in the sidebar to copy a snapshot of the current settings, including financial inputs. Anyone with the link can reopen that scenario. Links from the hosted dashboard open the public app.

## Run locally

```sh
uv sync
uv run streamlit run app.py
```

The app opens at http://localhost:8501. Streamlit hot-reloads `app.py` on save, but
**changes to `model.py` need a server restart** (stop it and run the command again).

## Tests

```sh
uv run pytest
```

`tests/test_model.py` checks model invariants (net-worth and cost identities, home-sale
tax rules, breakeven semantics, a fuzz grid for NaN/negative values).
`tests/test_app.py` runs the app headlessly with `streamlit.testing.v1.AppTest` across
edge-case inputs.

## Tabs

- **Overview** — the three questions side by side: buy advantage and net-worth breakeven;
  month-1 cost vs. rent and cash-flow breakeven; forced-sale year and runway. Each column
  has a chart and a "best down payment" curve.
- **Scenario Explorer** — pick any two inputs and see heatmaps of buy advantage,
  breakeven, month-1 cost and buy runway, plus the best value per row.
- **Calculations** — the formulas, a worked example at your inputs, and a downloadable
  month-by-month trace for the selected wealth and monthly cash-flow scenario.
- **Supplemental Analysis** — secondary cards, net-worth composition and the investment-return
  sensitivity.
- **Assumptions** — current scenario inputs and fixed modeling rules, with separate columns for the formula, first-year value, and comment.

The Overview also shows the lowest tested annual appreciation at which buying finishes
at least even after sale at the selected horizon. It checks −10% to +10% in quarter-point
steps. Expand **Which assumptions change the decision?** for a ranked, one-input-at-a-time
comparison, sale outcomes at 2, 5, and 10 years, and a two-year downside scenario. The
ranking measures the dollar impact of the changes shown, rather than their likelihood.

**Break-even rent by outcome** treats starting monthly rent as an output. The Overview
compares your rent with the lowest whole-dollar rent where buying matches or beats
renting at the horizon. Expand the details for rents where the sustained wealth
breakeven first occurs in the final month, both housing portfolios deplete in the
same month, or month-one housing outflows match. The wealth and runway search covers
$0–$50,000/month with all other assumptions fixed. Runway ties can span several
disjoint ranges. Two portfolios still funded at year 100 have no observed depletion date.

## Key modeling assumptions

- **Financing** defaults to a fixed $750,000 loan. You can also fix the cash down payment or its percentage of purchase price. Price sweeps preserve the selected mode unless you explicitly sweep the down payment percentage.
- **Seller concessions** are an optional dollar credit toward closing fees. Enter gross fees and the lender-approved credit separately. The model caps the applied credit at gross fees. The tax-basis percentage applies to fees the buyer pays after the credit. Rate buydowns and price reductions are separate deal terms. [CFPB Loan Estimate guide](https://www.consumerfinance.gov/owning-a-home/loan-estimate/)
- **Starting capital** is cash already available after tax. Later investment gains follow the portfolio tax settings.
- **Fair comparison:** both scenarios spend the same total each month; whichever has the
  lower housing cost invests the difference.
- **"If sold" net worth** is the headline basis. Buy = after-tax portfolio + home value ×
  (1 − selling costs) − loan balance − home-sale tax. Rent = after-tax portfolio.
- **Portfolio taxes:** set the share of investment return paid as income and its tax rate.
  Reinvested after-tax income increases portfolio basis. The remaining appreciation is
  taxed when sold. The default models deferred appreciation. For a savings account, use
  a 100% income share and enter the tax rate on interest. [IRS Publication 550](https://www.irs.gov/publications/p550)
- **Home-sale tax:** basis = price + the eligible share of closing costs. The default eligible share is
  0% until you enter an estimate from the closing statement. Recording fees and owner’s title
  insurance generally qualify. Loan origination fees are excluded. Buyer-paid fees use cash.
  Gain = value × (1 − selling costs) − basis. The §121 exclusion is $250k (Single) or
  $500k (Married), set by the **Filing status** control, and applies only after 24 months
  of assumed primary residence, assuming the other eligibility tests are met (partial exclusions ignored). Gain above it is taxed at the capital-gains
  rate. The retirement forced sale uses the same rule. [IRS Publication 523](https://www.irs.gov/publications/p523)
- **Breakevens** mean "gets ahead and stays ahead through the horizon"; a scenario that
  pulls ahead and later falls behind shows "never".
- **Monthly cost** excludes the mortgage-interest deduction. Wealth calculations estimate it monthly
  from the opening balance of one qualifying purchase loan, assuming itemization. For single or
  married filing jointly, the model caps eligible debt at $750,000 federally and $1 million for
  California. The editable illustrative marginal rates are 32% federal and 10% California.
  The optional annual tax savings limit applies to their combined benefit.
  [IRS Publication 936](https://www.irs.gov/publications/p936) ·
  [California Schedule CA instructions](https://www.ftb.ca.gov/forms/2025/2025-540-ca-instructions.html)
- **Prop 13:** property tax grows 2%/yr on the assessed value; insurance and maintenance
  scale with market value. PMI applies below 20% down until 78% LTV.
- **Monthly income** (e.g. ADU rent) is buy-side only, entered net of tax, grows with rent,
  and stops at a forced sale.
- **Retirement runway** measures housing costs alone. Other living expenses are paid separately. The model assumes no earned income or interest deduction. Surplus property income is invested. Portfolio withdrawals are grossed up
  for embedded capital-gains tax. If the owner cannot cover a month’s bills, the model
  sells the home at month-end, settles those bills, and starts charging rent the following month.
- All figures are nominal dollars.
