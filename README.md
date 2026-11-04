# AML Graph Intelligence

Investigate transaction patterns in the synthetic HI-Small account and transfer files. Each node is a bank ID and account number. Each directed edge retains the original CSV row number, timestamp, payment format, amounts and currencies. Account metadata supplies entity names where available.

## Run locally

Place HI-Small_accounts.csv and HI-Small_Trans.csv in data/raw. From the project directory run:

    python -m pip install -r requirements.txt
    python analyze.py
    python -m unittest -v

The pipeline partitions transfers by calendar day on disk so a day can be scored even when it spans input batches. Allow temporary disk space for the partitions and final alert export.

## Investigate a case

Open data/processed/evaluation.json for full-run metrics. Read the first few rows of data/processed/alerts.csv to choose a source_row, then run `python investigate.py ROW_NUMBER` with that number. The command prints the selected payment and the original transfer rows supporting each triggered rule. The export has one row per flagged transfer even when several rules trigger.

## Rule definitions and evaluation

- Fan-out flags outgoing transfers from an account that paid at least 10 distinct other accounts that calendar day. Fan-in uses the same threshold for distinct payers to a recipient.
- A return transfer closes a two-account cycle when a reverse payment has a strictly earlier timestamp that day. Equal timestamps have ambiguous order. Longer cycles and cross-midnight patterns fall outside these rules.
- Self-transfers are excluded from graph signals. All input transactions, including self-transfers, count toward the evaluation denominator. Amounts stay in their original currencies.
- The rules use end-of-day information. Labels are used only for evaluation. Precision is the share of flagged transfers carrying the synthetic laundering label. Recall is the share of all labelled transfers flagged.
- Legitimate high-volume merchants and reciprocal payments can satisfy these rules. Conversely, laundering through a longer chain can evade them. A flag is a reason to inspect a transfer. These retrospective synthetic results do not establish performance on a real bank ledger.

Run **python review.py** after analysis and open **data/processed/review.html** for rule-level counts and examples of both labelled laundering and false positives.

## Analyst queue

After analysis run `python rank_cases.py`. Open data/processed/ranked_cases.csv and inspect example_row with investigate.py. A case is a payer account and calendar day. The queue ranks maximum simultaneous signals first, then total signal hits and transfer count. Labels are added after ranking. A case is positive if any outgoing transfer that day carries the synthetic label.

The retrospective queue for September 8-18 starts after the first whole days covering 65% of transfers. Of 20,012 candidate cases, the first 100 contain 33 labelled cases, or 2.00% of the 1,651 positive payer-days in that period. Across the full candidate queue recall is 8.00%. As a sensitivity check, the last third of calendar dates alone (September 13-18) contains 163 labelled cases and zero candidates. Performance depends heavily on the period. This ranks a pooled end-of-period backlog and does not simulate a daily live review budget.

## Worked investigation — case 5 of 20,012

On September 10, 2022, payer `070/100428A08` sent 340 flagged transfers to 178 distinct other accounts. Every one triggered the daily fan-out rule, which requires at least 10 recipients. Two also went to a recipient that received money from 11 distinct other payers that day, triggering fan-in. The queue ranked this payer-day fifth. Its highest overlap was two rules on one transfer, followed by 342 total rule hits across 340 flagged transfers. The ranking used no laundering labels.

Four transfers from this payer illustrate what the reviewer would see. Row numbers refer to the original HI-Small transaction CSV, counting the header as row 1. All amounts below are in Saudi riyals.

| Source row | Time | Recipient bank/account | Paid | Rules triggered | Synthetic laundering label |
|---:|---|---|---:|---|---:|
| 4,887,784 | 00:26 | `0119/811C56E80` | 1,110,391.30 | Fan-out | 0 |
| 4,896,541 | 01:08 | `0118/811DD6C70` | 547.26 | Fan-out and fan-in | 0 |
| 4,896,542 | 01:29 | `0118/811DD6C70` | 246.51 | Fan-out and fan-in | 0 |
| 5,010,013 | 15:20 | `0248857/811D5F740` | 457.64 | Fan-out | 1 |

**Review finding.** The two payments 21 minutes apart explain the rule overlap that lifted the case in the queue. Both carry label 0. The 457.64-riyal payment later that day was the payer’s only outgoing transfer labelled 1, which makes the payer-day positive under the evaluation definition. The rules surfaced the right account for review, but their strongest signal pointed to a different recipient. The largest payment shown also carried label 0.

**Reproduce the trace.** After running the analysis, use `python investigate.py 4896541` to inspect the overlapping signals and `python investigate.py 5010013` to inspect the labelled transfer. In `data/processed/ranked_cases.csv`, find the row for this payer and date to verify its queue position.
