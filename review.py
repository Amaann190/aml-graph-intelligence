"""Generate a compact review page from the full alert export."""
from html import escape
import json
import pandas as pd
from analyze import OUTPUT

metrics = json.loads((OUTPUT / "evaluation.json").read_text())
rules = ["fan_in", "fan_out", "return_transfer"]
totals = {rule: [0, 0] for rule in rules}
examples = {}
for batch in pd.read_csv(OUTPUT / "alerts.csv", chunksize=100000):
    for rule in rules:
        hits = batch.loc[batch[rule]]
        totals[rule][0] += len(hits)
        totals[rule][1] += int(hits.label.sum())
        for label in (0, 1):
            sample = hits.loc[hits.label == label]
            if not sample.empty and (rule, label) not in examples:
                examples[rule, label] = sample.iloc[0]
page = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">
<title>AML investigation brief</title><style>body{font:16px system-ui;color:#203647;max-width:900px;margin:4% auto;padding:1rem}
td,th{padding:.55rem;text-align:left;border-bottom:1px solid #ccd9da}table{border-collapse:collapse}
h1{font-size:2.4rem}th{background:#eaf2f1}article{border-left:3px solid #408377;padding-left:1rem}</style>
<p>FINANCIAL CRIME ANALYTICS · SYNTHETIC HI-SMALL</p><h1>Daily transfer investigations</h1>"""
page += f"<p>{metrics['flagged']:,} of {metrics['transactions']:,} transfers triggered a rule. Precision was {metrics['precision']:.2%} and recall was {metrics['recall']:.2%}.</p>"
page += "<h2>Rule performance</h2><table><tr><th>Signal</th><th>Flagged</th><th>Labelled positive</th></tr>"
for rule, (hits, positives) in totals.items():
    page += f"<tr><td>{rule.replace('_',' ')}</td><td>{hits:,}</td><td>{positives:,}</td></tr>"
page += "</table><p>A transfer may trigger several rules. Counts overlap.</p><h2>Cases to investigate</h2>"
for (rule, label), row in examples.items():
    result = "Labelled laundering" if label else "False positive against synthetic label"
    page += f"<article><h3>{rule.replace('_', ' ')} · {result}</h3><p>{escape(row.source)} → {escape(row.target)} at {escape(row.time)}. Paid {row.paid:,.2f} {escape(row.payment_currency)}.</p><p>Trace supporting transfers with <code>python investigate.py {row.source_row}</code>.</p></article>"
(OUTPUT / "review.html").write_text(page, encoding="utf-8")
