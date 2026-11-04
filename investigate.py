"""Show the evidence behind one alert or one detected pattern.

    python investigate.py 4896541      # a transfer, by its line number in HI-Small_Trans.csv
    python investigate.py P12          # a cycle or scatter-gather from patterns.csv

Run analyze.py first. The synthetic label is printed so a reviewer can check the
result retrospectively; no signal uses it.
"""
import argparse

import pandas as pd

from aml.data import OUTPUT

SIGNALS = ["fan_out", "fan_in", "return_transfer", "cycle", "scatter_gather"]
COLUMNS = ["source_row", "time", "payer", "payee", "paid", "payment_currency", "format", "label"]


def load_alerts(rows=None, payer=None, day=None) -> pd.DataFrame:
    """Read alerts.csv in chunks, keeping rows that match any filter given."""
    keep = []
    for chunk in pd.read_csv(OUTPUT / "alerts.csv", chunksize=500_000, dtype={"pattern_ids": str}):
        mask = pd.Series(False, index=chunk.index)
        if rows is not None:
            mask |= chunk.source_row.isin(rows)
        if payer is not None:
            mask |= (chunk.payer == payer) & chunk.time.str.startswith(day)
        keep.append(chunk.loc[mask])
    return pd.concat(keep).fillna({"pattern_ids": ""})


def show_transfers(frame: pd.DataFrame):
    view = frame[COLUMNS].sort_values(["time", "source_row"])
    print(view.to_string(index=False, formatters={"paid": "{:,.2f}".format}))


def show_pattern(pattern_id: str):
    patterns = pd.read_csv(OUTPUT / "patterns.csv").set_index("pattern_id")
    if pattern_id not in patterns.index:
        raise SystemExit(f"No pattern {pattern_id} in patterns.csv.")
    pattern = patterns.loc[pattern_id]
    print(f"{pattern_id}: {pattern.kind.replace('_', '-')} across {pattern.accounts.count('>') + 1} accounts, "
          f"{pattern.start} to {pattern.end} ({pattern.hours} h)")
    print(f"Accounts: {pattern.accounts}")
    print(f"Entities: {pattern.entities}")
    print(f"{pattern.labelled_transfers} of {pattern.transfers} transfers carry the synthetic laundering label.\n")
    show_transfers(load_alerts(rows=[int(r) for r in pattern.source_rows.split()]))


def show_transfer(row: int):
    found = load_alerts(rows=[row])
    if found.empty:
        raise SystemExit("This source row triggered no signal.")
    alert = found.iloc[0]
    fired = [name.replace("_", "-") for name in SIGNALS if alert[name]]
    print(f"Row {row}: {alert.payer} -> {alert.payee} at {alert.time}, "
          f"{alert.paid:,.2f} {alert.payment_currency} by {alert.format}")
    print(f"Signals: {', '.join(fired)}.  Synthetic label: {alert.label}\n")
    if alert.fan_out:
        same_day = load_alerts(payer=alert.payer, day=alert.time[:10])
        print(f"Fan-out: {same_day.payee.nunique()} distinct payees from this payer that day.")
    for pattern_id in alert.pattern_ids.split():
        print()
        show_pattern(pattern_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", help="a source row number, or a pattern ID such as P12")
    target = parser.parse_args().target
    if target.upper().startswith("P"):
        show_pattern(target.upper())
    else:
        show_transfer(int(target))


if __name__ == "__main__":
    main()
