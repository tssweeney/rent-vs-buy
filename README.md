# Rent vs. Buy

A Streamlit dashboard that compares buying a home with renting a comparable one and
investing the difference. It answers three questions:

1. **Wealth** — where does my net worth end up at the horizon, after selling costs and
   taxes, and when does buying stay ahead through the selected horizon?
2. **Cash flow** — what does each month cost me as an owner vs. a renter?
3. **Retirement** — without earned income, how long does my portfolio last paying housing costs
   (and when would I be forced to sell the house)?

[Open the hosted dashboard on Streamlit](https://rent-vs-buy-zkayae2krysdjweasvgqpv.streamlit.app/).

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
- **Charts** — secondary cards, net-worth composition and the investment-return
  sensitivity.

## Key modeling assumptions

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
  insurance generally qualify. Loan origination fees are excluded. All closing costs use cash.
  Gain = value × (1 − selling costs) − basis. The §121 exclusion is $250k (Single) or
  $500k (Married), set by the **Filing status** control, and applies only after 24 months
  of assumed primary residence, assuming the other eligibility tests are met (partial exclusions ignored). Gain above it is taxed at the capital-gains
  rate. The retirement forced sale uses the same rule. [IRS Publication 523](https://www.irs.gov/publications/p523)
- **Breakevens** mean "gets ahead and stays ahead through the horizon"; a scenario that
  pulls ahead and later falls behind shows "never".
- **Monthly cost** on the Overview and Explorer is gross (before the mortgage-interest
  deduction); the deduction (marginal rate × interest on up to $750k of balance, assuming
  you itemize) is counted in net worth. Set the marginal rate to match your filing status.
- **Prop 13:** property tax grows 2%/yr on the assessed value; insurance and maintenance
  scale with market value. PMI applies below 20% down until 78% LTV.
- **Monthly income** (e.g. ADU rent) is buy-side only, entered net of tax, grows with rent,
  and stops at a forced sale.
- **Retirement runway:** no earned income or interest deduction. Surplus property income is invested. Portfolio withdrawals are grossed up
  for embedded capital-gains tax. If the owner cannot cover a month’s bills, the model
  sells the home at month-end, settles those bills, and starts charging rent the following month.
- All figures are nominal dollars.
