"""Print the source rows supporting a selected transaction alert."""
import argparse
import csv
from analyze import RAW, OUTPUT

def investigate(row_id):
    with (OUTPUT / "alerts.csv").open(newline="", encoding="utf-8") as file:
        alert = next((row for row in csv.DictReader(file) if row["source_row"] == str(row_id)), None)
    if alert is None:
        raise SystemExit("This source row has no alert.")
    print("Selected transfer:", alert["source"], "->", alert["target"], alert["time"])
    print("Source row | timestamp | payer -> payee | paid | evidence")
    with (RAW / "HI-Small_Trans.csv").open(newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        next(reader)
        for n, row in enumerate(reader, 2):
            time, bank_a, a, bank_b, b = row[:5]
            payer, payee = bank_a + "/" + a, bank_b + "/" + b
            if payer == payee or time[:10] != alert["time"][:10]:
                continue
            reasons = []
            if alert["fan_out"] == "True" and payer == alert["source"]:
                reasons.append("fan-out")
            if alert["fan_in"] == "True" and payee == alert["target"]:
                reasons.append("fan-in")
            if alert["return_transfer"] == "True" and payer == alert["target"] and payee == alert["source"] and time < alert["time"]:
                reasons.append("earlier reverse transfer")
            if n == row_id:
                reasons.append("selected")
            if reasons:
                print(n, time, payer, "->", payee, row[7], row[8], ", ".join(reasons), sep=" | ")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_row", type=int)
    investigate(parser.parse_args().source_row)
