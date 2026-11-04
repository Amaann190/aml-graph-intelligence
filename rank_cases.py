"""Prioritize end-of-day payer cases and evaluate the queue on the latest dates."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data/processed"

def rank_cases():
    groups = []
    for rows in pd.read_csv(OUT / "alerts.csv", chunksize=100000):
        rows["day"] = rows.time.str[:10]
        rows["signals"] = rows[["fan_in","fan_out","return_transfer"]].sum(axis=1)
        groups.append(rows.groupby(["day","source"]).agg(
            transfers=("source_row","size"), signal_count=("signals","sum"),
            max_overlap=("signals","max"), example_row=("source_row","min")))
    cases = pd.concat(groups).groupby(level=[0,1]).agg(
        {"transfers":"sum","signal_count":"sum","max_overlap":"max","example_row":"min"}).reset_index()
    return cases.sort_values(["max_overlap","signal_count","transfers","day","source"],
                            ascending=[False,False,False,True,True])

def main():
    cases = rank_cases()
    from collections import Counter
    dates, positives = Counter(), set()
    for raw in pd.read_csv(ROOT / "data/raw/HI-Small_Trans.csv", dtype=str, chunksize=200000,
                           usecols=[0,1,2,10]):
        raw.columns = ["time","bank","account","label"]
        day = raw.time.str[:10]
        dates.update(day.value_counts().to_dict())
        hit = raw.label.eq("1")
        positives.update(zip(day[hit], raw.loc[hit,"bank"] + "/" + raw.loc[hit,"account"]))
    cumulative = 0
    held = []
    for day in sorted(dates):
        if cumulative >= sum(dates.values()) * 0.65:
            held.append(day)
        cumulative += dates[day]
    queue = cases[cases.day.isin(held)].copy()
    queue["labelled_case"] = [(d,s) in positives for d,s in zip(queue.day,queue.source)]
    total = sum(day in held for day,_ in positives)
    first = queue.head(100)
    found = int(first.labelled_case.sum())
    metrics = dict(first_day=held[0], last_day=held[-1], candidate_cases=len(queue),
                   labelled_cases=total, reviewed=len(first), found=found,
                   precision_at_100=found/len(first) if len(first) else None,
                   recall_at_100=found/total if total else None,
                   candidate_recall=int(queue.labelled_case.sum())/total if total else None)
    queue.to_csv(OUT / "ranked_cases.csv",index=False)
    (OUT / "case_evaluation.json").write_text(json.dumps(metrics,indent=2))
    print(metrics)

if __name__ == "__main__":
    main()
