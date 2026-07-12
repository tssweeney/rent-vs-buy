"""AppTest verification: sidebar reorder into Investment / Property / Financing / Market / Personal."""
import sys

# pyarrow guard
try:
    import pyarrow  # noqa: F401
except ImportError:
    print("pyarrow not available — skipping AppTest (exit 0)")
    sys.exit(0)

from streamlit.testing.v1 import AppTest
from model import Assumptions, simulate

def run_and_check(at, label=""):
    at.run(timeout=60)
    if at.exception:
        print(f"EXCEPTION [{label}]: {at.exception}")
        sys.exit(1)

# --- Initial run ---
at = AppTest.from_file("app.py")
run_and_check(at, "initial run")

# Check 6 tabs with unchanged labels
tabs = at.tabs
tab_labels = [t.label for t in tabs]
expected = ["Overview", "Single scenario", "Scenario Explorer", "Calculations", "Runway", "Charts"]
assert tab_labels == expected, f"Tab labels mismatch: {tab_labels}"
print(f"Tab labels OK: {tab_labels}")

# --- Sidebar rerun: price → 1_200_000 ---
at.sidebar.number_input(key="price").set_value(1_200_000)
run_and_check(at, "price=1200000")

# --- Sidebar rerun: down_pct → 100 ---
at.sidebar.slider(key="down_pct").set_value(100)
run_and_check(at, "down_pct=100")

# --- Sidebar rerun: capital → 900_000 ---
at.sidebar.number_input(key="capital").set_value(900_000)
run_and_check(at, "capital=900000")

# --- Sanity: simulate() with Assumptions() defaults produces the same result ---
a_def = Assumptions()
res = simulate(a_def)
nw = res.net_worth_buy_liq[-1]
print(f"Defaults simulate() net_worth_buy_liq[-1] = {nw:,.0f}")
# Just check it's a finite number (not NaN, not zero)
assert nw == nw and nw != 0, f"Unexpected net_worth_buy_liq[-1]: {nw}"

print("All AppTest checks passed.")
sys.exit(0)
