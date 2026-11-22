"""Leakage-aware SMC outcome study with strict expanding walk-forward gates.

Features and regime descriptors use only information available at the signal
candle close. Outcome labels use subsequent candles. Every fold is chronological,
embargoed and boundary-purged; all per-event probabilities are suppressed unless
predeclared predictive-improvement, calibration, regime and uncertainty gates pass.

This module intentionally uses only the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any

from app.analysis.smc import _atr, _pivot_points, _structure_events

FEATURE_NAMES = (
    "break_distance_atr",
    "body_fraction",
    "log_volume_ratio",
    "choch_flag",
    "aligned_fvg_flag",
)

DEFAULT_GATES = {
    "minimum_train_events": 200,
    "minimum_calibration_events": 100,
    "minimum_test_events": 100,
    "minimum_train_per_class": 30,
    "minimum_calibration_per_class": 20,
    "minimum_test_per_class": 20,
}

WALK_FORWARD_DEFAULTS = {
    "initial_train_fraction": 0.35,
    "calibration_fraction": 0.15,
    "test_fraction": 0.10,
    "step_fraction": 0.10,
    "embargo_bars": 48,
    "minimum_completed_folds": 5,
    "minimum_positive_skill_folds": 4,
    "maximum_aggregate_ece": 0.10,
    "minimum_regime_events": 50,
    "minimum_populated_regimes": 2,
    "bootstrap_block_length": 10,
    "bootstrap_replicates": 500,
    "bootstrap_seed": 1729,
}



def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -700.0))
    return z / (1.0 + z)


def _normalise_candles(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep closed, valid, chronologically ordered candles with unique times."""
    by_time: dict[int, dict[str, Any]] = {}
    for raw_row in raw:
        if not raw_row.get("is_closed", True):
            continue
        try:
            row = dict(raw_row)
            t = int(row.get("time", row.get("open_time")))
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            v = float(row.get("volume", 0.0) or 0.0)
        except (TypeError, ValueError, KeyError):
            continue
        if not all(math.isfinite(x) for x in (o, h, low, c, v)):
            continue
        if low <= 0 or h < max(o, c, low) or low > min(o, c, h) or v < 0:
            continue
        row["time"] = t
        row["open"], row["high"], row["low"], row["close"] = o, h, low, c
        row["volume"] = v
        row["is_closed"] = True
        by_time[t] = row
    return [by_time[t] for t in sorted(by_time)]


def _feature_vector(candles: list[dict[str, Any]], idx: int, event: dict[str, Any], atr_period: int) -> list[float] | None:
    """Return causal signal-time features; no candle after idx is inspected."""
    history = candles[: idx + 1]
    atr = _atr(history, atr_period)
    if atr is None or atr <= 0:
        return None

    candle = candles[idx]
    spread = max(candle["high"] - candle["low"], 1e-12)
    direction = 1.0 if event.get("direction") == "BULLISH" else -1.0
    displacement = direction * (candle["close"] - float(event.get("level", candle["close"]))) / atr
    body_fraction = abs(candle["close"] - candle["open"]) / spread

    prior_volumes = [float(x.get("volume", 0.0) or 0.0) for x in candles[max(0, idx - 20):idx]]
    baseline_volume = (sum(prior_volumes) / len(prior_volumes)) if prior_volumes else 0.0
    current_volume = float(candle.get("volume", 0.0) or 0.0)
    volume_ratio = math.log((current_volume + 1e-12) / (baseline_volume + 1e-12))
    volume_ratio = max(-5.0, min(5.0, volume_ratio))

    choch_flag = 1.0 if "CHOCH" in str(event.get("type", "")) else 0.0
    aligned_fvg = 0.0
    if idx >= 2:
        first = candles[idx - 2]
        if direction > 0 and first["high"] < candle["low"]:
            aligned_fvg = 1.0
        elif direction < 0 and first["low"] > candle["high"]:
            aligned_fvg = 1.0

    return [max(-10.0, min(10.0, displacement)), max(0.0, min(1.0, body_fraction)), volume_ratio, choch_flag, aligned_fvg]


def _label_event(
    candles: list[dict[str, Any]], signal_idx: int, event: dict[str, Any], *,
    atr_period: int, atr_stop_multiple: float, reward_risk: float, horizon: int,
) -> dict[str, Any] | None:
    """Label a signal by the first stop/target touch after next-open entry."""
    entry_idx = signal_idx + 1
    last_idx = entry_idx + horizon - 1
    if entry_idx >= len(candles) or last_idx >= len(candles):
        return None  # right-censored; do not invent an outcome

    atr = _atr(candles[: signal_idx + 1], atr_period)
    if atr is None or atr <= 0:
        return None
    direction = 1 if event.get("direction") == "BULLISH" else -1
    entry = float(candles[entry_idx]["open"])
    stop_distance = atr * atr_stop_multiple
    stop = entry - direction * stop_distance
    target = entry + direction * stop_distance * reward_risk
    if entry <= 0 or stop <= 0 or target <= 0:
        return None

    exit_idx = last_idx
    exit_price = float(candles[last_idx]["close"])
    outcome = "TIMEOUT"
    for j in range(entry_idx, last_idx + 1):
        bar = candles[j]
        if direction > 0:
            stop_hit = float(bar["low"]) <= stop
            target_hit = float(bar["high"]) >= target
        else:
            stop_hit = float(bar["high"]) >= stop
            target_hit = float(bar["low"]) <= target
        # OHLC bars cannot reveal which level was reached first.
        if stop_hit:
            exit_idx, exit_price, outcome = j, stop, "STOP"
            break
        if target_hit:
            exit_idx, exit_price, outcome = j, target, "TARGET"
            break

    return {
        "signal_idx": signal_idx,
        "signal_time": int(candles[signal_idx]["time"]),
        "entry_time": int(candles[entry_idx]["time"]),
        "label_end_idx": exit_idx,
        "exit_time": int(candles[exit_idx]["time"]),
        "direction": "LONG" if direction > 0 else "SHORT",
        "signal_type": str(event.get("type", "STRUCTURE_BREAK")),
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "exit_price": exit_price,
        "outcome": outcome,
        "label": 1 if outcome == "TARGET" else 0,
    }


def _market_regime(candles: list[dict[str, Any]], idx: int, lookback: int = 50) -> str:
    """Causal broad regime label based only on the trailing close-to-close return."""
    if idx < lookback:
        return "UNKNOWN"
    start = float(candles[idx - lookback]["close"])
    end = float(candles[idx]["close"])
    if start <= 0:
        return "UNKNOWN"
    momentum = end / start - 1.0
    if momentum >= 0.01:
        return "UPTREND"
    if momentum <= -0.01:
        return "DOWNTREND"
    return "RANGE"


def _causal_volatility_regimes(
    candles: list[dict[str, Any]], *, atr_period: int = 14, reference_window: int = 200,
) -> list[str]:
    """Classify current ATR% against its trailing historical mean, excluding now."""
    true_ranges: list[float] = []
    for idx, candle in enumerate(candles):
        previous_close = float(candles[idx - 1]["close"]) if idx else float(candle["close"])
        true_ranges.append(max(
            float(candle["high"]) - float(candle["low"]),
            abs(float(candle["high"]) - previous_close),
            abs(float(candle["low"]) - previous_close),
        ))
    prefix = [0.0]
    for value in true_ranges:
        prefix.append(prefix[-1] + value)
    atr_percentages = []
    for idx, candle in enumerate(candles):
        start = max(0, idx - atr_period + 1)
        atr = (prefix[idx + 1] - prefix[start]) / (idx - start + 1)
        close = float(candle["close"])
        atr_percentages.append(atr / close if close > 0 else 0.0)

    atr_prefix = [0.0]
    for value in atr_percentages:
        atr_prefix.append(atr_prefix[-1] + value)
    labels = []
    for idx, current in enumerate(atr_percentages):
        start = max(0, idx - reference_window)
        count = idx - start
        if count < 20:
            labels.append("UNKNOWN")
            continue
        prior_mean = (atr_prefix[idx] - atr_prefix[start]) / count
        labels.append("HIGH_VOL" if current > prior_mean else "LOW_VOL")
    return labels


def build_labeled_events(
    raw_candles: list[dict[str, Any]], *, pivot_left: int = 3, pivot_right: int = 3,
    atr_period: int = 14, atr_stop_multiple: float = 1.5,
    reward_risk: float = 2.0, horizon: int = 48,
) -> dict[str, Any]:
    """Create non-overlapping causal structure-break events and future labels."""
    candles = _normalise_candles(raw_candles)
    minimum = max(80, pivot_left + pivot_right + atr_period + 20)
    if len(candles) < minimum:
        return {
            "status": "INSUFFICIENT_DATA", "candles_analyzed": len(candles),
            "minimum_required": minimum, "events": [], "right_censored": 0,
        }

    highs, lows = _pivot_points(candles, pivot_left, pivot_right)
    events, _ = _structure_events(candles, highs, lows)
    volatility_regimes = _causal_volatility_regimes(candles, atr_period=atr_period)
    index_by_time = {int(c["time"]): i for i, c in enumerate(candles)}
    indexed_events = []
    for event in events:
        idx = index_by_time.get(int(event.get("time", -1)))
        if idx is not None:
            indexed_events.append((idx, event))
    indexed_events.sort(key=lambda pair: pair[0])

    labelled: list[dict[str, Any]] = []
    right_censored = 0
    occupied_until = -1
    for idx, event in indexed_events:
        if idx <= occupied_until:
            continue
        features = _feature_vector(candles, idx, event, atr_period)
        if features is None:
            continue
        labelled_trade = _label_event(
            candles, idx, event, atr_period=atr_period,
            atr_stop_multiple=atr_stop_multiple, reward_risk=reward_risk,
            horizon=horizon,
        )
        if labelled_trade is None:
            right_censored += 1
            continue
        labelled.append({
            **labelled_trade,
            "features": features,
            "market_regime": _market_regime(candles, idx),
            "volatility_regime": volatility_regimes[idx],
        })
        occupied_until = int(labelled_trade["label_end_idx"])

    return {
        "status": "OK", "candles_analyzed": len(candles),
        "signals_found": len(indexed_events), "labelled_events": len(labelled),
        "right_censored": right_censored, "events": labelled,
    }



def _dataset_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Stable fingerprint and date range for reproducible research reports."""
    canonical = [
        [
            int(c["time"]),
            float(c["open"]).hex(),
            float(c["high"]).hex(),
            float(c["low"]).hex(),
            float(c["close"]).hex(),
            float(c.get("volume", 0.0) or 0.0).hex(),
        ]
        for c in candles
    ]
    payload = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "candle_count": len(candles),
        "first_candle_time": int(candles[0]["time"]) if candles else None,
        "last_candle_time": int(candles[-1]["time"]) if candles else None,
        "fingerprint_fields": ["time", "open", "high", "low", "close", "volume"],
    }


def _split_periods(candles: list[dict[str, Any]], boundaries: dict[str, int]) -> dict[str, Any]:
    n = len(candles)
    train_end = boundaries["train_end_index_exclusive"]
    calibration_end = boundaries["calibration_end_index_exclusive"]

    def period(start: int, end: int) -> dict[str, int | None]:
        if start >= end or start >= n:
            return {"first_candle_time": None, "last_candle_time": None}
        return {
            "first_candle_time": int(candles[start]["time"]),
            "last_candle_time": int(candles[min(end, n) - 1]["time"]),
        }

    return {
        "train": period(0, train_end),
        "calibration": period(train_end, calibration_end),
        "test": period(calibration_end, n),
    }

def _split_events(events: list[dict[str, Any]], candle_count: int) -> dict[str, Any]:
    train_end = int(candle_count * 0.60)
    calibration_end = int(candle_count * 0.80)
    train, calibration, test = [], [], []
    purged = 0
    for event in events:
        start, end = int(event["signal_idx"]), int(event["label_end_idx"])
        if start < train_end:
            if end < train_end:
                train.append(event)
            else:
                purged += 1
        elif start < calibration_end:
            if end < calibration_end:
                calibration.append(event)
            else:
                purged += 1
        else:
            test.append(event)
    return {"train": train, "calibration": calibration, "test": test, "purged_boundary_events": purged,
            "bar_boundaries": {"train_end_index_exclusive": train_end, "calibration_end_index_exclusive": calibration_end}}


def _class_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    positives = sum(int(x["label"]) for x in events)
    return {"events": len(events), "positive_target_first": positives, "negative_stop_or_timeout": len(events) - positives}


def _fit_logistic(train: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions = len(FEATURE_NAMES)
    means, scales = [], []
    for j in range(dimensions):
        values = [float(e["features"][j]) for e in train]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
        means.append(mean)
        scales.append(math.sqrt(variance) if variance > 1e-12 else 1.0)

    def transform(event: dict[str, Any]) -> list[float]:
        return [max(-8.0, min(8.0, (float(v) - means[j]) / scales[j])) for j, v in enumerate(event["features"])]

    x_rows = [[1.0, *transform(event)] for event in train]
    y_rows = [int(event["label"]) for event in train]
    beta = [0.0] * (dimensions + 1)
    prior = (sum(y_rows) + 0.5) / (len(y_rows) + 1.0)
    beta[0] = math.log(prior / (1.0 - prior))
    learning_rate = 0.08
    ridge = 0.02

    for _ in range(5000):
        gradients = [0.0] * len(beta)
        for x, y in zip(x_rows, y_rows):
            error = _sigmoid(sum(b * v for b, v in zip(beta, x))) - y
            for j, value in enumerate(x):
                gradients[j] += error * value
        gradients[0] /= len(x_rows)
        for j in range(1, len(beta)):
            gradients[j] = gradients[j] / len(x_rows) + ridge * beta[j]
        max_change = 0.0
        for j in range(len(beta)):
            change = learning_rate * gradients[j]
            beta[j] -= change
            max_change = max(max_change, abs(change))
        if max_change < 1e-8:
            break

    return {"means": means, "scales": scales, "coefficients": beta, "feature_names": list(FEATURE_NAMES)}


def _model_logit(model: dict[str, Any], event: dict[str, Any]) -> float:
    beta = model["coefficients"]
    values = [1.0]
    for j, raw in enumerate(event["features"]):
        z = (float(raw) - model["means"][j]) / model["scales"][j]
        values.append(max(-8.0, min(8.0, z)))
    return sum(a * b for a, b in zip(beta, values))


def _fit_platt(logits: list[float], labels: list[int]) -> tuple[float, float]:
    """Fit P(y=1)=sigmoid(slope*logit+intercept) by 2D Newton updates."""
    slope, intercept = 1.0, 0.0
    ridge = 1e-4
    for _ in range(200):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for z, y in zip(logits, labels):
            p = _sigmoid(slope * z + intercept)
            error = p - y
            weight = max(1e-8, p * (1.0 - p))
            g0 += error * z
            g1 += error
            h00 += weight * z * z
            h01 += weight * z
            h11 += weight
        g0 += ridge * slope
        g1 += ridge * intercept
        h00 += ridge
        h11 += ridge
        determinant = h00 * h11 - h01 * h01
        if abs(determinant) < 1e-12:
            break
        delta_slope = (h11 * g0 - h01 * g1) / determinant
        delta_intercept = (-h01 * g0 + h00 * g1) / determinant
        delta_slope = max(-5.0, min(5.0, delta_slope))
        delta_intercept = max(-5.0, min(5.0, delta_intercept))
        slope -= delta_slope
        intercept -= delta_intercept
        if max(abs(delta_slope), abs(delta_intercept)) < 1e-7:
            break
    return slope, intercept


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    margin = z * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total))) / denom
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _evaluate(
    probabilities: list[float], labels: list[int], baseline_rate: float | list[float], bins: int = 10,
) -> dict[str, Any]:
    n = len(labels)
    if n == 0:
        raise ValueError("Cannot evaluate an empty prediction set")
    eps = 1e-12
    baseline_probabilities = (
        [float(baseline_rate)] * n if isinstance(baseline_rate, (int, float))
        else [float(value) for value in baseline_rate]
    )
    if len(baseline_probabilities) != n:
        raise ValueError("Baseline probabilities must align with labels")
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / n
    log_loss = -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1.0 - p)) for p, y in zip(probabilities, labels)) / n
    baseline_brier = sum((p - y) ** 2 for p, y in zip(baseline_probabilities, labels)) / n
    baseline_log_loss = -sum(
        y * math.log(max(eps, min(1.0 - eps, p))) + (1 - y) * math.log(max(eps, min(1.0 - eps, 1.0 - p)))
        for p, y in zip(baseline_probabilities, labels)
    ) / n
    base_rate = sum(labels) / n
    calibration_bins = []
    ece = 0.0
    for b in range(bins):
        lower, upper = b / bins, (b + 1) / bins
        indexes = [i for i, p in enumerate(probabilities) if lower <= p < upper or (b == bins - 1 and p == 1.0)]
        if not indexes:
            continue
        mean_probability = sum(probabilities[i] for i in indexes) / len(indexes)
        observed_rate = sum(labels[i] for i in indexes) / len(indexes)
        ece += len(indexes) / n * abs(mean_probability - observed_rate)
        calibration_bins.append({
            "range": f"{lower:.1f}-{upper:.1f}", "count": len(indexes),
            "mean_predicted_probability": round(mean_probability, 4),
            "observed_target_rate": round(observed_rate, 4),
        })
    mean_baseline_probability = sum(baseline_probabilities) / n
    brier_skill = (1.0 - brier / baseline_brier) if baseline_brier > 0 else None
    log_loss_skill = (1.0 - log_loss / baseline_log_loss) if baseline_log_loss > 0 else None
    return {
        "test_events": n,
        "positive_target_first": sum(labels),
        "observed_target_rate": round(base_rate, 4),
        "observed_target_rate_wilson_95": _wilson_interval(sum(labels), n),
        "brier_score": round(brier, 5),
        "brier_score_baseline_training_rate": round(baseline_brier, 5),
        "baseline_probability_training_target_rate": round(mean_baseline_probability, 4),
        "brier_skill_score_vs_training_baseline": round(brier_skill, 5) if brier_skill is not None else None,
        "beats_training_rate_baseline": bool(brier < baseline_brier) if baseline_brier > 0 else None,
        "log_loss": round(log_loss, 5),
        "log_loss_baseline_training_rate": round(baseline_log_loss, 5),
        "log_loss_skill_vs_training_baseline": round(log_loss_skill, 5) if log_loss_skill is not None else None,
        "beats_training_rate_log_loss_baseline": bool(log_loss < baseline_log_loss),
        "expected_calibration_error": round(ece, 5),
        "calibration_bins": calibration_bins,
    }



def _binary_auc(scores: list[float], labels: list[int]) -> float | None:
    """ROC AUC using average ranks for ties; returns None without both classes."""
    if len(scores) != len(labels) or not scores:
        return None
    positives = sum(int(value) for value in labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted((float(score), int(label)) for score, label in zip(scores, labels))
    positive_rank_sum = 0.0
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        average_rank = ((position + 1) + end) / 2.0
        positive_rank_sum += average_rank * sum(label for _, label in ordered[position:end])
        position = end
    auc = (positive_rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)
    return round(auc, 6)


def _pearson_correlation(values: list[float], labels: list[int]) -> float | None:
    if len(values) != len(labels) or len(values) < 2:
        return None
    mean_x = sum(values) / len(values)
    mean_y = sum(labels) / len(labels)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(values, labels))
    var_x = sum((x - mean_x) ** 2 for x in values)
    var_y = sum((y - mean_y) ** 2 for y in labels)
    if var_x <= 0 or var_y <= 0:
        return None
    return round(cov / math.sqrt(var_x * var_y), 6)


def _audit_event_labels(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Check the semantic mapping between event outcomes and positive class."""
    valid_outcomes = {"TARGET", "STOP", "TIMEOUT"}
    label_mismatches = []
    invalid_rows = []
    duplicate_signal_indexes = 0
    seen = set()
    for row_index, row in enumerate(events):
        signal_idx = int(row.get("signal_idx", -1))
        if signal_idx in seen:
            duplicate_signal_indexes += 1
        seen.add(signal_idx)
        outcome = str(row.get("outcome", ""))
        label = row.get("label")
        direction = str(row.get("direction", ""))
        if outcome not in valid_outcomes or label not in (0, 1) or direction not in {"LONG", "SHORT"}:
            invalid_rows.append(row_index)
            continue
        if int(label) != (1 if outcome == "TARGET" else 0):
            label_mismatches.append(row_index)
        if int(row.get("label_end_idx", signal_idx)) < signal_idx + 1:
            invalid_rows.append(row_index)
    return {
        "definition": "positive=1 iff outcome is TARGET; STOP and TIMEOUT are negative=0",
        "events_audited": len(events),
        "positive_target_count": sum(1 for row in events if row.get("outcome") == "TARGET"),
        "negative_stop_or_timeout_count": sum(1 for row in events if row.get("outcome") in {"STOP", "TIMEOUT"}),
        "label_mapping_verified": not label_mismatches and not invalid_rows,
        "label_mismatch_rows": label_mismatches[:20],
        "invalid_event_rows": invalid_rows[:20],
        "duplicate_signal_index_count": duplicate_signal_indexes,
        "note": "The label is target-before-stop within the configured horizon, not general bullish/bearish direction or profitability.",
    }


def _feature_fold_diagnostics(
    train: list[dict[str, Any]], test: list[dict[str, Any]], model: dict[str, Any],
) -> dict[str, Any]:
    """Train-only orientation selection; test AUC is diagnostic and never flips a feature."""
    items = {}
    for feature_index, feature_name in enumerate(FEATURE_NAMES):
        train_values = [float(row["features"][feature_index]) for row in train]
        train_labels = [int(row["label"]) for row in train]
        test_values = [float(row["features"][feature_index]) for row in test]
        test_labels = [int(row["label"]) for row in test]
        train_auc = _binary_auc(train_values, train_labels)
        if train_auc is None or abs(train_auc - 0.5) < 1e-9:
            orientation = "UNRESOLVED"
            aligned_test_auc = None
        else:
            orientation = "HIGHER_FEATURE_VALUE" if train_auc > 0.5 else "LOWER_FEATURE_VALUE"
            aligned_values = test_values if train_auc > 0.5 else [-value for value in test_values]
            aligned_test_auc = _binary_auc(aligned_values, test_labels)
        raw_test_auc = _binary_auc(test_values, test_labels)
        coefficient = None
        if isinstance(model, dict) and len(model.get("coefficients", [])) > feature_index + 1:
            coefficient = round(float(model["coefficients"][feature_index + 1]), 6)
        train_mean = sum(train_values) / len(train_values) if train_values else 0.0
        train_variance = sum((value - train_mean) ** 2 for value in train_values) / max(1, len(train_values) - 1)
        test_mean = sum(test_values) / len(test_values) if test_values else 0.0
        scale = math.sqrt(train_variance) if train_variance > 1e-12 else 1.0
        items[feature_name] = {
            "train_univariate_auc": train_auc,
            "train_selected_orientation": orientation,
            "test_auc_after_train_only_orientation": aligned_test_auc,
            "test_univariate_auc_raw": raw_test_auc,
            "test_mean_shift_in_train_sd": round((test_mean - train_mean) / scale, 6),
            "full_model_standardized_coefficient": coefficient,
            "interpretation": "Exploratory marginal association; correlated features and repeated comparisons can inflate apparent importance.",
        }
    return {"feature_results": items, "orientation_rule": "Feature orientation is selected on the training partition only; test outcomes never choose or flip direction."}


def _category_prior_logit(train: list[dict[str, Any]], row: dict[str, Any], key: str) -> float:
    """Laplace-smoothed category frequency, with training prevalence for unknown groups."""
    total_positive = sum(int(item["label"]) for item in train)
    global_rate = (total_positive + 1.0) / (len(train) + 2.0)
    category = row.get(key)
    matches = [item for item in train if item.get(key) == category]
    rate = (sum(int(item["label"]) for item in matches) + 1.0) / (len(matches) + 2.0)
    # Shrink sparse category rates toward the global training prior.
    weight = len(matches) / (len(matches) + 10.0)
    rate = weight * rate + (1.0 - weight) * global_rate
    rate = min(1.0 - 1e-6, max(1e-6, rate))
    return math.log(rate / (1.0 - rate))


def _model_comparison_for_fold(
    train: list[dict[str, Any]], calibration: list[dict[str, Any]], test: list[dict[str, Any]],
    full_probabilities: list[float], training_rate: float,
) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """Compare simple transparent baselines and the SMC logistic model on identical OOS rows."""
    labels = [int(row["label"]) for row in test]
    model_probs: dict[str, list[float]] = {
        "constant_training_rate": [training_rate] * len(test),
        "full_smc_logistic": list(full_probabilities),
    }
    calibration_labels = [int(row["label"]) for row in calibration]
    calibration_diagnostics = {}
    for display_name, category_key in (("direction_frequency", "direction"), ("event_type_frequency", "signal_type")):
        cal_logits = [_category_prior_logit(train, row, category_key) for row in calibration]
        test_logits = [_category_prior_logit(train, row, category_key) for row in test]
        slope, intercept = _fit_platt(cal_logits, calibration_labels)
        probabilities = [_sigmoid(slope * value + intercept) for value in test_logits]
        model_probs[display_name] = probabilities
        calibration_diagnostics[display_name] = {
            "platt_slope": round(slope, 6),
            "score_ordering": "POSITIVE" if slope > 0 else "NON_POSITIVE_OR_UNSTABLE",
        }
    metrics = {
        name: _evaluate(probabilities, labels, baseline_rate=training_rate)
        for name, probabilities in model_probs.items()
    }
    return {
        "metrics": metrics,
        "calibration_diagnostics": calibration_diagnostics,
        "warning": "These are exploratory diagnostic comparisons, not a model-selection contest. Choosing among them on these same test folds would create selection bias; any selected challenger needs a newly reserved future holdout.",
    }, model_probs


def _aggregate_model_comparisons(
    pooled: dict[str, dict[str, list[float]]], baselines: list[float], labels: list[int],
) -> dict[str, Any]:
    results = {}
    for name, payload in pooled.items():
        results[name] = _evaluate(payload["probabilities"], labels, baselines)
    ranked = sorted(
        (name for name in results if name != "constant_training_rate"),
        key=lambda name: results[name]["brier_score"],
    )
    return {
        "same_oos_events": len(labels),
        "models": results,
        "diagnostic_brier_order": ranked,
        "selection_policy": "No challenger is promoted from these test results. A new untouched prospective/chronological holdout is required before adopting a challenger.",
    }

def _walk_forward_folds(candle_count: int, config: dict[str, Any]) -> list[dict[str, int]]:
    """Create expanding-train, sequential calibration/test windows in candle time."""
    initial = float(config["initial_train_fraction"])
    calibration = float(config["calibration_fraction"])
    test = float(config["test_fraction"])
    step = float(config["step_fraction"])
    embargo = max(0, int(config.get("embargo_bars", 0)))
    if initial <= 0 or calibration <= 0 or test <= 0 or step <= 0 or initial + calibration + test > 1.0:
        raise ValueError("Invalid walk-forward window fractions")
    folds = []
    start = initial
    while start + calibration + test <= 1.0 + 1e-9:
        train_end = int(candle_count * start)
        calibration_end = int(candle_count * (start + calibration))
        test_end = min(candle_count, int(candle_count * (start + calibration + test)))
        if train_end > 0 and calibration_end > train_end + embargo and test_end > calibration_end + embargo:
            folds.append({
                "train_start_index": 0, "train_end_index_exclusive": train_end,
                "calibration_start_index": train_end + embargo, "calibration_end_index_exclusive": calibration_end,
                "test_start_index": calibration_end + embargo, "test_end_index_exclusive": test_end,
                "embargo_bars": embargo,
            })
        start = round(start + step, 10)
    return folds


def _split_events_for_fold(events: list[dict[str, Any]], bounds: dict[str, int]) -> dict[str, Any]:
    train, calibration, test = [], [], []
    purged = {"train": 0, "calibration": 0, "test": 0}
    embargoed = {"train_to_calibration": 0, "calibration_to_test": 0}
    t_end = bounds["train_end_index_exclusive"]
    raw_calibration_start = t_end
    c_start = bounds["calibration_start_index"]
    c_end = bounds["calibration_end_index_exclusive"]
    v_start = bounds["test_start_index"]
    raw_test_start = c_end
    v_end = bounds["test_end_index_exclusive"]
    for event in events:
        start, end = int(event["signal_idx"]), int(event["label_end_idx"])
        if start < t_end:
            if end < t_end:
                train.append(event)
            else:
                purged["train"] += 1
        elif raw_calibration_start <= start < c_start:
            embargoed["train_to_calibration"] += 1
        elif c_start <= start < c_end:
            if end < c_end:
                calibration.append(event)
            else:
                purged["calibration"] += 1
        elif raw_test_start <= start < v_start:
            embargoed["calibration_to_test"] += 1
        elif v_start <= start < v_end:
            if end < v_end:
                test.append(event)
            else:
                purged["test"] += 1
    return {"train": train, "calibration": calibration, "test": test, "purged": purged, "embargoed": embargoed}


def _bootstrap_brier_skill_interval(
    probabilities: list[float], labels: list[int], baseline_probabilities: list[float], *,
    block_length: int = 10, replicates: int = 500, seed: int = 1729,
) -> list[float] | None:
    """Moving-block bootstrap CI for paired Brier skill, preserving local event clustering."""
    n = len(labels)
    if n < max(20, block_length * 2) or replicates < 100:
        return None
    rng = random.Random(seed)
    skills = []
    blocks_needed = math.ceil(n / block_length)
    for _ in range(replicates):
        indexes = []
        for _block in range(blocks_needed):
            start = rng.randrange(n)
            indexes.extend((start + offset) % n for offset in range(block_length))
        indexes = indexes[:n]
        model_loss = sum((probabilities[i] - labels[i]) ** 2 for i in indexes) / n
        baseline_loss = sum((baseline_probabilities[i] - labels[i]) ** 2 for i in indexes) / n
        if baseline_loss > 0:
            skills.append(1.0 - model_loss / baseline_loss)
    if not skills:
        return None
    skills.sort()
    low = skills[int(0.025 * (len(skills) - 1))]
    high = skills[int(0.975 * (len(skills) - 1))]
    return [round(low, 5), round(high, 5)]


def _regime_evaluations(
    predictions: list[dict[str, Any]], *, minimum_events: int, dimension: str,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in predictions:
        grouped.setdefault(str(row.get(dimension, "UNKNOWN")), []).append(row)
    result = {}
    populated = []
    for regime, rows in sorted(grouped.items()):
        labels = [int(row["label"]) for row in rows]
        probs = [float(row["probability"]) for row in rows]
        baselines = [float(row["baseline_probability"]) for row in rows]
        if len(rows) >= minimum_events and len(set(labels)) == 2:
            metrics = _evaluate(probs, labels, baselines)
            populated.append(regime)
        else:
            metrics = None
        result[regime] = {"events": len(rows), "evaluation": metrics}
    return {"groups": result, "populated_regimes": populated, "populated_regime_count": len(populated)}


def run_calibration_study(
    raw_candles: list[dict[str, Any]], *, pivot_left: int = 3, pivot_right: int = 3,
    atr_period: int = 14, atr_stop_multiple: float = 1.5, reward_risk: float = 2.0,
    horizon: int = 48, gates: dict[str, int] | None = None,
    walk_forward: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run strict expanding-window walk-forward validation and gate all probabilities."""
    candles = _normalise_candles(raw_candles)
    gate = {**DEFAULT_GATES, **(gates or {})}
    wf = {**WALK_FORWARD_DEFAULTS, **(walk_forward or {})}
    if walk_forward is None or "embargo_bars" not in walk_forward:
        wf["embargo_bars"] = horizon
    dataset = build_labeled_events(
        candles, pivot_left=pivot_left, pivot_right=pivot_right,
        atr_period=atr_period, atr_stop_multiple=atr_stop_multiple,
        reward_risk=reward_risk, horizon=horizon,
    )
    common = {
        "probability_policy": "STRICT_RESEARCH",
        "probabilities_published": False,
        "historical_probabilities_available": False,
        "live_signal_eligible": False,
        "probability_status": "SUPPRESSED_VALIDATION_NOT_PASSED",
        "target_definition": f"Target ({reward_risk:g}R) touched before stop ({atr_stop_multiple:g} ATR) within {horizon} bars after next-candle-open entry.",
        "protocol_version": "mm-research-0.9.0-diagnostics",
        "data_snapshot": _dataset_snapshot(candles),
        "candles_analyzed": len(candles),
        "gates": gate,
        "walk_forward_protocol": {
            "design": "Expanding training window; sequential calibration and disjoint test windows; boundary-label purging plus embargo gaps.",
            "initial_train_fraction": wf["initial_train_fraction"],
            "calibration_fraction": wf["calibration_fraction"],
            "test_fraction": wf["test_fraction"],
            "step_fraction": wf["step_fraction"],
            "embargo_bars": wf["embargo_bars"],
            "minimum_completed_folds": wf["minimum_completed_folds"],
            "minimum_positive_skill_folds": wf["minimum_positive_skill_folds"],
            "bootstrap": "Moving-block bootstrap on paired OOS Brier loss differences.",
            "bootstrap_block_length_events": wf["bootstrap_block_length"],
            "bootstrap_replicates": wf["bootstrap_replicates"],
        },
        "evaluation": None,
        "folds": [],
        "regime_analysis": None,
        "historical_oos_predictions": [],
        "model_validation": {
            "live_signal_eligible": False,
            "production_eligibility": "NOT_ELIGIBLE_RESEARCH_ONLY",
            "reason": "Walk-forward evidence does not authorize live trading. Prospective paper trading, cost-aware execution validation, and drift monitoring remain separate release gates.",
        },
        "limitations": [
            "The probability target is target-before-stop within the configured horizon; it is not a general direction forecast or expected return.",
            "Same-candle stop and target touches are labelled STOP because OHLC bars do not reveal intrabar ordering.",
            "TIMEOUT is a negative target-before-stop label, not necessarily a net losing trade.",
            "Fees, spread, slippage, funding, borrow, market impact and execution failures are not included in the current event label.",
            "Trend regime labels use only the trailing 50-candle return; volatility labels compare ATR percent to a trailing historical mean that excludes the current candle.",
            "The moving-block bootstrap is an uncertainty diagnostic, not a cure for all dependence, non-stationarity or selection bias.",
            "A passing historical walk-forward gate is not live-signal eligibility; prospective paper-trading and ongoing monitoring are still required.",
        ],
    }
    if dataset["status"] != "OK":
        common.update({
            "status": "INSUFFICIENT_DATA",
            "events_found": 0, "labelled_events": 0, "right_censored_events": 0,
            "gate_failures": ["Not enough closed candles to construct causal structure events and outcome labels."],
            "message": "Not enough closed candles to run the strict walk-forward study.",
        })
        return common

    events = dataset["events"]
    label_audit = _audit_event_labels(events)
    common["label_audit"] = label_audit
    planned_folds = _walk_forward_folds(len(candles), wf)
    common.update({
        "events_found": dataset["signals_found"],
        "labelled_events": dataset["labelled_events"],
        "right_censored_events": dataset["right_censored"],
        "planned_folds": len(planned_folds),
    })
    if len(planned_folds) < int(wf["minimum_completed_folds"]):
        common.update({
            "status": "WALK_FORWARD_INSUFFICIENT_WINDOWS",
            "gate_failures": [f"Only {len(planned_folds)} chronological test windows can be formed; requires {wf['minimum_completed_folds']} ."],
            "message": "The dataset is too short for the required number of non-overlapping walk-forward test windows.",
        })
        return common

    fold_reports = []
    pooled_predictions: list[dict[str, Any]] = []
    all_failures: list[str] = []
    feature_fold_reports: list[dict[str, Any]] = []
    comparison_pooled: dict[str, dict[str, list[float]]] = {
        name: {"probabilities": []} for name in (
            "constant_training_rate", "direction_frequency", "event_type_frequency", "full_smc_logistic"
        )
    }
    comparison_labels: list[int] = []
    comparison_baselines: list[float] = []
    score_diagnostics: list[dict[str, Any]] = []
    if not label_audit["label_mapping_verified"]:
        all_failures.append("Outcome-to-label audit failed: positive class must equal TARGET and negative class must equal STOP or TIMEOUT.")
    for fold_index, bounds in enumerate(planned_folds, start=1):
        split = _split_events_for_fold(events, bounds)
        train, calibration, test = split["train"], split["calibration"], split["test"]
        counts = {name: _class_counts(rows) for name, rows in (("train", train), ("calibration", calibration), ("test", test))}
        fold_failures = []
        for name, threshold in (("train", "minimum_train_events"), ("calibration", "minimum_calibration_events"), ("test", "minimum_test_events")):
            if len(split[name]) < gate[threshold]:
                fold_failures.append(f"{name} has {len(split[name])} events; requires {gate[threshold]}.")
        for name, threshold in (("train", "minimum_train_per_class"), ("calibration", "minimum_calibration_per_class"), ("test", "minimum_test_per_class")):
            if counts[name]["positive_target_first"] < gate[threshold] or counts[name]["negative_stop_or_timeout"] < gate[threshold]:
                fold_failures.append(f"{name} requires at least {gate[threshold]} events in each outcome class.")
        report: dict[str, Any] = {
            "fold": fold_index, "boundaries": bounds, "counts": counts,
            "purged_boundary_events": split["purged"], "embargoed_events": split["embargoed"], "gate_failures": fold_failures,
            "evaluation": None, "platt_slope": None,
            "score_direction": None, "feature_diagnostics": None, "model_comparison": None,
        }
        if fold_failures:
            all_failures.extend([f"Fold {fold_index}: {reason}" for reason in fold_failures])
            fold_reports.append(report)
            continue

        model = _fit_logistic(train)
        calibration_logits = [_model_logit(model, row) for row in calibration]
        calibration_labels = [int(row["label"]) for row in calibration]
        slope, intercept = _fit_platt(calibration_logits, calibration_labels)
        if not math.isfinite(slope) or slope <= 0:
            reason = f"Fold {fold_index}: Platt slope is non-positive ({slope:.6f}); score/outcome ordering is unstable or inverted."
            all_failures.append(reason)
            report["gate_failures"].append(reason)
        train_logits = [_model_logit(model, row) for row in train]
        test_logits = [_model_logit(model, row) for row in test]
        probabilities = [_sigmoid(slope * value + intercept) for value in test_logits]
        labels = [int(row["label"]) for row in test]
        training_rate = sum(int(row["label"]) for row in train) / len(train)
        evaluation = _evaluate(probabilities, labels, baseline_rate=training_rate)
        train_auc = _binary_auc(train_logits, [int(row["label"]) for row in train])
        calibration_auc = _binary_auc(calibration_logits, calibration_labels)
        test_auc = _binary_auc(test_logits, labels)
        score_status = (
            "INVERTED_TEST_SCORE_ORDERING" if test_auc is not None and test_auc < 0.45
            else "POSITIVE_TEST_SCORE_ORDERING" if test_auc is not None and test_auc > 0.55
            else "NO_CLEAR_TEST_DISCRIMINATION"
        )
        score_direction = {
            "train_auc": train_auc,
            "calibration_auc": calibration_auc,
            "test_auc": test_auc,
            "test_score_ordering": score_status,
            "platt_slope": round(slope, 6),
            "diagnosis": "Test AUC below 0.5 means larger raw logits rank target-first labels lower than non-targets. The test set is diagnostic only; score direction is never flipped using test labels.",
        }
        feature_diagnostics = _feature_fold_diagnostics(train, test, model)
        model_comparison, fold_model_probabilities = _model_comparison_for_fold(
            train, calibration, test, probabilities, training_rate,
        )
        report.update({
            "platt_slope": round(slope, 6),
            "platt_intercept": round(intercept, 6),
            "evaluation": evaluation,
            "score_direction": score_direction,
            "feature_diagnostics": feature_diagnostics,
            "model_comparison": model_comparison,
        })
        score_diagnostics.append({"fold": fold_index, **score_direction})
        feature_fold_reports.append({"fold": fold_index, **feature_diagnostics["feature_results"]})
        for name, values in fold_model_probabilities.items():
            comparison_pooled[name]["probabilities"].extend(values)
        comparison_labels.extend(labels)
        comparison_baselines.extend([training_rate] * len(labels))
        report["brier_baseline_improved"] = bool(evaluation["beats_training_rate_baseline"])
        report["log_loss_baseline_improved"] = bool(evaluation["beats_training_rate_log_loss_baseline"])
        for row, probability in zip(test, probabilities):
            pooled_predictions.append({
                "signal_time": int(row["signal_time"]),
                "direction": row["direction"], "signal_type": row["signal_type"],
                "market_regime": row.get("market_regime", "UNKNOWN"),
                "volatility_regime": row.get("volatility_regime", "UNKNOWN"),
                "probability": probability, "label": int(row["label"]),
                "realized_outcome": row["outcome"], "baseline_probability": training_rate,
                "fold": fold_index,
            })
        fold_reports.append(report)

    valid_fold_reports = [row for row in fold_reports if row["evaluation"] is not None]
    positive_skill_folds = sum(
        1 for row in valid_fold_reports
        if row["evaluation"]["beats_training_rate_baseline"]
    )
    common["folds"] = fold_reports
    common["completed_folds"] = len(valid_fold_reports)
    common["positive_brier_skill_folds"] = positive_skill_folds
    common["score_direction_diagnostics"] = {
        "folds": score_diagnostics,
        "inverted_test_folds": sum(1 for item in score_diagnostics if item["test_score_ordering"] == "INVERTED_TEST_SCORE_ORDERING"),
        "positive_test_folds": sum(1 for item in score_diagnostics if item["test_score_ordering"] == "POSITIVE_TEST_SCORE_ORDERING"),
        "warning": "Do not reverse model scores based on test-set outcomes. A suspected inversion must be investigated on training/calibration data and then evaluated on a new untouched period.",
    }
    feature_summary = {}
    for feature_name in FEATURE_NAMES:
        feature_rows = [item[feature_name] for item in feature_fold_reports if feature_name in item]
        usable_auc = [row["test_auc_after_train_only_orientation"] for row in feature_rows if row["test_auc_after_train_only_orientation"] is not None]
        coefficients = [row["full_model_standardized_coefficient"] for row in feature_rows if row["full_model_standardized_coefficient"] is not None]
        orientations = [row["train_selected_orientation"] for row in feature_rows if row["train_selected_orientation"] != "UNRESOLVED"]
        feature_summary[feature_name] = {
            "folds_with_diagnostic": len(feature_rows),
            "mean_test_auc_after_train_only_orientation": round(sum(usable_auc) / len(usable_auc), 6) if usable_auc else None,
            "train_orientation_consistency": round(max(orientations.count("HIGHER_FEATURE_VALUE"), orientations.count("LOWER_FEATURE_VALUE")) / len(orientations), 4) if orientations else None,
            "mean_full_model_standardized_coefficient": round(sum(coefficients) / len(coefficients), 6) if coefficients else None,
            "fold_details": feature_rows,
        }
    common["feature_investigation"] = {
        "features": feature_summary,
        "method": "Per fold, orient each feature using training-only univariate AUC, then measure that fixed orientation on the test partition. Also report fold logistic standardized coefficients and test distribution shifts.",
        "caution": "Univariate AUC is marginal and does not account for feature correlations. These diagnostics do not automatically remove or promote features.",
    }
    if comparison_labels:
        common["model_comparison"] = _aggregate_model_comparisons(
            comparison_pooled, comparison_baselines, comparison_labels,
        )
    if len(valid_fold_reports) < int(wf["minimum_completed_folds"]):
        all_failures.append(f"Only {len(valid_fold_reports)} folds completed all sample gates; requires {wf['minimum_completed_folds']}.")
    if positive_skill_folds < int(wf["minimum_positive_skill_folds"]):
        all_failures.append(f"Only {positive_skill_folds} folds beat the Brier baseline; requires {wf['minimum_positive_skill_folds']}.")

    if pooled_predictions:
        pooled_predictions.sort(key=lambda row: (row["signal_time"], row["fold"]))
        probabilities = [float(row["probability"]) for row in pooled_predictions]
        labels = [int(row["label"]) for row in pooled_predictions]
        baselines = [float(row["baseline_probability"]) for row in pooled_predictions]
        aggregate = _evaluate(probabilities, labels, baselines)
        ci = _bootstrap_brier_skill_interval(
            probabilities, labels, baselines,
            block_length=int(wf["bootstrap_block_length"]),
            replicates=int(wf["bootstrap_replicates"]), seed=int(wf["bootstrap_seed"]),
        )
        aggregate["brier_skill_block_bootstrap_95"] = ci
        aggregate["bootstrap_block_length_events"] = int(wf["bootstrap_block_length"])
        aggregate["bootstrap_replicates"] = int(wf["bootstrap_replicates"])
        common["evaluation"] = aggregate
        if not aggregate["beats_training_rate_baseline"]:
            all_failures.append("Pooled walk-forward Brier score did not beat the fold-specific training-rate baselines.")
        if not aggregate["beats_training_rate_log_loss_baseline"]:
            all_failures.append("Pooled walk-forward log loss did not beat the fold-specific training-rate baselines.")
        if ci is None or ci[0] <= 0:
            all_failures.append("The 95% moving-block bootstrap interval for Brier skill does not lie entirely above zero.")
        if aggregate["expected_calibration_error"] > float(wf["maximum_aggregate_ece"]):
            all_failures.append(f"Pooled expected calibration error {aggregate['expected_calibration_error']:.4f} exceeds {wf['maximum_aggregate_ece']:.4f}.")

        trend_analysis = _regime_evaluations(
            pooled_predictions, minimum_events=int(wf["minimum_regime_events"]), dimension="market_regime",
        )
        volatility_analysis = _regime_evaluations(
            pooled_predictions, minimum_events=int(wf["minimum_regime_events"]), dimension="volatility_regime",
        )
        common["regime_analysis"] = {"trend": trend_analysis, "volatility": volatility_analysis}
        for dimension, analysis in (("trend", trend_analysis), ("volatility", volatility_analysis)):
            if analysis["populated_regime_count"] < int(wf["minimum_populated_regimes"]):
                all_failures.append(
                    f"Only {analysis['populated_regime_count']} {dimension} regimes have at least {wf['minimum_regime_events']} OOS events and both outcome classes; requires {wf['minimum_populated_regimes']}."
                )
            for regime, details in analysis["groups"].items():
                metrics = details["evaluation"]
                if metrics is not None and not metrics["beats_training_rate_baseline"]:
                    all_failures.append(f"{dimension.title()} regime {regime} does not beat its fold-specific training-rate baseline.")
    else:
        empty = {"groups": {}, "populated_regimes": [], "populated_regime_count": 0}
        common["regime_analysis"] = {"trend": empty, "volatility": empty}
        all_failures.append("No out-of-sample predictions could be generated.")

    # Preserve failure reasons in first-occurrence order for readable API and dashboard output.
    failures = list(dict.fromkeys(all_failures))
    common["gate_failures"] = failures
    passed = not failures and len(valid_fold_reports) >= int(wf["minimum_completed_folds"])
    common["status"] = "WALK_FORWARD_VALIDATED_RESEARCH" if passed else "PROBABILITIES_SUPPRESSED_VALIDATION_FAILED"
    common["probability_status"] = "HISTORICAL_OOS_VALIDATED_NOT_LIVE" if passed else "SUPPRESSED_VALIDATION_FAILED"
    common["probabilities_published"] = bool(passed)
    common["historical_probabilities_available"] = bool(passed)
    if passed:
        common["historical_oos_predictions"] = [
            {
                "signal_time": row["signal_time"], "direction": row["direction"],
                "signal_type": row["signal_type"], "market_regime": row["market_regime"],
                "volatility_regime": row["volatility_regime"],
                "probability_target_before_stop": round(row["probability"], 4),
                "realized_outcome": row["realized_outcome"], "label": row["label"],
                "fold": row["fold"],
            }
            for row in pooled_predictions[-200:]
        ]
        common["message"] = "Historical out-of-sample probabilities passed the declared walk-forward research gates. Live signal use remains disabled."
    else:
        # Do not leak predicted probabilities through per-event rows or reliability-bin means.
        common["historical_oos_predictions"] = []
        if isinstance(common.get("evaluation"), dict):
            common["evaluation"].pop("calibration_bins", None)
        for fold_report in common["folds"]:
            fold_evaluation = fold_report.get("evaluation")
            if isinstance(fold_evaluation, dict):
                fold_evaluation.pop("calibration_bins", None)
        for dimension_report in (common.get("regime_analysis") or {}).values():
            for regime_details in dimension_report.get("groups", {}).values():
                regime_evaluation = regime_details.get("evaluation")
                if isinstance(regime_evaluation, dict):
                    regime_evaluation.pop("calibration_bins", None)
        for comparison in (common.get("model_comparison") or {}).get("models", {}).values():
            if isinstance(comparison, dict):
                comparison.pop("calibration_bins", None)
        for fold_report in common["folds"]:
            for comparison in (fold_report.get("model_comparison") or {}).get("metrics", {}).values():
                if isinstance(comparison, dict):
                    comparison.pop("calibration_bins", None)
        common["message"] = "Probabilities are suppressed because one or more predeclared walk-forward validation gates failed. Only aggregate scoring diagnostics, feature/score diagnostics, model benchmark metrics and gate failures are returned."
    common["disclaimer"] = "Strict research mode. No live trading probabilities or alerts are authorized by this historical study."
    return common
