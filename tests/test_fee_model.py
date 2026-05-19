import math
import pytest
from src.fee_model import FeeModel


@pytest.fixture
def fm():
    return FeeModel()


# --- taker_fee ---

def test_taker_fee_standard_formula(fm):
    # fee = C * feeRate * p * (1-p)
    # 100 contracts at 0.50, feeRate=0.04 => 100 * 0.04 * 0.50 * 0.50 = 1.0
    assert fm.taker_fee(size=100, price=0.50, fee_rate=0.04, exponent=1) == pytest.approx(1.0)


def test_taker_fee_at_extremes_near_zero(fm):
    fee = fm.taker_fee(size=100, price=0.02, fee_rate=0.04, exponent=1)
    assert fee == pytest.approx(100 * 0.04 * 0.02 * 0.98)


def test_taker_fee_crypto_rate(fm):
    fee = fm.taker_fee(size=50, price=0.46, fee_rate=0.07, exponent=1)
    assert fee == pytest.approx(50 * 0.07 * 0.46 * 0.54)


def test_taker_fee_sports_exponent(fm):
    # Sports: size * price * fee_rate * (price*(1-price))^exponent
    # = 100 * 0.60 * 0.03 * (0.60*0.40)^1 = 100 * 0.60 * 0.03 * 0.24 = 0.432
    fee = fm.taker_fee(size=100, price=0.60, fee_rate=0.03, exponent=1, sports=True)
    assert fee == pytest.approx(100 * 0.60 * 0.03 * (0.60 * 0.40))


def test_taker_fee_sports_peaks_at_two_thirds(fm):
    fees = [fm.taker_fee(100, p/100, 0.03, exponent=1, sports=True) for p in range(1, 100)]
    peak_p = (fees.index(max(fees)) + 1) / 100
    assert abs(peak_p - 2/3) < 0.02


def test_taker_fee_standard_peaks_at_half(fm):
    fees = [fm.taker_fee(100, p/100, 0.04, exponent=1) for p in range(1, 100)]
    peak_p = (fees.index(max(fees)) + 1) / 100
    assert abs(peak_p - 0.50) < 0.02


# --- maker_rebate ---

def test_maker_rebate(fm):
    # rebate = rebate_fraction * fee_rate * p * (1-p) * size
    # 100 * 0.20 * 0.04 * 0.50 * 0.50 = 0.20
    rebate = fm.maker_rebate(size=100, price=0.50, fee_rate=0.04, rebate_fraction=0.20)
    assert rebate == pytest.approx(0.20)


def test_maker_rebate_zero_fraction(fm):
    rebate = fm.maker_rebate(size=100, price=0.50, fee_rate=0.04, rebate_fraction=0.0)
    assert rebate == 0.0


# --- fee_flatten_expected ---

def test_fee_flatten_expected_standard(fm):
    result = fm.fee_flatten_expected(fv=0.46, fee_rate=0.04, exponent=1)
    assert result == pytest.approx(0.04 * 0.46 * 0.54)


# --- max_flatten_price ---

def test_max_flatten_price_finance_at_midmarket(fm):
    # p_fill=0.50, feeRate=0.04 → p_max ≈ 0.487
    # Breakeven: (1 - 0.50 - p) + rebate(0.50) - taker_fee(p) = 0.005
    # Quadratic gives p_max ≈ 0.487 (smaller root; larger root > 1 is discarded)
    p_max = fm.max_flatten_price(
        p_fill=0.50, fee_rate=0.04, rebate_fraction=0.20, min_edge_floor=0.005
    )
    assert p_max == pytest.approx(0.487, abs=0.002)


def test_max_flatten_price_crypto_at_30(fm):
    # p_fill=0.30, feeRate=0.07 → p_max ≈ 0.683
    # Breakeven: (1 - 0.30 - p) + rebate(0.30) - taker_fee(p) = 0.005
    p_max = fm.max_flatten_price(
        p_fill=0.30, fee_rate=0.07, rebate_fraction=0.20, min_edge_floor=0.005
    )
    assert p_max == pytest.approx(0.683, abs=0.003)


def test_max_flatten_price_no_fill_above_1(fm):
    p_max = fm.max_flatten_price(
        p_fill=0.99, fee_rate=0.07, rebate_fraction=0.20, min_edge_floor=0.005
    )
    assert p_max <= 1.0


def test_max_flatten_price_returns_zero_on_impossible(fm):
    p_max = fm.max_flatten_price(
        p_fill=0.50, fee_rate=0.04, rebate_fraction=0.20, min_edge_floor=0.90
    )
    assert p_max == 0.0


def test_max_flatten_price_is_above_p_fill_for_yes_buy(fm):
    p_fill = 0.46
    p_max = fm.max_flatten_price(
        p_fill=p_fill, fee_rate=0.04, rebate_fraction=0.20, min_edge_floor=0.005
    )
    assert p_max < 1 - p_fill + 0.05
