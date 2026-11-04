"""Run every signal over HI-Small, export the evidence and score it against the labels.

Outputs in data/processed/:
  alerts.csv            one row per flagged transfer, with each signal and its pattern IDs
  patterns.csv          every detected cycle and scatter-gather, with its transfers
  ranked_cases.csv      payer-day review queue, graph patterns first
  evaluation.json       transfer-level precision, recall and lift per signal and period
  case_evaluation.json  precision@k of the review queue, with and without graph patterns
"""
import json
import time

import pandas as pd

from aml.data import OUTPUT, entity_name, load_entities, load_transactions
from aml.evaluation import (SIGNALS, build_cases, labelled_cases, queue_report, rank,
                            score, signal_report)
from aml.signals import (MAX_CYCLE_LENGTH, MIN_MIDDLE, daily_signals, flag_patterns,
                         scatter_gather, temporal_cycles)

PERIODS = {
    "Sep 1-5": ("2022-09-01", "2022-09-05"),
    "Sep 6-10": ("2022-09-06", "2022-09-10"),
    "Sep 11-18 (tail)": ("2022-09-11", "2022-09-18"),
}
HOLDOUT = ("2022-09-08", "2022-09-18")      # the period the original queue was reported on


def in_period(frame: pd.DataFrame, period: tuple) -> pd.Series:
    return frame.day.between(*period)


def describe(patterns, accounts, entities, frame) -> pd.DataFrame:
    labels = frame.set_index("source_row").label
    records = []
    for number, pattern in enumerate(patterns, 1):
        names = [accounts[a] for a in pattern.accounts]
        records.append({
            "pattern_id": f"P{number}",
            "kind": pattern.kind,
            "accounts": " > ".join(names),
            "entities": " > ".join(entity_name(entities, n) for n in names),
            "transfers": len(pattern.rows),
            "start": pd.Timestamp(pattern.start, unit="m").strftime("%Y-%m-%d %H:%M"),
            "end": pd.Timestamp(pattern.end, unit="m").strftime("%Y-%m-%d %H:%M"),
            "hours": round((pattern.end - pattern.start) / 60, 1),
            "labelled_transfers": int(labels.loc[list(pattern.rows)].sum()),
            "source_rows": " ".join(map(str, pattern.rows)),
        })
    return pd.DataFrame(records)


def sensitivity(frame, cycles) -> dict:
    """How the graph signals respond to their two main settings."""
    report = {}
    for length in (4, 6, MAX_CYCLE_LENGTH):
        kept = [p for p in cycles if len(p.accounts) <= length]
        report[f"cycle, up to {length} accounts"] = score(flag_patterns(frame, kept).cycle, frame.label)
    for middle in (2, 3, 4, 5):
        found = scatter_gather(frame, min_middle=middle)
        report[f"scatter-gather, {middle}+ intermediaries"] = score(
            flag_patterns(frame, found).scatter_gather, frame.label)
    return report


def main():
    started = time.time()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frame, accounts = load_transactions()
    entities = load_entities()
    print(f"loaded {len(frame):,} transfers in {time.time() - started:.0f}s")

    signals = daily_signals(frame)
    cycles = temporal_cycles(frame)
    gathers = scatter_gather(frame, min_middle=MIN_MIDDLE)
    patterns = cycles + gathers
    signals = signals.join(flag_patterns(frame, patterns))
    print(f"{len(cycles)} cycles, {len(gathers)} scatter-gathers after {time.time() - started:.0f}s")

    flagged = signals[SIGNALS].any(axis=1)
    alerts = frame.loc[flagged].join(signals.loc[flagged])
    alerts.insert(1, "payer", accounts[alerts.source.to_numpy()])
    alerts.insert(2, "payee", accounts[alerts.target.to_numpy()])
    alerts["payer_entity"] = [entity_name(entities, a) for a in alerts.payer]
    alerts["payee_entity"] = [entity_name(entities, a) for a in alerts.payee]
    alerts.drop(columns=["source", "target", "minute", "day"]).to_csv(OUTPUT / "alerts.csv", index=False)
    describe(patterns, accounts, entities, frame).to_csv(OUTPUT / "patterns.csv", index=False)

    days = frame.groupby("day").label.agg(transfers="size", labelled="sum")
    evaluation = {
        "transactions": len(frame),
        "labelled_positive": int(frame.label.sum()),
        "base_rate": float(frame.label.mean()),
        "signals": signal_report(frame, signals),
        "periods": {name: {"transactions": int(in_period(frame, p).sum()),
                           "labelled_positive": int(frame.label[in_period(frame, p)].sum()),
                           "signals": signal_report(frame[in_period(frame, p)], signals[in_period(frame, p)])}
                    for name, p in PERIODS.items()},
        "days": {day: {"transfers": int(r.transfers), "labelled": int(r.labelled)} for day, r in days.iterrows()},
        "sensitivity": sensitivity(frame, cycles),
    }
    (OUTPUT / "evaluation.json").write_text(json.dumps(evaluation, indent=2))

    cases = build_cases(frame, signals)
    positives = labelled_cases(frame)
    queue = rank(cases)
    baseline = rank(cases, use_graph=False)
    late = {(d, s) for d, s in positives if HOLDOUT[0] <= d <= HOLDOUT[1]}
    case_evaluation = {
        "case": "payer account and calendar day; positive if any outgoing transfer is labelled",
        "all_days": {"graph_ranking": queue_report(queue, positives),
                     "daily_rules_ranking": queue_report(baseline, positives)},
        f"{HOLDOUT[0]}_to_{HOLDOUT[1]}": {
            "graph_ranking": queue_report(queue.loc[queue.day.between(*HOLDOUT)], late),
            "daily_rules_ranking": queue_report(baseline.loc[baseline.day.between(*HOLDOUT)], late)},
    }
    (OUTPUT / "case_evaluation.json").write_text(json.dumps(case_evaluation, indent=2))

    queue = queue.assign(payer=accounts[queue.source.to_numpy()],
                         labelled_case=[(d, s) in positives for d, s in zip(queue.day, queue.source)])
    queue.drop(columns="source").to_csv(OUTPUT / "ranked_cases.csv", index=False)

    for name, result in evaluation["signals"].items():
        print(f"{name:18} flagged {result['flagged']:>8,}  precision {result['precision']:7.2%}  "
              f"recall {result['recall']:6.2%}  lift {result['lift']:7.1f}x")
    print("queue precision@100:", case_evaluation["all_days"]["graph_ranking"]["precision_at_100"],
          "vs daily rules only:", case_evaluation["all_days"]["daily_rules_ranking"]["precision_at_100"])
    print(f"done in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
