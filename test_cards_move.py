"""AppTest verification: six secondary cards moved from Overview to Charts tab."""
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

# 1. Check tab count and labels
tabs = at.tabs
tab_labels = [t.label for t in tabs]
expected_labels = ["Overview", "Single scenario", "Scenario Explorer", "Calculations", "Runway", "Charts"]
assert tab_labels == expected_labels, f"Tab labels mismatch: {tab_labels}"
print(f"Tab labels OK: {tab_labels}")

# 2. Check moved card labels: each must appear in the Charts (tab5) section
#    and must NOT appear in the Overview (tab0) section of app.py source.
with open("app.py") as f:
    src = f.read()

# Extract the Overview (tab0) section: from "with tab0:" up to "# ================================================================ tab 3"
tab0_start = src.index("with tab0:")
tab0_end = src.index("# ================================================================ tab 3")
tab0_src = src[tab0_start:tab0_end]

# Extract the Charts (tab5) section: from "with tab5:" to end of file
tab5_start = src.index("with tab5:")
tab5_src = src[tab5_start:]

moved_labels = [
    "Cash at closing",
    "Reserve after closing",
    "Interest deduction (mo 1)",
    "Principal portion (mo 1)",
    "Buy burn (mo 1)",
    "Rent burn (mo 1)",
]
for label in moved_labels:
    # Must NOT be in Overview tab source
    assert label not in tab0_src, f'Label "{label}" still found in Overview (tab0) source!'
    # Must be in Charts tab source
    assert label in tab5_src, f'Label "{label}" not found in Charts (tab5) source!'
    print(f'  Label "{label}": absent from Overview, present in Charts — OK')

# --- Sidebar rerun: price → 1_200_000 ---
at.sidebar.number_input(key="price").set_value(1_200_000)
run_and_check(at, "price=1200000")
print("Rerun with price=1_200_000: OK")

# --- Sidebar rerun: down_pct → 100 ---
at.sidebar.slider(key="down_pct").set_value(100)
run_and_check(at, "down_pct=100")
print("Rerun with down_pct=100: OK")

print("All AppTest checks passed.")
sys.exit(0)
