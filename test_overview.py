"""AppTest verification for the Overview tab feature."""
import sys

# pyarrow guard
try:
    import pyarrow  # noqa: F401
except ImportError:
    print("pyarrow not available — skipping AppTest (exit 0)")
    sys.exit(0)

from streamlit.testing.v1 import AppTest

def run_and_check(at, label=""):
    at.run(timeout=60)
    if at.exception:
        print(f"EXCEPTION [{label}]: {at.exception}")
        sys.exit(1)

# --- Initial run ---
at = AppTest.from_file("app.py")
run_and_check(at, "initial run")

# Check tab labels
tabs = at.tabs
tab_labels = [t.label for t in tabs]
expected = ["Overview", "Single scenario", "Scenario Explorer", "Details", "Methodology", "Runway"]
assert tab_labels == expected, f"Tab labels mismatch: {tab_labels}"
print(f"Tab labels OK: {tab_labels}")

# --- Sidebar: down_pct → 100 (monthly-cost breakeven should be immediate) ---
at.sidebar.slider[1].set_value(100)  # down_pct slider (index 1 in sidebar sliders)
run_and_check(at, "down_pct=100")

# --- price → 1_200_000 ---
at.sidebar.number_input[0].set_value(1_200_000)
run_and_check(at, "price=1200000")

# --- extra_spend → 5_000 ---
# extra_spend is a number_input with key "extra_spend"
at.number_input(key="extra_spend").set_value(5_000)
run_and_check(at, "extra_spend=5000")

print("All AppTest checks passed.")
sys.exit(0)
