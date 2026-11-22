from app.analysis import research


def candle(i, o=100.0, h=101.0, low=99.0, c=100.0, volume=10.0, closed=True):
    return {
        "time": i * 3600, "open": o, "high": h, "low": low,
        "close": c, "volume": volume, "is_closed": closed,
    }


def make_events(candle_count=1200, per_segment=120, counts=None):
    events = []
    train_end = int(candle_count * 0.60)
    calibration_end = int(candle_count * 0.80)
    segments = [
        (40, train_end - 20),
        (train_end + 10, calibration_end - 20),
        (calibration_end + 10, candle_count - 60),
    ]
    counts = counts or [per_segment, per_segment, per_segment]
    for segment_id, (start, end) in enumerate(segments):
        count = counts[segment_id]
        width = max(1, (end - start) // count)
        for j in range(count):
            idx = start + j * width
            label = j % 2
            events.append({
                "signal_idx": idx,
                "signal_time": idx * 3600,
                "label_end_idx": idx + 2,
                "exit_time": (idx + 2) * 3600,
                "direction": "LONG" if j % 3 else "SHORT",
                "signal_type": "BULLISH_BOS" if j % 3 else "BEARISH_CHOCH",
                "outcome": "TARGET" if label else "STOP",
                "label": label,
                "features": [1.0 if label else -1.0, float(label), 0.5 if label else -0.5,
                             1.0 if j % 3 == 0 else 0.0, 0.0],
            })
    return events


def test_label_enters_next_open_and_target_first():
    rows = [candle(i) for i in range(100)]
    rows[51]["open"] = 100.0
    rows[52]["high"] = 110.0
    result = research._label_event(
        rows, 50, {"direction": "BULLISH", "type": "BULLISH_BOS"},
        atr_period=14, atr_stop_multiple=1.0, reward_risk=1.0, horizon=5,
    )
    assert result is not None
    assert result["entry_time"] == rows[51]["time"]
    assert result["outcome"] == "TARGET"
    assert result["label"] == 1


def test_same_bar_stop_and_target_is_labelled_stop_first():
    rows = [candle(i) for i in range(100)]
    rows[51]["high"] = 110.0
    rows[51]["low"] = 90.0
    result = research._label_event(
        rows, 50, {"direction": "BULLISH", "type": "BULLISH_BOS"},
        atr_period=14, atr_stop_multiple=1.0, reward_risk=1.0, horizon=5,
    )
    assert result is not None
    assert result["outcome"] == "STOP"
    assert result["label"] == 0


def test_recent_unclosed_and_duplicate_candles_are_normalised():
    rows = [candle(i) for i in range(20)]
    rows[-1]["is_closed"] = False
    rows.append(candle(4, c=100.5))  # duplicate time; last valid version is retained
    normal = research._normalise_candles(rows)
    assert len(normal) == 19
    assert normal[-1]["time"] == rows[-3]["time"]
    assert normal[4]["close"] == 100.5


def test_split_purges_labels_that_cross_boundaries():
    n = 100
    events = [
        {"signal_idx": 50, "label_end_idx": 59},
        {"signal_idx": 58, "label_end_idx": 61},  # crosses train boundary
        {"signal_idx": 65, "label_end_idx": 75},
        {"signal_idx": 78, "label_end_idx": 85},  # crosses calibration boundary
        {"signal_idx": 90, "label_end_idx": 95},
    ]
    split = research._split_events(events, n)
    assert len(split["train"]) == 1
    assert len(split["calibration"]) == 1
    assert len(split["test"]) == 1
    assert split["purged_boundary_events"] == 2


def make_walk_forward_events(candle_count=1200, predictive=True):
    events = []
    for idx in range(30, candle_count - 2):
        label = idx % 2
        feature = (1.0 if label else -1.0) if predictive else 0.0
        events.append({
            "signal_idx": idx,
            "signal_time": idx * 3600,
            "label_end_idx": idx + 1,
            "exit_time": (idx + 1) * 3600,
            "direction": "LONG" if label else "SHORT",
            "signal_type": "BULLISH_BOS" if label else "BEARISH_CHOCH",
            "outcome": "TARGET" if label else "STOP",
            "label": label,
            "market_regime": "UPTREND" if idx % 4 < 2 else "DOWNTREND",
            "volatility_regime": "HIGH_VOL" if idx % 4 < 2 else "LOW_VOL",
            "features": [feature, float(label) if predictive else 0.0,
                         0.5 * feature, float(label) if predictive else 0.0, 0.0],
        })
    return events


def test_probabilities_are_withheld_when_walk_forward_sample_gates_fail(monkeypatch):
    candles = [candle(i) for i in range(1200)]
    events = make_walk_forward_events()[:50]
    monkeypatch.setattr(research, "build_labeled_events", lambda *args, **kwargs: {
        "status": "OK", "candles_analyzed": len(candles), "signals_found": len(events),
        "labelled_events": len(events), "right_censored": 0, "events": events,
    })
    result = research.run_calibration_study(candles, walk_forward={"embargo_bars": 2})
    assert result["status"] == "PROBABILITIES_SUPPRESSED_VALIDATION_FAILED"
    assert result["probabilities_published"] is False
    assert result["historical_probabilities_available"] is False
    assert result["historical_oos_predictions"] == []
    assert result["gate_failures"]


def test_walk_forward_predictive_data_passes_historical_research_gates(monkeypatch):
    candles = [candle(i) for i in range(1200)]
    events = make_walk_forward_events()
    monkeypatch.setattr(research, "build_labeled_events", lambda *args, **kwargs: {
        "status": "OK", "candles_analyzed": len(candles), "signals_found": len(events),
        "labelled_events": len(events), "right_censored": 0, "events": events,
    })
    result = research.run_calibration_study(candles, walk_forward={"embargo_bars": 2})
    assert result["status"] == "WALK_FORWARD_VALIDATED_RESEARCH"
    assert result["probabilities_published"] is True
    assert result["historical_probabilities_available"] is True
    assert result["live_signal_eligible"] is False
    assert result["completed_folds"] == 5
    assert result["positive_brier_skill_folds"] == 5
    assert result["regime_analysis"]["trend"]["populated_regime_count"] == 2
    assert result["regime_analysis"]["volatility"]["populated_regime_count"] == 2
    assert result["evaluation"]["brier_skill_block_bootstrap_95"][0] > 0
    assert result["historical_oos_predictions"]
    assert result["label_audit"]["label_mapping_verified"] is True
    assert len(result["score_direction_diagnostics"]["folds"]) == 5
    assert set(result["model_comparison"]["models"]) == {
        "constant_training_rate", "direction_frequency", "event_type_frequency", "full_smc_logistic"
    }
    assert "break_distance_atr" in result["feature_investigation"]["features"]
    assert all("probability_target_before_stop" in row for row in result["historical_oos_predictions"])
    assert all("volatility_regime" in row for row in result["historical_oos_predictions"])


def test_non_predictive_data_never_exposes_raw_probabilities(monkeypatch):
    candles = [candle(i) for i in range(1200)]
    events = make_walk_forward_events(predictive=False)
    monkeypatch.setattr(research, "build_labeled_events", lambda *args, **kwargs: {
        "status": "OK", "candles_analyzed": len(candles), "signals_found": len(events),
        "labelled_events": len(events), "right_censored": 0, "events": events,
    })
    result = research.run_calibration_study(candles, walk_forward={"embargo_bars": 2})
    assert result["probabilities_published"] is False
    assert result["historical_oos_predictions"] == []
    if result["evaluation"] is not None:
        assert "calibration_bins" not in result["evaluation"]
    for model in result.get("model_comparison", {}).get("models", {}).values():
        assert "calibration_bins" not in model
    assert any("Brier" in reason or "skill" in reason for reason in result["gate_failures"])


def test_walk_forward_windows_are_expanding_and_test_segments_disjoint():
    folds = research._walk_forward_folds(1000, research.WALK_FORWARD_DEFAULTS)
    assert len(folds) == 5
    assert folds[0]["train_end_index_exclusive"] < folds[1]["train_end_index_exclusive"]
    assert folds[0]["embargo_bars"] == 48
    for left, right in zip(folds, folds[1:]):
        assert right["test_start_index"] - left["test_end_index_exclusive"] == 48


def test_walk_forward_fold_purges_cross_boundary_labels():
    bounds = {
        "train_end_index_exclusive": 60,
        "calibration_start_index": 60,
        "calibration_end_index_exclusive": 80,
        "test_start_index": 80,
        "test_end_index_exclusive": 100,
    }
    events = [
        {"signal_idx": 50, "label_end_idx": 55},
        {"signal_idx": 58, "label_end_idx": 61},
        {"signal_idx": 65, "label_end_idx": 70},
        {"signal_idx": 78, "label_end_idx": 82},
        {"signal_idx": 90, "label_end_idx": 95},
    ]
    split = research._split_events_for_fold(events, bounds)
    assert len(split["train"]) == 1
    assert len(split["calibration"]) == 1
    assert len(split["test"]) == 1
    assert split["purged"] == {"train": 1, "calibration": 1, "test": 0}

def test_dataset_snapshot_is_reproducible_and_changes_with_data():
    rows = [candle(i) for i in range(10)]
    first = research._dataset_snapshot(rows)
    second = research._dataset_snapshot(rows)
    assert first["sha256"] == second["sha256"]
    assert first["candle_count"] == 10
    assert first["first_candle_time"] == rows[0]["time"]
    assert first["last_candle_time"] == rows[-1]["time"]
    changed = [dict(row) for row in rows]
    changed[-1]["close"] = 100.25
    assert research._dataset_snapshot(changed)["sha256"] != first["sha256"]


def test_split_periods_report_chronological_boundaries():
    rows = [candle(i) for i in range(100)]
    periods = research._split_periods(rows, {
        "train_end_index_exclusive": 60,
        "calibration_end_index_exclusive": 80,
    })
    assert periods["train"]["first_candle_time"] == rows[0]["time"]
    assert periods["train"]["last_candle_time"] == rows[59]["time"]
    assert periods["calibration"]["first_candle_time"] == rows[60]["time"]
    assert periods["calibration"]["last_candle_time"] == rows[79]["time"]
    assert periods["test"]["first_candle_time"] == rows[80]["time"]
    assert periods["test"]["last_candle_time"] == rows[99]["time"]


def test_volatility_regime_uses_only_current_and_prior_candles():
    rows = [candle(i) for i in range(260)]
    for i in range(220, 260):
        rows[i]["high"] = 105.0
        rows[i]["low"] = 95.0
    first = research._causal_volatility_regimes(rows)
    changed_future = [dict(row) for row in rows]
    changed_future[250]["high"] = 150.0
    second = research._causal_volatility_regimes(changed_future)
    assert first[220] == "HIGH_VOL"
    assert first[220] == second[220]
    assert first[100] == second[100]


def test_nonpositive_platt_slope_suppresses_probabilities(monkeypatch):
    candles = [candle(i) for i in range(1200)]
    events = make_walk_forward_events()
    monkeypatch.setattr(research, "build_labeled_events", lambda *args, **kwargs: {
        "status": "OK", "candles_analyzed": len(candles), "signals_found": len(events),
        "labelled_events": len(events), "right_censored": 0, "events": events,
    })
    monkeypatch.setattr(research, "_fit_logistic", lambda train: {"fixture": True})
    monkeypatch.setattr(research, "_model_logit", lambda model, event: 1.0 if event["label"] else -1.0)
    monkeypatch.setattr(research, "_fit_platt", lambda logits, labels: (-0.25, 0.0))
    result = research.run_calibration_study(candles, walk_forward={"embargo_bars": 2})
    assert result["probabilities_published"] is False
    assert result["historical_oos_predictions"] == []
    assert any("Platt slope is non-positive" in reason for reason in result["gate_failures"])


def test_auc_score_direction_diagnostic_handles_order_and_ties():
    assert research._binary_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert research._binary_auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0
    assert research._binary_auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5


def test_label_audit_detects_positive_class_mismatch():
    events = [{"signal_idx": 5, "label_end_idx": 6, "direction": "LONG", "outcome": "STOP", "label": 1}]
    audit = research._audit_event_labels(events)
    assert audit["label_mapping_verified"] is False
    assert audit["label_mismatch_rows"] == [0]


def test_feature_values_are_causal_and_ignore_future_candle_changes():
    rows = [candle(i, o=100 + i * 0.01, h=101 + i * 0.01, low=99 + i * 0.01,
                   c=100.2 + i * 0.01, volume=10 + i) for i in range(100)]
    event = {"direction": "BULLISH", "type": "BULLISH_BOS", "level": rows[80]["close"] - 0.5}
    first = research._feature_vector(rows, 80, event, 14)
    changed = [dict(row) for row in rows]
    changed[81]["high"] = 500.0
    changed[90]["volume"] = 99999.0
    second = research._feature_vector(changed, 80, event, 14)
    assert first == second
