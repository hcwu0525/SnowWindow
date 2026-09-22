"""Plot full-year planting-date yield curves for the three main parameter sets."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".cache/matplotlib").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(".cache").resolve()))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


ROOT = Path("outputs/aquacrop_annual")
FIGURES = ROOT / "figures"
SCENARIOS = {
    "default": ("默认参数", "播期产量_默认参数.png"),
    "first_calibration": ("第一版率定参数", "播期产量_第一版率定.png"),
    "optimized": ("优化后参数", "播期产量_优化参数.png"),
}


def main(root: Path = ROOT, cross_year: bool = False) -> None:
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "Hiragino Sans GB",
            "axes.unicode_minus": False,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "savefig.dpi": 180,
        }
    )
    use = ["Env", "parameter_set", "planting_date", "status", "yield_at_15p5_Mg_ha"]
    data = pd.read_csv(root / "annual_scenarios.csv", usecols=use)
    units = pd.read_csv(root / "environments.csv")
    sites = ["INH1", "MOH2", "NYH2"]
    years = [2022, 2023]
    for code, (title, filename) in SCENARIOS.items():
        fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, sharey=True)
        fig.subplots_adjust(left=.08, right=.98, bottom=.10, top=.83, hspace=.34, wspace=.08)
        for row, site in enumerate(sites):
            for col, year in enumerate(years):
                env = f"{site}_{year}"
                ax = axes[row, col]
                g = data.loc[data.parameter_set.eq(code) & data.Env.eq(env)].copy()
                assert len(g) == 365 and g.planting_date.nunique() == 365
                g = g.sort_values("planting_date")
                x = pd.to_datetime(g.planting_date).dt.dayofyear.to_numpy()
                y = g.yield_at_15p5_Mg_ha.where(g.status.eq("matured")).to_numpy(dtype=float)
                color = "#237D85" if year == 2022 else "#315D9A"
                ax.plot(x, y, color=color, lw=2.0)
                unit = units.loc[units.Env.eq(env)].iloc[0]
                observed_date = pd.Timestamp(unit.planting_date)
                ax.scatter(observed_date.dayofyear, unit.observed_yield_15p5_Mg_ha,
                           marker="*", s=125, color="#BD334D", edgecolor="white", linewidth=.6, zorder=4)
                ax.axvline(observed_date.dayofyear, color="#BD334D", lw=.8, alpha=.5)
                ax.set_title(f"{env}  ·  正常成熟 {np.isfinite(y).sum()}/365 天")
                ax.set_xlim(1, 365)
                ax.set_xticks([1, 60, 121, 182, 244, 305, 365])
                ax.set_xticklabels(["1月", "3月", "5月", "7月", "9月", "11月", "12月末"])
                if col == 0:
                    ax.set_ylabel("籽粒产量（t/ha，15.5%含水率）")
                if row == 2:
                    ax.set_xlabel("候选播种日期")
        suffix = "允许跨年生长" if cross_year else "当年截止"
        fig.suptitle(f"{title}：播期与最终产量（{suffix}）", fontsize=16, fontweight="bold", y=.97)
        fig.legend(handles=[Line2D([0], [0], color="#237D85", lw=2, label="2022模拟"),
                            Line2D([0], [0], color="#315D9A", lw=2, label="2023模拟"),
                            Line2D([0], [0], marker="*", color="none", markerfacecolor="#BD334D",
                                   markeredgecolor="white", markersize=12, label="原播期实测产量")],
                   loc="upper center", ncol=3, bbox_to_anchor=(.5, .935), frameon=False)
        note = ("跨年情景最多允许生长约一年；空白表示未正常成熟或模型拒绝。冬季模拟高产不等于田间可行。"
                if cross_year else "空白日期表示未正常成熟、积温不足或日历限制；冬季模拟高产不等于田间可行。")
        fig.text(.5, .018, note,
                 ha="center", fontsize=9, color="#555555")
        path = figures / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        print(path)


if __name__ == "__main__":
    main()
