"""Step 5: charts.

    ./venv/bin/python charts.py   -> charts/01_schema.png (Graphviz), 02_layers.png, 03_availability.png,
                                     04_enrollment.png, 05_outcomes.png, 06_fields.png
"""
import json
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
R = HERE / "results"
INK, DIM, GRID, BG, BLUE, ORANGE, GRAY = "#f2f2f0", "#8a8a87", "#1d1d1d", "#0b0b0b", "#3987e5", "#d95926", "#9a9a96"
COLORS = {"Public": BLUE, "Private nonprofit": GRAY, "Private for-profit": ORANGE}
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": INK,
    "axes.edgecolor": "#3a3a3a", "axes.labelcolor": DIM, "xtick.color": DIM, "ytick.color": DIM,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 1,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 11, "axes.titlesize": 13,
    "axes.titlelocation": "left", "axes.titlepad": 12,
})
DOT = shutil.which("dot") or str(Path.home() / "micromamba" / "envs" / "analyst" / "bin" / "dot")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(HERE / "charts" / name, dpi=150)
    plt.close(fig)


def schema():
    t = lambda name, color, rows: (f'  {name} [label=<<table border="1" cellborder="0" cellspacing="0" cellpadding="3" color="#3a3a3a" bgcolor="#141414">'
                                   f'<tr><td bgcolor="{color}"><b>{name}</b></td></tr>' + "".join(f'<tr><td align="left">{r}</td></tr>' for r in rows) + "</table>>];")
    fact, dim = "#4a2414", "#1f3b5c"
    lines = ['digraph G {', '  graph [bgcolor="#0b0b0b", rankdir=LR, nodesep=0.35, ranksep=0.9];',
             '  node [shape=plaintext, fontname="Helvetica", fontcolor="#f2f2f0", fontsize=12];', '  edge [color="#8a8a87", arrowhead=none];',
             t("fact_institution_year", fact, ["<i>grain: institution x year</i>", "sector, degree mix as reported that year",
                                               "enrollment, admission rate", "cost, net price, tuition",
                                               "Pell share, completion", "median debt, earnings 10 yr", "default rate"]),
             t("fact_program", fact, ["<i>grain: institution x field x credential x cohort</i>", "completers", "median debt",
                                      "earnings 1 and 4 yrs after"]),
             t("dim_institution", dim, ["unitid", "name, city, state", "latest sector, degree mix", "region, locale, HBCU"]),
             t("dim_year", dim, ["year", "academic year"]), t("dim_control", dim, ["public / nonprofit / for-profit"]),
             t("dim_field", dim, ["4-digit CIP", "field name", "family"]), t("dim_cip_family", dim, ["2-digit CIP family title"]),
             t("dim_credential", dim, ["credential level"]),
             t("agg_enrollment_cube", "#2a2a2a", ["CUBE(year, control, region)", "institutions, undergrads"]),
             "  dim_year -> fact_institution_year;", "  dim_institution -> fact_institution_year;", "  dim_institution -> fact_program;",
             "  dim_control -> dim_institution;", "  dim_control -> fact_institution_year;", "  dim_field -> fact_program;", "  dim_cip_family -> dim_field;", "  dim_credential -> fact_program;",
             "  fact_institution_year -> agg_enrollment_cube [style=dashed];", "}"]
    (HERE / "charts" / "schema.dot").write_text("\n".join(lines) + "\n")
    subprocess.run([DOT, "-Tpng", "-Gdpi=130", str(HERE / "charts" / "schema.dot"), "-o", str(HERE / "charts" / "01_schema.png")], check=True)


def main():
    (HERE / "charts").mkdir(exist_ok=True)
    schema()

    s, b = json.loads((R / "lake_sizes.json").read_text()), json.loads((R / "benchmark.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    vals = [s["bronze_institution_csv_mb"], s["same_27_columns_as_csv_mb"], s["silver_institution_parquet_mb"]]
    axes[0].barh(["raw CSV, 3,308 columns", "27 columns, CSV", "27 columns, Parquet"], vals, color=[GRAY, GRAY, BLUE], height=0.55)
    for i, v in enumerate(vals):
        axes[0].text(v * 1.2, i, f"{v:,.1f} MB" if v < 100 else f"{v:,.0f} MB", va="center", color=INK, fontsize=9)
    axes[0].set_xscale("log"); axes[0].set_xlim(5, 30000); axes[0].invert_yaxis(); axes[0].grid(axis="y", visible=False)
    axes[0].set_title("30 years of institution files, on disk", fontsize=12)
    tv = [b["raw_csv_seconds"], b["silver_parquet_seconds"], b["gold_table_seconds"]]
    axes[1].barh(["raw CSV", "silver Parquet", "gold table"], tv, color=[GRAY, BLUE, BLUE], height=0.55)
    for i, v in enumerate(tv):
        axes[1].text(v * 1.3, i, f"{v:g} s", va="center", color=INK, fontsize=9)
    axes[1].set_xscale("log"); axes[1].set_xlim(0.0008, 300); axes[1].invert_yaxis(); axes[1].grid(axis="y", visible=False)
    axes[1].set_title("Enrollment by sector, all years: query time", fontsize=12)
    fig.suptitle("Bronze to silver to gold: keep the columns you need, store them as Parquet (log scales)", x=0.01, ha="left", fontsize=13, color=INK)
    save(fig, "02_layers.png")

    a = pd.read_csv(R / "measure_availability.csv").set_index("year")
    cols = ["enrollment", "tuition", "net_price", "debt", "earnings_10yr", "completion"]
    share = a[cols].div(a["institutions"], axis=0)
    fig, ax = plt.subplots(figsize=(11, 3.4))
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#262626")                                      # measure absent from that year's file
    ax.imshow(np.ma.masked_equal(share.T.values, 0), aspect="auto", cmap=cmap, vmin=0, vmax=1)
    ax.set_yticks(range(len(cols)), ["enrollment", "tuition", "net price", "median debt", "earnings 10 yrs", "completion"])
    ax.set_xticks(range(len(share)), [str(y) if y % 5 == 0 else "" for y in share.index])
    ax.grid(False)
    ax.set_title("Which measures each annual file carries (blue shade = share of institutions with a value; gray = none)")
    save(fig, "03_availability.png")

    e = pd.read_csv(R / "enrollment_by_control.csv")             # 2000 stays NaN, so the lines break there
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for ctl, g in e.groupby("control"):
        ax.plot(g["year"], g["undergrads"] / 1e6, color=COLORS[ctl], linewidth=2, marker="o", markersize=3, label=ctl)
    fp = e[e["control"] == "Private for-profit"].set_index("year")["undergrads"]
    peak = fp.idxmax()
    latest = pd.read_csv(R / "sector_attribution.csv").set_index("year")["for_profit_by_latest_sector"]
    ax.plot(latest.index, latest / 1e6, color=ORANGE, linewidth=1.5, linestyle="--", label="For-profit, filed under today's sector")
    ax.annotate(f"for-profit peak {fp[peak] / 1e6:.2f}M ({peak})", (peak, fp[peak] / 1e6), xytext=(peak + 2, 0.3), color=INK, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=DIM))
    ax.set_ylabel("undergraduates (millions)")
    ax.legend(frameon=False, labelcolor=INK, loc="center right", fontsize=10)
    ax.grid(axis="x", visible=False)
    ax.set_title("The for-profit boom and bust: undergraduate enrollment by sector (2000 and 2025 files lack enrollment)")
    save(fig, "04_enrollment.png")

    o = pd.read_csv(R / "outcomes_by_control_2020.csv").set_index("control").loc[["Public", "Private nonprofit", "Private for-profit"]]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    metrics = [("median_net_price", "net price per year"), ("median_debt", "median debt at graduation"), ("median_earnings_10yr", "median earnings 10 yrs after entry")]
    x = np.arange(len(metrics))
    for k, (ctl, row) in enumerate(o.iterrows()):
        vals = [row[m] for m, _ in metrics]
        ax.bar(x + (k - 1) * 0.26, vals, width=0.26, color=COLORS[ctl], label=ctl)
        for xi, v in zip(x + (k - 1) * 0.26, vals):
            ax.text(xi, v + 600, f"${v / 1000:.0f}k", ha="center", color=INK, fontsize=8)
    ax.set_xticks(x, [m[1] for m in metrics])
    ax.yaxis.set_major_formatter(lambda v, _: f"${v / 1000:.0f}k")
    ax.legend(frameon=False, labelcolor=INK, loc="upper left")
    ax.grid(axis="x", visible=False)
    ax.set_title("Predominantly bachelor's colleges, 2020-21 file: for-profits cost more and pay off less")
    save(fig, "05_outcomes.png")

    f = pd.read_csv(R / "bachelors_by_field.csv", dtype={"family": str})
    pick = pd.concat([f.head(6), f.tail(6)]).iloc[::-1]
    short = {"11": "Computer and information sciences", "15": "Engineering technologies", "19": "Family and consumer sciences",
             "23": "English language and literature", "24": "Liberal arts and general studies"}
    names = pick["family"].map(short).fillna(pick["family_title"].str.capitalize().str.replace(" and related.*", "", regex=True))
    fig, ax = plt.subplots(figsize=(10, 5.0))
    ax.barh(names, pick["earnings_4yr"] / 1000, color=BLUE, height=0.6, label="median earnings 4 yrs after graduating")
    ax.scatter(pick["debt"] / 1000, names, color=ORANGE, s=40, zorder=3, label="median debt")
    for i, (e4, r) in enumerate(zip(pick["earnings_4yr"], pick["debt_to_earnings"])):
        ax.text(e4 / 1000 + 1, i, f"${e4 / 1000:.0f}k · debt {r:.2f}x", va="center", color=INK, fontsize=8.5)
    ax.axhline(5.5, color=DIM, linewidth=1, linestyle="--")
    ax.set_xlim(0, pick["earnings_4yr"].max() / 1000 * 1.35)
    ax.set_xlabel("thousands of dollars; bachelor's programs, 2018-20 completers")
    ax.legend(frameon=False, labelcolor=INK, loc="lower right", fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_title("Fields of study: similar debt, very different pay (top and bottom six)")
    save(fig, "06_fields.png")
    print("charts written")


if __name__ == "__main__":
    main()
