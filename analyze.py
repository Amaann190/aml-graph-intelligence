"""Score daily bank-account graphs and export transaction-level evidence."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data/raw"
OUTPUT = ROOT / "data/processed"
FAN_THRESHOLD = 10


def score_day(frame):
    edges = frame.loc[frame.source != frame.target].copy()
    outgoing = edges.groupby("source").target.nunique()
    incoming = edges.groupby("target").source.nunique()
    edges["out_degree"] = edges.source.map(outgoing)
    edges["in_degree"] = edges.target.map(incoming)
    first = edges.groupby(["source", "target"]).time.min()
    reverse = pd.MultiIndex.from_arrays([edges.target, edges.source])
    earlier = pd.Series(first.reindex(reverse).to_numpy(), index=edges.index)
    edges["return_transfer"] = earlier.fillna("9999") < edges.time
    edges["fan_out"] = edges.out_degree >= FAN_THRESHOLD
    edges["fan_in"] = edges.in_degree >= FAN_THRESHOLD
    return edges.loc[edges[["return_transfer", "fan_in", "fan_out"]].any(axis=1)].copy()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    accounts = pd.read_csv(RAW / "HI-Small_accounts.csv", dtype=str)
    entities = dict(zip(accounts["Bank ID"] + "/" + accounts["Account Number"], accounts["Entity Name"]))
    counts = Counter()
    columns = ["time", "from_bank", "payer", "to_bank", "payee", "received", "receiving_currency",
               "paid", "payment_currency", "format", "label"]
    with TemporaryDirectory(dir=OUTPUT) as temp:
        staging = Path(temp)
        for batch, part in enumerate(pd.read_csv(RAW / "HI-Small_Trans.csv", header=0,
                                                names=columns, dtype=str, chunksize=200000)):
            part["source_row"] = part.index + 2
            part["source"] = part.from_bank + "/" + part.payer
            part["target"] = part.to_bank + "/" + part.payee
            for day, rows in part.groupby(part.time.str[:10].str.replace("/", "-")):
                directory = staging / day
                directory.mkdir(exist_ok=True)
                rows.to_pickle(directory / f"{batch}.pkl")
        alerts_file = staging / "alerts.csv"
        for day in sorted(p for p in staging.iterdir() if p.is_dir()):
            rows = pd.concat(pd.read_pickle(p) for p in day.glob("*.pkl"))
            alerts = score_day(rows)
            alerts["sender_entity"] = alerts.source.map(entities)
            alerts["receiver_entity"] = alerts.target.map(entities)
            counts.update(transactions=len(rows), labelled_positive=int((rows.label == "1").sum()),
                          flagged=len(alerts), true_positive=int((alerts.label == "1").sum()))
            alerts.to_csv(alerts_file, mode="a", header=not alerts_file.exists(), index=False)
        counts["false_positive"] = counts["flagged"] - counts["true_positive"]
        counts["false_negative"] = counts["labelled_positive"] - counts["true_positive"]
        for metric, denominator in [("precision", "flagged"), ("recall", "labelled_positive")]:
            counts[metric] = counts["true_positive"] / counts[denominator] if counts[denominator] else None
        alerts_file.replace(OUTPUT / "alerts.csv")
    summary = json.dumps(dict(counts), indent=2)
    (OUTPUT / "evaluation.json").write_text(summary)
    print(summary)


if __name__ == "__main__":
    main()
