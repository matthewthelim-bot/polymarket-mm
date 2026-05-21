import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.scan_markets import compute_score


def test_score_zero_when_no_quotable():
    assert compute_score(50000.0, 0.0, 0.1) == 0.0


def test_score_zero_when_no_volatility():
    # std=0 → volatility_multiplier=0 → score=0
    assert compute_score(50000.0, 100.0, 0.0) == 0.0


def test_score_below_threshold_std():
    import math
    s = compute_score(50000.0, 100.0, 0.02)
    expected = math.log1p(50000.0) * 100.0 * min(0.02 / 0.05, 2.0)
    assert s == pytest.approx(expected)


def test_score_capped_at_2x():
    import math
    # std=0.15 → min(0.15/0.05, 2.0) = 2.0
    s = compute_score(50000.0, 100.0, 0.15)
    expected = math.log1p(50000.0) * 100.0 * 2.0
    assert s == pytest.approx(expected)


def test_score_proportional_to_std_below_cap():
    s1 = compute_score(50000.0, 100.0, 0.05)
    s2 = compute_score(50000.0, 100.0, 0.10)
    assert s2 == pytest.approx(s1 * 2.0)
