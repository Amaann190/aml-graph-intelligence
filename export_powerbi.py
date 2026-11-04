"""Write the small, tidy tables the Power BI report reads. Output: data/processed/powerbi/*.csv

Run after analyze.py. Every file is derived from the evaluation JSON files,
patterns.csv and ranked_cases.csv, so the report never needs the 476 MB raw data.
"""
import json

import pandas as pd

from aml.data import OUTPUT

POWERBI = OUTPUT / "powerbi"
SIGNALS = [
    ("fan_out", "Fan-out", "Daily rule"),
    ("fan_in", "Fan-in", "Daily rule"),
    ("return_transfer", "Return transfer", "Daily rule"),
    ("cycle", "Temporal cycle", "Graph pattern"),
    ("scatter_gather", "Scatter-gather", "Graph pattern"),
    ("any daily rule", "Any daily rule", "Combined"),
    ("any graph pattern", "Any graph pattern", "Combined"),
    ("any signal", "Any signal", "Combined"),
]
CASES_KEPT = 1000


def signal_rows(signals: dict) -> pd.DataFrame:
    rows = []
    for order, (key, label, family) in enumerate(SIGNALS, 1):
        result = signals[key]
        rows.append({"order": order, "signal": label, "family": family, "flagged": result["flagged"],
                     "true_positive": result["true_positive"], "precision": result["precision"],
                     "recall": result["recall"], "lift": result["lift"]})
    return pd.DataFrame(rows)


def main():
    POWERBI.mkdir(parents=True, exist_ok=True)
    evaluation = json.loads((OUTPUT / "evaluation.json").read_text())
    cases = json.loads((OUTPUT / "case_evaluation.json").read_text())
    patterns = pd.read_csv(OUTPUT / "patterns.csv")
    queue = pd.read_csv(OUTPUT / "ranked_cases.csv")

    signals = signal_rows(evaluation["signals"])
    signals.to_csv(POWERBI / "signals.csv", index=False)

    periods = []
    for order, (name, period) in enumerate(evaluation["periods"].items(), 1):
        for group in ("any daily rule", "any graph pattern"):
            result = period["signals"][group]
            periods.append({"order": order, "period": name, "group": group.replace("any ", "").capitalize() + "s",
                            "transactions": period["transactions"], "labelled": period["labelled_positive"],
                            "flagged": result["flagged"], "precision": result["precision"],
                            "recall": result["recall"]})
    pd.DataFrame(periods).to_csv(POWERBI / "periods.csv", index=False)

    days = pd.DataFrame([{"day": day, **values} for day, values in evaluation["days"].items()])
    days["labelled_share"] = days.labelled / days.transfers
    days.to_csv(POWERBI / "days.csv", index=False)

    depth_rows = []
    for key, label in [("graph_ranking", "Graph patterns first"), ("daily_rules_ranking", "Daily rules only")]:
        result = cases["all_days"][key]
        for name, value in result.items():
            if name.startswith("precision_at_"):
                depth = int(name.rsplit("_", 1)[1])
                depth_rows.append({"ranking": label, "depth": depth, "precision": value,
                                   "found": result[f"found_at_{depth}"]})
    pd.DataFrame(depth_rows).to_csv(POWERBI / "queue_depths.csv", index=False)

    top = queue.head(CASES_KEPT).copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    top["labelled_case"] = top.labelled_case.map({True: "Labelled", False: "Not labelled"})
    top[["rank", "day", "payer", "graph_patterns", "graph_transfers", "transfers", "daily_hits",
         "max_overlap", "example_row", "labelled_case"]].to_csv(POWERBI / "review_queue.csv", index=False)

    view = patterns.drop(columns="source_rows").copy()
    view["accounts_in_pattern"] = view.accounts.str.count(">") + 1
    view["labelled_share"] = view.labelled_transfers / view.transfers
    view["kind"] = view.kind.map({"cycle": "Temporal cycle", "scatter_gather": "Scatter-gather"})
    view["start_day"] = view.start.str[:10]
    view.to_csv(POWERBI / "patterns.csv", index=False)

    graph, daily = evaluation["signals"]["any graph pattern"], evaluation["signals"]["any daily rule"]
    pd.DataFrame([{
        "transactions": evaluation["transactions"],
        "labelled": evaluation["labelled_positive"],
        "base_rate": evaluation["base_rate"],
        "patterns": len(patterns),
        "graph_flagged": graph["flagged"], "graph_precision": graph["precision"],
        "graph_recall": graph["recall"], "graph_lift": graph["lift"],
        "daily_flagged": daily["flagged"], "daily_precision": daily["precision"], "daily_recall": daily["recall"],
        "queue_p100_graph": cases["all_days"]["graph_ranking"]["precision_at_100"],
        "queue_p100_daily": cases["all_days"]["daily_rules_ranking"]["precision_at_100"],
    }]).to_csv(POWERBI / "summary.csv", index=False)
    print("wrote", sorted(p.name for p in POWERBI.glob("*.csv")))


if __name__ == "__main__":
    main()
