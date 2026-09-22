"""Compare the previously truncated curves with full cross-year runs."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def main() -> Path:
    root = Path("outputs/aquacrop_crossyear")
    old = pd.read_csv("outputs/aquacrop_annual/annual_scenarios.csv",
                      usecols=["Env", "parameter_set", "planting_date", "status", "yield_at_15p5_Mg_ha"])
    new = pd.read_csv(root / "annual_scenarios.csv",
                      usecols=["Env", "parameter_set", "planting_date", "status", "yield_at_15p5_Mg_ha"])
    old = old.loc[old.parameter_set.eq("optimized")]
    new = new.loc[new.parameter_set.eq("optimized")]
    plt.rcParams.update({"font.family": "Hiragino Sans GB", "axes.unicode_minus": False,
                         "axes.grid": True, "grid.alpha": .16, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, sharey=True)
    fig.subplots_adjust(left=.08, right=.98, bottom=.10, top=.86, hspace=.33, wspace=.08)
    for ax, env in zip(axes.flat, [f"{site}_{year}" for site in ["INH1", "MOH2", "NYH2"] for year in [2022, 2023]]):
        for frame, color, label in [(old, "#9A9A9A", "当年截止"), (new, "#187F85", "允许跨年")]:
            g = frame.loc[frame.Env.eq(env)].sort_values("planting_date")
            x = pd.to_datetime(g.planting_date).dt.dayofyear
            y = g.yield_at_15p5_Mg_ha.where(g.status.eq("matured"))
            ax.plot(x, y, color=color, lw=2, label=label)
        ax.set_title(env)
        ax.set_xlim(1, 365)
        ax.set_xticks([1, 60, 121, 182, 244, 305, 365])
        ax.set_xticklabels(["1月", "3月", "5月", "7月", "9月", "11月", "12月末"])
    for ax in axes[:, 0]: ax.set_ylabel("产量（t/ha，15.5%含水率）")
    for ax in axes[-1, :]: ax.set_xlabel("播种日期")
    fig.suptitle("优化参数：当年截止与允许跨年的播期响应", y=.97, fontsize=16)
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper center", ncol=2,
               bbox_to_anchor=(.5, .94), frameon=False)
    fig.text(.5, .02, "仅绘制正常成熟产量；冬季和晚播的数值结果尚未经田间多播期实测验证。",
             ha="center", color="#555555")
    path = root / "figures" / "当年截止与跨年对比.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)
    print(path)
    return path


if __name__ == "__main__":
    main()
