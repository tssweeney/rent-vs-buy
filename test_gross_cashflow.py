"""AppTest: gross cash-flow figures + per-category down-payment optimization charts.

Checks (per task spec):
1. 6 tabs with correct labels (unchanged).
2. No exception on initial run.
3. No exception after price -> 1_200_000, down_pct -> 100, down_pct -> 3 reruns.
"""
import sys

# pyarrow guard
try:
    import pyarrow  # noqa: F401
except ImportError:
    print("pyarrow not available — skipping AppTest (exit 0)")
    sys.exit(0)

from streamlit.testing.v1 import AppTest

EXPECTED_TABS = [
    "Overview", "Single scenario", "Scenario Explorer",
    "Calculations", "Runway", "Charts",
]


def _run(at, label=""):
    at.run(timeout=120)
    if at.exception:
        print(f"EXCEPTION [{label}]: {at.exception}")
        sys.exit(1)


# ---- initial run ----
at = AppTest.from_file("app.py", default_timeout=120)
_run(at, "initial run")

tab_labels = [t.label for t in at.tabs]
assert tab_labels == EXPECTED_TABS, f"Tab labels mismatch: {tab_labels}"
print(f"PASS: 6 tabs — {tab_labels}")

# ---- price -> 1_200_000 ----
at.number_input(key="price").set_value(1_200_000)
_run(at, "price=1200000")
print("PASS: no exception after price=1_200_000")

# ---- down_pct -> 100 ----
at.slider(key="down_pct").set_value(100)
_run(at, "down_pct=100")
print("PASS: no exception after down_pct=100")

# ---- down_pct -> 3 ----
at.slider(key="down_pct").set_value(3)
_run(at, "down_pct=3")
print("PASS: no exception after down_pct=3")

print("All AppTest checks PASSED.")
sys.exit(0)
