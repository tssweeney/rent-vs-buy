"""AppTest verification for the unified Overview tab."""
import sys

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
print("Initial run: OK")

# 2. Six tabs, correct labels
tabs = at.tabs
tab_labels = [t.label for t in tabs]
expected = ["Overview", "Single scenario", "Scenario Explorer", "Calculations", "Runway", "Charts"]
assert tab_labels == expected, f"Tab labels mismatch: {tab_labels}"
print(f"Tab labels OK: {tab_labels}")

# 3. Sidebar price → 1_200_000
at.sidebar.number_input[0].set_value(1_200_000)
run_and_check(at, "price=1200000")
print("price=1_200_000 rerun: OK")

# 4. Sidebar down_pct → 100
at.sidebar.slider[0].set_value(100)
run_and_check(at, "down_pct=100")
print("down_pct=100 rerun: OK")

# 5. "Where does my net worth end up?" appears exactly once in source
with open("app.py") as f:
    src = f.read()
count = src.count("Where does my net worth end up?")
assert count == 1, f"'Where does my net worth end up?' appears {count} times in source (expected 1)"
print(f"Single render site check OK: count={count}")

print("All AppTest checks passed.")
sys.exit(0)
