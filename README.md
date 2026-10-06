# Rent vs. Buy

A Streamlit dashboard that compares buying a home with renting a comparable one and
investing the difference. It answers three questions:

1. **Wealth** — where does my net worth end up at the horizon, after selling costs and
   taxes, and when does buying pull ahead for good?
2. **Cash flow** — what does each month cost me as an owner vs. a renter?
3. **Retirement** — with no income, how long does my portfolio last paying housing costs
   (and when would I be forced to sell the house)?

## Run it

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
  month-by-month trace that reconciles with every chart.
- **Charts** — secondary cards, net-worth composition and the investment-return
  sensitivity.

## Key modeling assumptions

- **Fair comparison:** both scenarios spend the same total each month; whichever has the
  lower housing cost invests the difference.
- **"If sold" net worth** is the headline basis. Buy = after-tax portfolio + home value ×
  (1 − selling costs) − loan balance − home-sale tax. Rent = after-tax portfolio.
- **Portfolio taxes:** optional annual drag, plus capital-gains tax on gains above
  contributions in every "if sold" figure.
- **Home-sale tax:** basis = price + closing costs (one-time/moving costs are not basis).
  Gain = value × (1 − selling costs) − basis. The §121 exclusion is $250k (Single) or
  $500k (Married), set by the **Filing status** control, and applies only after 24 months
  of ownership (partial exclusions ignored). Gain above it is taxed at the capital-gains
  rate. The retirement forced sale uses the same rule.
- **Breakevens** mean "gets ahead and stays ahead through the horizon"; a scenario that
  pulls ahead and later falls behind shows "never".
- **Monthly cost** on the Overview and Explorer is gross (before the mortgage-interest
  deduction); the deduction (marginal rate × interest on up to $750k of balance, assuming
  you itemize) is counted in net worth. Set the marginal rate to match your filing status.
- **Prop 13:** property tax grows 2%/yr on the assessed value; insurance and maintenance
  scale with market value. PMI applies below 20% down until 78% LTV.
- **Monthly income** (e.g. ADU rent) is buy-side only, entered net of tax, grows with rent,
  and stops at a forced sale.
- **Retirement runway:** no income, so no interest deduction; withdrawals are grossed up
  for embedded capital-gains tax.
- All figures are nominal dollars.
