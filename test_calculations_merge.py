"""AppTest: verify the Details+Methodology → Calculations merge."""
import sys

try:
    import pyarrow  # noqa: F401
except ImportError:
    sys.exit(139)

from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=60)
at.run()
assert not at.exception, f"App raised exception on initial run: {at.exception}"

# 1. Exactly 5 tabs with the right labels
tab_labels = [t.label for t in at.tabs]
expected = ["Overview", "Single scenario", "Scenario Explorer", "Calculations", "Runway"]
assert tab_labels == expected, f"Expected {expected}, got {tab_labels}"

# 2. LaTeX blocks still render
assert len(at.latex) >= 6, f"Expected >= 6 latex blocks, got {len(at.latex)}"

# 3. Rerun after sidebar price → 1_200_000 and down_pct → 100
at.session_state["price"] = 1_200_000
at.session_state["down_pct"] = 100
at.run()
assert not at.exception, f"App raised exception after price/down_pct change: {at.exception}"

print("All assertions passed.")
