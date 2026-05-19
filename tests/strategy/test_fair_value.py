import pytest
from datetime import datetime, timezone, timedelta
from src.strategy.fair_value import FairValueEstimator, TradeObservation, ExternalSignal


def ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


# --- TWAP ---

def test_twap_single_trade():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.0)
    est.on_trade(TradeObservation(price=0.46, size=100, timestamp=ts(0)))
    fv = est.estimate(as_of=ts(10))
    assert fv == pytest.approx(0.46)


def test_twap_volume_weighted():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.0)
    est.on_trade(TradeObservation(price=0.40, size=100, timestamp=ts(0)))
    est.on_trade(TradeObservation(price=0.50, size=300, timestamp=ts(1)))
    fv = est.estimate(as_of=ts(10))
    # VWAP: (0.40*100 + 0.50*300) / 400 = 190/400 = 0.475
    assert fv == pytest.approx(0.475)


def test_twap_ignores_trades_outside_window():
    est = FairValueEstimator(twap_window_seconds=60, external_weight=0.0)
    est.on_trade(TradeObservation(price=0.30, size=500, timestamp=ts(0)))   # old
    est.on_trade(TradeObservation(price=0.50, size=100, timestamp=ts(90)))  # recent
    fv = est.estimate(as_of=ts(100))
    assert fv == pytest.approx(0.50)


def test_twap_returns_none_with_no_trades():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.0)
    fv = est.estimate(as_of=ts(0))
    assert fv is None


# --- External signal blending ---

def test_external_signal_blend():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.30)
    est.on_trade(TradeObservation(price=0.50, size=100, timestamp=ts(0)))
    est.on_external_signal(ExternalSignal(source="metaculus", probability=0.65, timestamp=ts(0)))
    fv = est.estimate(as_of=ts(1))
    # blend: 0.70 * 0.50 + 0.30 * 0.65 = 0.35 + 0.195 = 0.545
    assert fv == pytest.approx(0.545)


def test_external_signal_ignored_if_no_trades():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.30)
    est.on_external_signal(ExternalSignal(source="metaculus", probability=0.65, timestamp=ts(0)))
    fv = est.estimate(as_of=ts(1))
    assert fv is None


def test_multiple_external_signals_averaged():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.40)
    est.on_trade(TradeObservation(price=0.50, size=100, timestamp=ts(0)))
    est.on_external_signal(ExternalSignal(source="metaculus", probability=0.60, timestamp=ts(0)))
    est.on_external_signal(ExternalSignal(source="manifold", probability=0.80, timestamp=ts(0)))
    fv = est.estimate(as_of=ts(1))
    # external avg = (0.60 + 0.80) / 2 = 0.70
    # blend: 0.60 * 0.50 + 0.40 * 0.70 = 0.30 + 0.28 = 0.58
    assert fv == pytest.approx(0.58)


# --- FV never anchors to book mid ---

def test_fv_does_not_use_book_mid():
    import inspect
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.0)
    sig = inspect.signature(est.estimate)
    assert "book" not in sig.parameters
    assert "mid" not in sig.parameters
