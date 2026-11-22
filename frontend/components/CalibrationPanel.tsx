"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

type SplitCount = {
  events: number;
  positive_target_first: number;
  negative_stop_or_timeout: number;
};

type Evaluation = {
  test_events: number;
  positive_target_first: number;
  observed_target_rate: number;
  observed_target_rate_wilson_95: number[] | null;
  brier_score: number;
  brier_score_baseline_training_rate: number;
  baseline_probability_training_target_rate: number;
  brier_skill_score_vs_training_baseline: number | null;
  beats_training_rate_baseline: boolean | null;
  log_loss: number;
  log_loss_baseline_training_rate: number;
  log_loss_skill_vs_training_baseline: number | null;
  beats_training_rate_log_loss_baseline: boolean;
  expected_calibration_error: number;
  brier_skill_block_bootstrap_95?: number[] | null;
};

type Fold = {
  fold: number;
  counts: { train: SplitCount; calibration: SplitCount; test: SplitCount };
  purged_boundary_events: { train: number; calibration: number; test: number };
  platt_slope: number | null;
  evaluation: Evaluation | null;
  gate_failures: string[];
  brier_baseline_improved?: boolean;
  log_loss_baseline_improved?: boolean;
};

type CalibrationStudy = {
  status: string;
  probability_policy: string;
  probability_status: string;
  probabilities_published: boolean;
  historical_probabilities_available: boolean;
  live_signal_eligible: boolean;
  target_definition?: string;
  protocol_version?: string;
  data_snapshot?: { sha256: string; candle_count: number };
  candles_analyzed?: number;
  events_found?: number;
  labelled_events?: number;
  right_censored_events?: number;
  planned_folds?: number;
  completed_folds?: number;
  positive_brier_skill_folds?: number;
  gate_failures?: string[];
  evaluation?: Evaluation | null;
  folds?: Fold[];
  label_audit?: {
    events_audited: number;
    label_mapping_verified: boolean;
    positive_target_count: number;
    negative_stop_or_timeout_count: number;
    label_mismatch_rows: number[];
    invalid_event_rows: number[];
  };
  score_direction_diagnostics?: {
    inverted_test_folds: number;
    positive_test_folds: number;
    folds: Array<{ fold: number; train_auc: number | null; calibration_auc: number | null; test_auc: number | null; platt_slope: number; test_score_ordering: string }>;
  };
  feature_investigation?: {
    features: Record<string, {
      folds_with_diagnostic: number;
      mean_test_auc_after_train_only_orientation: number | null;
      train_orientation_consistency: number | null;
      mean_full_model_standardized_coefficient: number | null;
    }>;
    method: string;
    caution: string;
  };
  model_comparison?: {
    same_oos_events: number;
    models: Record<string, Evaluation>;
    diagnostic_brier_order: string[];
    selection_policy: string;
  };
  regime_analysis?: {
    trend: {
      groups: Record<string, { events: number; evaluation: Evaluation | null }>;
      populated_regimes: string[];
      populated_regime_count: number;
    };
    volatility: {
      groups: Record<string, { events: number; evaluation: Evaluation | null }>;
      populated_regimes: string[];
      populated_regime_count: number;
    };
  } | null;
  historical_oos_predictions?: Array<{
    signal_time: number;
    direction: string;
    signal_type: string;
    market_regime: string;
    volatility_regime: string;
    probability_target_before_stop: number;
    realized_outcome: string;
    label: number;
    fold: number;
  }>;
  limitations?: string[];
  message?: string;
};

type ApiResponse = {
  symbol: string;
  interval: string;
  data_status: string;
  source: string;
  stored_candles: number;
  study: CalibrationStudy;
};

function stamp(value: number) {
  return new Date(value * 1000).toLocaleString();
}

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function metric(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : value.toFixed(4);
}

export default function CalibrationPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setIntervalValue] = useState("1h");
  const [limit, setLimit] = useState("20000");
  const [result, setResult] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runStudy() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${API}/market/research/walk-forward?symbol=${symbol}&interval=${interval}&limit=${limit}`,
        { cache: "no-store" }
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Walk-forward study request failed");
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run walk-forward study");
    } finally {
      setLoading(false);
    }
  }

  const study = result?.study;
  const evaluation = study?.evaluation;
  const validated = study?.status === "WALK_FORWARD_VALIDATED_RESEARCH" &&
    study.probabilities_published === true && study.historical_probabilities_available === true;

  return (
    <section className="section calibrationSection">
      <div className="sectionHeading">
        <div><p className="eyebrow">STRICT RESEARCH QUALITY GATE</p><h2>Walk-Forward Probability Lab</h2></div>
        <span className="smallMuted">Expanding windows · Purged labels · Block-bootstrap uncertainty</span>
      </div>

      <div className="calibrationIntro">
        <strong>Publication policy</strong>
        <p>Historical probabilities stay hidden unless the model beats its training-rate baseline across the declared walk-forward tests, passes calibration and regime checks, and has a positive lower confidence bound for Brier skill. A pass still does not authorize live alerts or trading.</p>
      </div>

      <div className="backtestControls">
        <label>Market<select value={symbol} onChange={(e) => setSymbol(e.target.value)}><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option></select></label>
        <label>Timeframe<select value={interval} onChange={(e) => setIntervalValue(e.target.value)}><option value="15m">15 minutes</option><option value="30m">30 minutes</option><option value="1h">1 hour</option><option value="2h">2 hours</option><option value="4h">4 hours</option><option value="1d">1 day</option></select></label>
        <label>History<select value={limit} onChange={(e) => setLimit(e.target.value)}><option value="5000">5,000 candles</option><option value="10000">10,000 candles</option><option value="20000">20,000 candles</option></select></label>
        <button className="primaryButton" onClick={runStudy} disabled={loading}>{loading ? "Fetching history & validating…" : "Run strict walk-forward study"}</button>
      </div>

      {error && <div className="error">{error}</div>}
      {!study && <p className="panelHint">The study uses public historical market candles, causal SMC event features, next-candle-open outcome labels, and five sequential expanding-window test periods. Only summary diagnostics are returned when a validation gate fails; raw probability estimates remain suppressed.</p>}

      {study && <>
        <div className="calibrationMeta">{result?.symbol} · {result?.interval} · {result?.data_status} · {result?.stored_candles.toLocaleString()} stored candles · {study.labelled_events ?? 0} labelled events · {study.planned_folds ?? 0} planned folds · {study.completed_folds ?? 0} completed folds</div>
        {study.data_snapshot && <div className="snapshotMeta">Dataset SHA-256: <code>{study.data_snapshot.sha256}</code> · Protocol: {study.protocol_version ?? "—"}</div>}

        <div className={`calibrationStatus ${validated ? "successStatus" : "warningStatus"}`}>
          <strong>{validated ? "Historical walk-forward research gates passed" : "Probabilities suppressed — strict validation not passed"}</strong>
          <span>{study.message ?? "See the diagnostics below for the evidence and failed gates."}</span>
          <span>Live signal eligibility: <b>DISABLED</b></span>
        </div>

        {evaluation && <>
          <div className="backtestMetrics calibrationMetrics">
            <article><span>Pooled OOS events</span><strong>{evaluation.test_events}</strong></article>
            <article><span>Model Brier</span><strong>{metric(evaluation.brier_score)}</strong></article>
            <article><span>Baseline Brier</span><strong>{metric(evaluation.brier_score_baseline_training_rate)}</strong></article>
            <article><span>Brier skill</span><strong className={(evaluation.brier_skill_score_vs_training_baseline ?? 0) > 0 ? "positive" : "negative"}>{metric(evaluation.brier_skill_score_vs_training_baseline)}</strong></article>
            <article><span>Model log loss</span><strong>{metric(evaluation.log_loss)}</strong></article>
            <article><span>Baseline log loss</span><strong>{metric(evaluation.log_loss_baseline_training_rate)}</strong></article>
            <article><span>Expected calibration error</span><strong>{metric(evaluation.expected_calibration_error)}</strong></article>
            <article><span>95% block-bootstrap Brier skill</span><strong>{evaluation.brier_skill_block_bootstrap_95?.map((v) => v.toFixed(4)).join(" – ") ?? "Unavailable"}</strong></article>
          </div>
          <p className="panelHint">Observed target-first rate: {pct(evaluation.observed_target_rate)}; nominal Wilson 95% interval: {evaluation.observed_target_rate_wilson_95?.map(pct).join(" – ") ?? "unavailable"}. The block-bootstrap interval is used as the strict uncertainty gate; the nominal Wilson interval does not adjust for event dependence.</p>
        </>}

        <div className="calibrationSubPanel">
          <h3>Walk-forward fold diagnostics</h3>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Fold</th><th>Train</th><th>Calibrate</th><th>Test</th><th>Platt slope</th><th>Brier skill</th><th>Result</th></tr></thead><tbody>
            {(study.folds ?? []).map((fold) => <tr key={fold.fold}>
              <td>{fold.fold}</td>
              <td>{fold.counts.train.events} ({fold.counts.train.positive_target_first}/{fold.counts.train.negative_stop_or_timeout})</td>
              <td>{fold.counts.calibration.events} ({fold.counts.calibration.positive_target_first}/{fold.counts.calibration.negative_stop_or_timeout})</td>
              <td>{fold.counts.test.events} ({fold.counts.test.positive_target_first}/{fold.counts.test.negative_stop_or_timeout})</td>
              <td>{metric(fold.platt_slope)}</td>
              <td>{metric(fold.evaluation?.brier_skill_score_vs_training_baseline)}</td>
              <td className={fold.gate_failures.length === 0 && fold.brier_baseline_improved ? "positive" : "negative"}>{fold.gate_failures.length > 0 ? "Gate failed" : fold.brier_baseline_improved ? "Brier pass" : "Brier miss"}</td>
            </tr>)}
          </tbody></table></div>
        </div>

        {study.regime_analysis && <div className="calibrationSubPanel">
          <h3>Market-regime robustness</h3>
          <p className="panelHint">Regimes are assigned from trailing 50-candle returns only. A regime contributes to validation when it has at least 50 OOS events and both outcome classes.</p>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Dimension</th><th>Regime</th><th>Events</th><th>Brier skill</th><th>Baseline improved?</th></tr></thead><tbody>
            {(["trend", "volatility"] as const).flatMap((dimension) => Object.entries(study.regime_analysis?.[dimension].groups ?? {}).map(([name, group]) => <tr key={`${dimension}-${name}`}><td>{dimension}</td><td>{name}</td><td>{group.events}</td><td>{metric(group.evaluation?.brier_skill_score_vs_training_baseline)}</td><td>{group.evaluation ? (group.evaluation.beats_training_rate_baseline ? "Yes" : "No") : "Insufficient sample"}</td></tr>))}
          </tbody></table></div>
        </div>}

        {study.label_audit && <div className="calibrationSubPanel">
          <h3>Outcome label and score-direction audit</h3>
          <p>Positive class mapping: TARGET = 1; STOP and TIMEOUT = 0. Audit: <strong>{study.label_audit.label_mapping_verified ? "PASS" : "FAIL"}</strong> · {study.label_audit.events_audited} events · {study.label_audit.positive_target_count} positive · {study.label_audit.negative_stop_or_timeout_count} negative · {study.label_audit.label_mismatch_rows.length} mapping mismatches.</p>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Fold</th><th>Train AUC</th><th>Calibration AUC</th><th>Test AUC</th><th>Platt slope</th><th>Test score order</th></tr></thead><tbody>
            {(study.score_direction_diagnostics?.folds ?? []).map((item) => <tr key={item.fold}><td>{item.fold}</td><td>{metric(item.train_auc)}</td><td>{metric(item.calibration_auc)}</td><td>{metric(item.test_auc)}</td><td>{metric(item.platt_slope)}</td><td>{item.test_score_ordering}</td></tr>)}
          </tbody></table></div>
          <p>Test labels are diagnostic only. MarketMind does not flip or reverse scores based on test-set outcomes.</p>
        </div>}

        {study.feature_investigation && <div className="calibrationSubPanel">
          <h3>SMC feature investigation</h3>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Feature</th><th>Fold diagnostics</th><th>Mean test AUC*</th><th>Train orientation consistency</th><th>Mean standardized coefficient</th></tr></thead><tbody>
            {Object.entries(study.feature_investigation.features).map(([name, feature]) => <tr key={name}><td>{name}</td><td>{feature.folds_with_diagnostic}</td><td>{metric(feature.mean_test_auc_after_train_only_orientation)}</td><td>{feature.train_orientation_consistency === null ? "—" : pct(feature.train_orientation_consistency)}</td><td>{metric(feature.mean_full_model_standardized_coefficient)}</td></tr>)}
          </tbody></table></div>
          <p>*Feature direction is selected from training data only. These marginal comparisons are exploratory and do not automatically remove or promote features.</p>
        </div>}

        {study.model_comparison && <div className="calibrationSubPanel">
          <h3>Transparent benchmark comparison</h3>
          <p>Same {study.model_comparison.same_oos_events} out-of-sample events across all comparisons. All results are diagnostics, not permission to select a challenger using these same test windows.</p>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Benchmark</th><th>Brier</th><th>Brier skill vs training prior</th><th>Log loss</th><th>Calibration error</th></tr></thead><tbody>
            {Object.entries(study.model_comparison.models).map(([name, model]) => <tr key={name}><td>{name.replace(/_/g, " ")}</td><td>{metric(model.brier_score)}</td><td>{metric(model.brier_skill_score_vs_training_baseline)}</td><td>{metric(model.log_loss)}</td><td>{metric(model.expected_calibration_error)}</td></tr>)}
          </tbody></table></div>
          <p>{study.model_comparison.selection_policy}</p>
        </div>}

        {(study.gate_failures?.length ?? 0) > 0 && <div className="gateFailures"><strong>Publication gate failures</strong>{study.gate_failures?.map((reason) => <p key={reason}>• {reason}</p>)}</div>}

        {validated && <div className="calibrationSubPanel predictionPanel">
          <h3>Historical out-of-sample estimates · not live forecasts</h3>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Signal time</th><th>Direction</th><th>Event</th><th>Regime</th><th>Historical probability</th><th>Realised outcome</th><th>Fold</th></tr></thead><tbody>
            {(study.historical_oos_predictions ?? []).slice(-40).reverse().map((item, index) => <tr key={`${item.signal_time}-${index}`}><td>{stamp(item.signal_time)}</td><td>{item.direction}</td><td>{item.signal_type}</td><td>{item.market_regime} / {item.volatility_regime}</td><td>{pct(item.probability_target_before_stop)}</td><td className={item.label ? "positive" : "negative"}>{item.realized_outcome}</td><td>{item.fold}</td></tr>)}
          </tbody></table></div>
        </div>}

        <div className="calibrationFooter">
          <strong>Target:</strong> {study.target_definition ?? "Not available"}
          <p>Strict research mode always keeps live signal eligibility disabled. Passing historical validation is not proof of future performance, profitability after costs, or stable calibration.</p>
          <p>Dataset records: {study.data_snapshot?.candle_count ?? study.candles_analyzed ?? 0} candles · {study.events_found ?? 0} detected events · {study.right_censored_events ?? 0} right-censored events.</p>
          {(study.limitations ?? []).map((item) => <p key={item}>{item}</p>)}
        </div>
      </>}
    </section>
  );
}
