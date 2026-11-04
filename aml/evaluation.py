"""Score signals and case queues against the synthetic laundering labels.

Labels are only read here, after every signal and ranking has been computed.
"""
import pandas as pd

DAILY = ["fan_out", "fan_in", "return_transfer"]
GRAPH = ["cycle", "scatter_gather"]
SIGNALS = DAILY + GRAPH
QUEUE_DEPTHS = [25, 50, 100, 250, 500, 1000]


def score(flagged: pd.Series, label: pd.Series) -> dict:
    """Transfer-level precision, recall and lift over the base rate."""
    positives = int(label.sum())
    hits = int(flagged.sum())
    true_positive = int((flagged & (label == 1)).sum())
    base_rate = positives / len(label) if len(label) else 0.0
    precision = true_positive / hits if hits else 0.0
    return {
        "flagged": hits,
        "true_positive": true_positive,
        "precision": precision,
        "recall": true_positive / positives if positives else 0.0,
        "lift": precision / base_rate if base_rate else 0.0,
    }


def signal_report(frame: pd.DataFrame, signals: pd.DataFrame) -> dict:
    """One score per signal, per signal family and for everything combined."""
    groups = {name: signals[name] for name in SIGNALS}
    groups["any daily rule"] = signals[DAILY].any(axis=1)
    groups["any graph pattern"] = signals[GRAPH].any(axis=1)
    groups["any signal"] = signals[SIGNALS].any(axis=1)
    return {name: score(flags, frame.label) for name, flags in groups.items()}


def build_cases(frame: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """One case per payer and calendar day that has at least one flagged outgoing transfer."""
    hit = signals[SIGNALS].any(axis=1)
    rows = frame.loc[hit, ["day", "source", "source_row"]].copy()
    rows["daily"] = signals.loc[hit, DAILY].sum(axis=1)
    rows["signals"] = signals.loc[hit, SIGNALS].sum(axis=1)
    rows["patterns"] = signals.loc[hit, "pattern_ids"]
    rows["graph"] = signals.loc[hit, GRAPH].any(axis=1)
    grouped = rows.groupby(["day", "source"])
    cases = grouped.agg(transfers=("source_row", "size"), graph_transfers=("graph", "sum"),
                        daily_hits=("daily", "sum"),
                        max_daily_overlap=("daily", "max"), signal_count=("signals", "sum"),
                        max_overlap=("signals", "max"))
    cases["graph_patterns"] = grouped.patterns.agg(lambda ids: len(set(" ".join(ids).split())))
    top = rows.loc[rows.signals == rows.groupby(["day", "source"]).signals.transform("max")]
    cases["example_row"] = top.groupby(["day", "source"]).source_row.min()
    return cases.reset_index()


def rank(cases: pd.DataFrame, use_graph: bool = True) -> pd.DataFrame:
    """Order cases for review. Labels play no part.

    The original queue keeps only cases with a daily-rule hit and ranks them by the
    most daily rules on one transfer, then total daily hits, then transfer count.
    With graph patterns, every case in a cycle or scatter-gather goes first, ordered by
    how many patterns and pattern transfers it has; the original queue follows unchanged.
    """
    keys = ["max_daily_overlap", "daily_hits", "transfers"]
    if use_graph:
        keys = ["graph_patterns", "graph_transfers"] + keys
        queue = cases
    else:
        queue = cases.loc[cases.daily_hits > 0]
    return queue.sort_values(keys + ["day", "source"], ascending=[False] * len(keys) + [True, True])


def labelled_cases(frame: pd.DataFrame) -> set:
    """(day, payer) pairs with at least one outgoing transfer carrying the laundering label."""
    positive = frame.loc[frame.label == 1]
    return set(zip(positive.day, positive.source))


def queue_report(queue: pd.DataFrame, positives: set, depths=QUEUE_DEPTHS) -> dict:
    found = pd.Series([(d, s) in positives for d, s in zip(queue.day, queue.source)], dtype=bool)
    report = {"candidate_cases": len(queue), "labelled_cases": len(positives),
              "candidate_recall": float(found.sum() / len(positives)) if positives else 0.0}
    for depth in depths:
        top = found.iloc[:depth]
        report[f"precision_at_{depth}"] = float(top.mean()) if len(top) else 0.0
        report[f"found_at_{depth}"] = int(top.sum())
    return report
