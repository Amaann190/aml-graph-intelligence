"""Draw the README figures from the files analyze.py writes. Output: docs/images/*.png"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

from aml.data import OUTPUT, ROOT
from investigate import load_alerts

IMAGES = ROOT / "docs" / "images"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
DAILY, GRAPH = "#2a78d6", "#eb6834"          # categorical slots 1 and 2

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 11, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titlesize": 14, "axes.titleweight": "bold", "axes.titlelocation": "left",
})

CURRENCY = {"US Dollar": "USD", "Euro": "EUR", "Saudi Riyal": "SAR", "Yuan": "CNY", "Rupee": "INR",
            "Yen": "JPY", "UK Pound": "GBP", "Ruble": "RUB", "Canadian Dollar": "CAD",
            "Australian Dollar": "AUD", "Swiss Franc": "CHF", "Mexican Peso": "MXN",
            "Brazil Real": "BRL", "Shekel": "ILS", "Bitcoin": "BTC"}

NAMES = {
    "fan_out": ("Fan-out", DAILY), "fan_in": ("Fan-in", DAILY), "return_transfer": ("Return transfer", DAILY),
    "cycle": ("Temporal cycle", GRAPH), "scatter_gather": ("Scatter-gather", GRAPH),
}


def save(figure, name):
    IMAGES.mkdir(parents=True, exist_ok=True)
    figure.savefig(IMAGES / name, dpi=160, bbox_inches="tight")
    plt.close(figure)


def signal_precision(evaluation):
    signals = evaluation["signals"]
    base = evaluation["base_rate"]
    order = list(NAMES)[::-1]
    figure, axis = plt.subplots(figsize=(9, 4.2))
    values = [signals[s]["precision"] * 100 for s in order]
    axis.barh([NAMES[s][0] for s in order], values, color=[NAMES[s][1] for s in order], height=0.55)
    axis.set_xscale("log")
    axis.axvline(base * 100, color=MUTED, linestyle="--", linewidth=1.2)
    axis.text(base * 100 * 1.08, -0.55, f"base rate {base:.2%}", color=MUTED, fontsize=10, va="center")
    for y, s in enumerate(order):
        result = signals[s]
        axis.text(values[y] * 1.12, y, f"{result['precision']:.1%}  ({result['flagged']:,} flagged, "
                  f"{result['lift']:,.0f}x)", va="center", fontsize=10, color=INK)
    axis.set_xlim(base * 100 * 0.6, 1000)
    axis.set_xlabel("Share of flagged transfers that are labelled laundering (%, log scale)")
    axis.grid(axis="y", visible=False)
    axis.set_title("Graph patterns are hundreds of times more precise than daily rules")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (DAILY, GRAPH)]
    axis.legend(handles, ["Daily rule", "Graph pattern"], loc="upper right", frameon=False)
    save(figure, "signal_precision.png")


def queue_precision(cases):
    figure, axis = plt.subplots(figsize=(9, 4.2))
    results = cases["all_days"]
    for key, label, colour in [("graph_ranking", "Graph patterns first", GRAPH),
                               ("daily_rules_ranking", "Daily rules only", DAILY)]:
        depths = sorted(int(k.split("_")[-1]) for k in results[key] if k.startswith("precision_at_"))
        values = [results[key][f"precision_at_{d}"] * 100 for d in depths]
        axis.plot(depths, values, color=colour, linewidth=2, marker="o", markersize=6, label=label)
        offset = (10, 10) if colour == GRAPH else (10, -16)
        axis.annotate(f"{values[2]:.0f}% at 100", (depths[2], values[2]), textcoords="offset points",
                      xytext=offset, color=INK, fontsize=10)
    axis.set_xscale("log")
    axis.set_xticks(depths, [str(d) for d in depths])
    axis.minorticks_off()
    axis.set_ylim(0, 105)
    axis.set_xlabel("Cases reviewed, top of the queue")
    axis.set_ylabel("Cases that are labelled laundering (%)")
    axis.set_title("Review queue precision: payer-days, ranked without labels")
    axis.legend(frameon=False, loc="center right")
    save(figure, "queue_precision.png")


def daily_volume(evaluation):
    days = pd.DataFrame(evaluation["days"]).T
    days.index = pd.to_datetime(days.index).strftime("%b %d")
    figure, (top, bottom) = plt.subplots(2, 1, figsize=(10, 5.4), sharex=True,
                                         gridspec_kw={"height_ratios": [1, 1], "hspace": 0.25})
    top.bar(days.index, days.transfers, color=DAILY, width=0.7)
    top.set_yscale("log")
    top.set_ylabel("Transfers (log)")
    top.set_title("After Sep 10 only the tails of laundering chains remain")
    share = days.labelled / days.transfers * 100
    bottom.bar(days.index, share, color=GRAPH, width=0.7)
    bottom.set_ylabel("Labelled (%)")
    for x, value in zip(days.index, share):
        if value > 5:
            bottom.text(x, value + 2, f"{value:.0f}%", ha="center", fontsize=9, color=INK)
    normal = share.iloc[:10].mean()
    bottom.text(4.5, 8, f"Sep 1-10: {normal:.2f}% labelled", ha="center", color=MUTED, fontsize=10)
    bottom.set_ylim(0, 85)
    bottom.tick_params(axis="x", rotation=45)
    for axis in (top, bottom):
        axis.grid(axis="x", visible=False)
    save(figure, "daily_volume.png")


def pick(patterns, kind, sizes):
    chosen = patterns.loc[(patterns.kind == kind) & (patterns.labelled_transfers == patterns.transfers)]
    chosen = chosen.loc[chosen.accounts.str.count(">").add(1).between(*sizes)]
    return chosen.sort_values(["transfers", "start"]).iloc[len(chosen) // 2]


def draw_pattern(pattern, filename, title):
    rows = load_alerts(rows=[int(r) for r in pattern.source_rows.split()]).sort_values("time")
    accounts = pattern.accounts.split(" > ")
    short = {a: a.split("/")[1][:6] + "…" for a in accounts}
    graph = nx.DiGraph()
    for row in rows.itertuples():
        stamp = pd.Timestamp(row.time).strftime("%b %d %H:%M")
        label = f"{stamp}\n{row.paid:,.0f} {CURRENCY.get(row.payment_currency, row.payment_currency)}"
        if graph.has_edge(row.payer, row.payee):
            label = graph.edges[row.payer, row.payee]["label"] + "\n" + label
        graph.add_edge(row.payer, row.payee, label=label)
    if pattern.kind == "cycle":
        layout = nx.circular_layout(accounts)
    else:
        middles = accounts[1:-1]
        layout = {accounts[0]: (0, 0), accounts[-1]: (2, 0)}
        layout |= {m: (1, (len(middles) - 1) / 2 - i) for i, m in enumerate(middles)}
    figure, axis = plt.subplots(figsize=(9, 6))
    axis.axis("off")
    nx.draw_networkx_nodes(graph, layout, node_size=2400, node_color=SURFACE, edgecolors=GRAPH,
                           linewidths=2, ax=axis)
    nx.draw_networkx_labels(graph, layout, labels=short, font_size=9, font_color=INK, ax=axis)
    nx.draw_networkx_edges(graph, layout, edge_color=MUTED, width=1.6, arrowsize=18,
                           node_size=2400, connectionstyle="arc3,rad=0.08", ax=axis)
    nx.draw_networkx_edge_labels(graph, layout, edge_labels=nx.get_edge_attributes(graph, "label"),
                                 font_size=8, font_color=INK, bbox={"color": SURFACE, "pad": 0.4},
                                 ax=axis)
    axis.set_title(title, loc="left")
    axis.text(0, -0.02, f"{pattern.pattern_id} · {pattern.start} to {pattern.end} · "
              f"{pattern.labelled_transfers} of {pattern.transfers} transfers labelled laundering",
              transform=axis.transAxes, color=MUTED, fontsize=9)
    axis.margins(0.12)
    save(figure, filename)
    return pattern.pattern_id


def main():
    evaluation = json.loads((OUTPUT / "evaluation.json").read_text())
    cases = json.loads((OUTPUT / "case_evaluation.json").read_text())
    patterns = pd.read_csv(OUTPUT / "patterns.csv")
    signal_precision(evaluation)
    queue_precision(cases)
    daily_volume(evaluation)
    cycle = draw_pattern(pick(patterns, "cycle", (4, 5)), "example_cycle.png",
                         "A temporal cycle: money returns to where it started")
    gather = draw_pattern(pick(patterns, "scatter_gather", (5, 7)), "example_scatter_gather.png",
                          "A scatter-gather: split across intermediaries, then recombined")
    print("examples:", cycle, gather)


if __name__ == "__main__":
    main()
