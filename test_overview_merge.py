"""AppTest verification for Overview merge.

Checks:
1. 5 tabs with correct labels.
2. No exception on initial run.
3. No exception after price -> 1_200_000, down_pct -> 100 (infeasible), down_pct -> 3.
4. Same key metric values appear in both Overview and Single scenario.
"""
import sys

try:
    import pyarrow  # noqa: F401
except ImportError:
    print("pyarrow not available — skipping AppTest (pyarrow guard)")
    sys.exit(0)

from streamlit.testing.v1 import AppTest


def test_tabs():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"Exception on initial run: {at.exception}"
    tab_labels = [t.label for t in at.tabs]
    assert tab_labels == ["Overview", "Single scenario", "Scenario Explorer", "Calculations", "Runway"], \
        f"Unexpected tab labels: {tab_labels}"
    print("PASS: 5 tabs with correct labels")


def test_no_exception_initial():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"Exception on initial run: {at.exception}"
    print("PASS: no exception on initial run")


def test_infeasible_high_down():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    # price key = "price" (number_input)
    at.number_input(key="price").set_value(1_200_000)
    at.run()
    assert not at.exception, f"Exception after price=1_200_000: {at.exception}"
    # Push down_pct to 100 (infeasible: 1_200_000 > capital 1_500_000 when closing+onetime added)
    at.slider(key="down_pct").set_value(100)
    at.run()
    assert not at.exception, f"Exception after down_pct=100: {at.exception}"
    print("PASS: no exception with down_pct=100 (infeasible scenario)")


def test_low_down():
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    at.slider(key="down_pct").set_value(3)
    at.run()
    assert not at.exception, f"Exception after down_pct=3: {at.exception}"
    print("PASS: no exception with down_pct=3")


def test_metrics_consistent():
    """Overview and Single scenario tabs should show the same net worth values."""
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"Exception: {at.exception}"

    all_metrics = at.metric
    # Collect all metric values by label
    metric_map = {}
    for m in all_metrics:
        lbl = m.label
        val = m.value
        if lbl not in metric_map:
            metric_map[lbl] = []
        metric_map[lbl].append(val)

    # "Buy net worth (yr X)" should appear in both Overview (Wealth section) and Single scenario
    buy_nw_keys = [k for k in metric_map if k.startswith("Buy net worth")]
    assert buy_nw_keys, "No 'Buy net worth' metric found"
    for k in buy_nw_keys:
        vals = metric_map[k]
        assert len(vals) >= 2, f"Expected 'Buy net worth' to appear in at least 2 places, got {len(vals)}: {vals}"
        # All instances should have the same value
        assert len(set(vals)) == 1, f"Inconsistent 'Buy net worth' values across tabs: {vals}"

    # "Rent net worth (yr X)" similarly
    rent_nw_keys = [k for k in metric_map if k.startswith("Rent net worth")]
    assert rent_nw_keys, "No 'Rent net worth' metric found"
    for k in rent_nw_keys:
        vals = metric_map[k]
        assert len(vals) >= 2, f"Expected 'Rent net worth' to appear in at least 2 places, got {len(vals)}: {vals}"
        assert len(set(vals)) == 1, f"Inconsistent 'Rent net worth' values across tabs: {vals}"

    print("PASS: Overview and Single scenario show consistent net worth values")
    print(f"  Buy net worth labels found: {buy_nw_keys}")
    print(f"  Rent net worth labels found: {rent_nw_keys}")


if __name__ == "__main__":
    test_tabs()
    test_no_exception_initial()
    test_infeasible_high_down()
    test_low_down()
    test_metrics_consistent()
    print("\nAll tests PASSED")
