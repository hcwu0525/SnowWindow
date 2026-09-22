"""Scientific figures and auditable Chinese report for annual planting scans."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .report import plt, markdown_table
from .data import write_json, sha256_file

COLORS={'default':'#999999','first_calibration':'#d28e34','optimized':'#187f85'}

def build(cfg):
    out=Path(cfg['output_dir']); figs=out/'figures'; figs.mkdir(exist_ok=True)
    d=pd.read_csv(out/'annual_scenarios.csv'); audit=pd.read_csv(out/'input_audit.csv'); env=pd.read_csv(out/'environments.csv')
    m=pd.read_csv(out/'validation_metrics.csv'); v=pd.read_csv(out/'validation_predictions.csv')
    params=json.loads((out/'calibration_parameters.json').read_text()); p=next(x for x in params if x['name']=='heldout_year')
    # Air-temperature exposure is a screening indicator, not a soil-temperature or frost-survival model.
    for name, g in d.groupby('Env'):
        weather=pd.read_csv(out/'weather'/f'{name}.csv',parse_dates=['Date'])
        dates=pd.DatetimeIndex(weather.Date); cold=np.r_[0,np.cumsum(weather.MinTemp.to_numpy()<0)]
        indices=dates.get_indexer(pd.to_datetime(g.planting_date)); ends=np.minimum(indices+14,len(weather))
        d.loc[g.index,'first14_available_days']=ends-indices
        d.loc[g.index,'first14_air_below0_days']=cold[ends]-cold[indices]
    d.to_csv(out/'annual_scenarios.csv',index=False)
    main=d[d.parameter_set.eq('optimized')]; windows=json.loads((out/'planting_windows.json').read_text())
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.15,'savefig.dpi':160})
    fig,axes=plt.subplots(3,2,figsize=(13,10),sharex=True,constrained_layout=True)
    for ax,u in zip(axes.flat,env.to_dict('records')):
        g=d[d.Env.eq(u['Env'])]
        for name,color in COLORS.items():
            s=g[g.parameter_set.eq(name)].sort_values('planting_date'); x=pd.to_datetime(s.planting_date).dt.dayofyear
            y=s.yield_at_15p5_Mg_ha.where(s.status.eq('matured')); ax.plot(x,y,label=name,color=color,lw=1.5)
        sens=g[g.parameter_set.str.startswith('HI_sensitivity_')|g.parameter_set.eq('optimized')].copy()
        sens['mature_yield']=sens.yield_at_15p5_Mg_ha.where(sens.status.eq('matured'))
        band=sens.groupby('planting_date').mature_yield.agg(['min','max']); x=pd.to_datetime(band.index).dayofyear
        ax.fill_between(x,band['min'],band['max'],color=COLORS['optimized'],alpha=.16)
        ax.scatter([pd.Timestamp(u['planting_date']).dayofyear],[u['observed_yield_15p5_Mg_ha']],color='#a42843',marker='*',s=110,label='observed at actual planting',zorder=4)
        ax.set(title=u['Env'],xlim=(1,365),ylabel='Grain yield at 15.5% moisture (t/ha)')
    axes[0,0].legend(fontsize=8); axes[-1,0].set_xlabel('Planting day of year'); axes[-1,1].set_xlabel('Planting day of year')
    fig.savefig(figs/'annual_yield_curves.png'); plt.close(fig)
    # Comparison views; missing scenarios stay missing instead of connecting across gaps.
    fig,axes=plt.subplots(1,3,figsize=(15,4),constrained_layout=True,sharey=True)
    for ax,(site,g) in zip(axes,main.groupby('site')):
        for year,s in g.groupby('year'):
            s=s.sort_values('planting_date'); ax.plot(pd.to_datetime(s.planting_date).dt.dayofyear,s.yield_at_15p5_Mg_ha.where(s.status.eq('matured')),label=str(year))
        ax.set(title=site,xlabel='Planting day of year',xlim=(1,365)); ax.legend()
    axes[0].set_ylabel('Grain yield at 15.5% moisture (t/ha)'); fig.savefig(figs/'same_site_across_years.png'); plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,4),constrained_layout=True,sharey=True)
    for ax,(year,g) in zip(axes,main.groupby('year')):
        for site,s in g.groupby('site'):
            s=s.sort_values('planting_date'); ax.plot(pd.to_datetime(s.planting_date).dt.dayofyear,s.yield_at_15p5_Mg_ha.where(s.status.eq('matured')),label=site)
        ax.set(title=str(year),xlabel='Planting day of year',xlim=(1,365)); ax.legend()
    axes[0].set_ylabel('Grain yield at 15.5% moisture (t/ha)'); fig.savefig(figs/'same_year_across_sites.png'); plt.close(fig)
    statuses=['matured','crop_died','not_germinated','not_matured','insufficient_thermal_time','calendar_not_supported','execution_failed']
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    palette=['#328d79','#a84745','#bb8835','#e1c762','#aaaeb3','#555765','#9c46b2']
    ordered=sorted(main.Env.unique()); matrix=[]; ymatrix=[]
    for name in ordered:
        g=main[main.Env.eq(name)].sort_values('planting_date'); matrix.append([statuses.index(x) for x in g.status]); ymatrix.append(g.yield_at_15p5_Mg_ha.where(g.status.eq('matured')).to_numpy())
    fig,axes=plt.subplots(2,1,figsize=(14,6),constrained_layout=True)
    im=axes[0].imshow(ymatrix,aspect='auto',extent=[.5,365.5,5.5,-.5],cmap='viridis'); fig.colorbar(im,ax=axes[0],label='Mature grain yield (t/ha, 15.5% moisture)')
    axes[1].imshow(matrix,aspect='auto',extent=[.5,365.5,5.5,-.5],cmap=ListedColormap(palette),norm=BoundaryNorm(np.arange(-.5,len(statuses)+.5),len(statuses)))
    for ax in axes: ax.set(yticks=range(6),yticklabels=ordered,xlabel='Planting day of year'); ax.grid(False)
    axes[1].legend(handles=[Patch(color=c,label=s) for s,c in zip(statuses,palette)],loc='upper center',bbox_to_anchor=(.5,-.24),ncol=4,fontsize=8)
    fig.savefig(figs/'yield_and_feasibility_heatmap.png',bbox_inches='tight'); plt.close(fig)
    searches=pd.read_csv(out/'calibration_search.csv'); fig,axes=plt.subplots(1,2,figsize=(11,4),constrained_layout=True)
    for ax,phase,col in zip(axes,['phenology','yield'],['phenology_scale','HI0']):
        for fold,g in searches[searches.phase.str.startswith(phase)].groupby('fold'):
            g=g.sort_values(col); g=g.drop_duplicates(col); ax.plot(g[col],g.training_mae.replace([np.inf,-np.inf],np.nan),'.-',label=fold,alpha=.7)
        ax.set(xlabel=col,ylabel='Training MAE (days)' if phase=='phenology' else 'Training MAE (dry t/ha)')
    axes[1].legend(fontsize=7); fig.savefig(figs/'parameter_loss_curves.png'); plt.close(fig)
    selected=v[v.fold.eq('heldout_year') & v.validation_split.eq('test')].copy()
    fig,axes=plt.subplots(1,2,figsize=(10,4),constrained_layout=True)
    for ax,target,observed,label in zip(axes,['dry_yield_Mg_ha','flowering_proxy_DAP'],['observed_dry_yield_Mg_ha','observed_pollen_DAP'],['Dry grain yield (t/ha)','Pollen / flowering proxy (DAP)']):
        for mode,color in COLORS.items():
            g=selected[selected.parameter_set.eq(mode) & selected.status.eq('matured')]; ax.scatter(g[observed],g[target],color=color,label=mode)
        a=np.r_[selected[observed],selected[target]]; lo,hi=np.nanmin(a)*.95,np.nanmax(a)*1.05; ax.plot([lo,hi],[lo,hi],'k--',lw=.8); ax.set(xlabel='Observed '+label,ylabel='Simulated '+label)
    axes[0].legend(fontsize=8); fig.savefig(figs/'original_date_validation.png'); plt.close(fig)
    reps=pd.read_csv(out/'representative_runs.csv')
    # One representative environment, multiple planting dates; full daily tables retained for all six.
    name='INH1_2023'; fig,axes=plt.subplots(3,1,figsize=(11,8),constrained_layout=True,sharex=True)
    events=[]
    for r in reps.to_dict('records'):
        path=out/'runs'/f"{r['run_id']}.parquet"
        if not path.exists(): continue
        daily=pd.read_parquet(path); cover=daily.loc[daily.canopy_cover.gt(0) & daily.growing_season]
        onset=cover.Date.iloc[0] if len(cover) else None
        events.append(dict(**r,canopy_first_positive_date=str(pd.Timestamp(onset).date()) if onset is not None else None,days_to_positive_canopy=(pd.Timestamp(onset)-pd.Timestamp(r['date'])).days if onset is not None else None))
    pd.DataFrame(events).to_csv(out/'representative_process_events.csv',index=False)
    for r in reps[reps.Env.eq(name)].to_dict('records'):
        path=out/'runs'/f"{r['run_id']}.parquet"
        if not path.exists(): continue
        g=pd.read_parquet(path); x=pd.to_datetime(g.Date).dt.dayofyear
        for ax,col in zip(axes,['canopy_cover','soil_water_mm','biomass']): ax.plot(x,g[col]/100 if col=='biomass' else g[col],label=r['date'])
    for ax,label in zip(axes,['Canopy cover','Profile soil water (mm)','Biomass (t/ha)']): ax.set_ylabel(label)
    axes[0].legend(ncol=3,fontsize=8); axes[-1].set_xlabel('Calendar day of year'); fig.savefig(figs/'representative_daily_processes.png'); plt.close(fig)
    count=d.groupby(['parameter_set','status']).size().unstack(fill_value=0); count.to_csv(out/'status_counts.csv')
    checks={}
    checks['raw_sources_unchanged']=all(sha256_file(Path(k))==h for k,h in json.loads((out/'source_manifest.json').read_text()).items())
    checks['full_year_inputs']=bool((audit.weather_rows.eq(365)&audit.missing_dates.eq(0)&audit.duplicate_dates.eq(0)&audit.missing_weather_values.eq(0)).all())
    checks['365_unique_dates_every_group']=all(len(g)==365 and g.planting_date.nunique()==365 for _,g in d.groupby(['Env','parameter_set']))
    checks['no_technical_failure']=not d.status.eq('execution_failed').any()
    checks['unsupported_dates_have_no_yield']=bool(d.loc[d.status.isin(['insufficient_thermal_time','calendar_not_supported']),'dry_yield_Mg_ha'].isna().all())
    checks['water_balance']=bool((d.loc[d.water_balance_max_abs_mm_day.notna(),'water_balance_max_abs_mm_day']<1e-7).all())
    checks['soil_water_bounds']=bool(d.loc[d.soil_water_bounds_ok.notna(),'soil_water_bounds_ok'].all())
    checks['primary_validation_all_mature']=bool(selected[selected.parameter_set.eq('optimized')].status.eq('matured').all())
    checks['original_date_matches_scenario']=True
    for r in selected[selected.parameter_set.eq('optimized')].to_dict('records'):
        g=main[main.unit_id.eq(r['unit_id']) & main.planting_date.eq(r['planting_date'])]
        checks['original_date_matches_scenario'] &= len(g)==1 and np.isclose(g.dry_yield_Mg_ha.iloc[0],r['dry_yield_Mg_ha'],atol=1e-12)
    checks['representative_daily_files']=all((out/'runs'/f"{r['run_id']}.parquet").exists() for r in reps.to_dict('records') if r['status'] in ['matured','crop_died','not_matured','not_germinated'])
    checks = {k: bool(value) for k, value in checks.items()}
    write_json(out/'acceptance_checks.json',checks)
    # Verify every reported window date is a mature scenario of its own parameter set.
    checks['windows_only_mature_dates'] = all(all(date in set(d.loc[d.Env.eq(w['Env']) & d.parameter_set.eq(w['parameter_set']) & d.status.eq('matured'), 'planting_date']) for date in w['dates']) for w in windows)
    for par in params:
        checks['fold_ids_disjoint_' + par['name']] = not bool(set(par['train_ids']) & set(par['test_ids']))
    write_json(out/'acceptance_checks.json', checks)
    def compress_dates(values):
        segments=[]
        for value in sorted(values):
            if not segments or (pd.Timestamp(value)-pd.Timestamp(segments[-1][1])).days != 1: segments.append([value,value])
            else: segments[-1][1]=value
        return ';'.join(a if a==b else a+'至'+b for a,b in segments)
    wrows=[]
    for w in windows:
        if w['parameter_set']=='optimized': wrows.append(dict(Env=w['Env'],fraction=w['fraction'],max_dry_yield=w.get('max_dry_yield_Mg_ha'),best_dates=compress_dates(w.get('best_dates',[])),segments=';'.join('至'.join(s) for s in w['segments']),adjacent_abnormal=w.get('adjacent_abnormal_candidate')))
    wf=pd.DataFrame(wrows); wf.to_csv(out/'planting_windows.csv',index=False)
    sensitivity_rows=[]
    for (name, mode), g in d.groupby(['Env','parameter_set']):
        mature=g.loc[g.status.eq('matured')]
        best=mature.loc[mature.dry_yield_Mg_ha.idxmax()] if len(mature) else None
        sensitivity_rows.append(dict(Env=name,parameter_set=mode,n_mature=len(mature),first_mature_planting=mature.planting_date.min() if len(mature) else None,last_mature_planting=mature.planting_date.max() if len(mature) else None,best_date=best.planting_date if best is not None else None,max_dry_yield=best.dry_yield_Mg_ha if best is not None else None))
    pd.DataFrame(sensitivity_rows).to_csv(out/'window_sensitivity.csv',index=False)
    met=m[m.fold.eq('heldout_year') & m.split.eq('test')]
    cmp=selected[selected.parameter_set.eq('optimized')][['Env','observed_dry_yield_Mg_ha','dry_yield_Mg_ha']].copy(); cmp['relative_error_pct']=100*(cmp.dry_yield_Mg_ha/cmp.observed_dry_yield_Mg_ha-1)
    text=f'''# AquaCrop 率定优化与全年逐日播期结果

本实验固定六个环境（三地点×2022、2023年），全年每天一个候选播期，1月1日初始化，12月31日截止。默认、第一版率定、优化方案及HI0敏感性候选共运行{len(d):,}个情景记录。地点身份不等于固定地块，冬季播期仅用于探索模型响应，不能直接视为田间可实施方案。

## 参数与率定结果

优化参数：物候积温共同缩放系数 **{p['phenology_scale']}**，参考收获指数 **{p['HI0']}**；HI0边界状态 **{p['hi0_boundary']}**。仅使用2022年三个环境选择主参数，2023年仅评估。物候代理是累计积温达到HIstart，与实测散粉不是完全相同事件；成熟没有独立观测率定。

真实观测按选定实验和原播期，先对各杂交种的重复取均值，再对杂交种等权平均；模型代表通用品种。跨环境品种构成差异可能混入环境平均产量差异，当前不进行品种参数分解。

率定采用粗网格与局部细化、训练环境等权MAE；全部训练环境必须正常成熟。误差相同时接近默认参数优先。细化HI0候选中训练MAE不超过最优值加0.20 t/ha者用于敏感性带，属于仅HI0的条件敏感性范围，不覆盖物候、土壤、初始化或结构误差，并非置信区间。土壤、密度、根深、水分生产力和冠层参数不参与搜索。HI0达到下界时未继续降低。

{markdown_table(pd.DataFrame(params)[['name','phenology_scale','HI0','training_yield_mae','hi0_boundary']])}

![参数损失曲线](figures/parameter_loss_curves.png)

## 原播期独立年份验证

以下产量指标均为干物质t/ha；换算15.5%含水率除以0.845。2023年结果已在第一版被查看，本次属于迭代评估，不能视为全新盲测。留地点折独立率定，training_leave_site折仅在2022年内检查参数稳定性。

{markdown_table(met[['target','parameter_set','n','n_excluded','mae','rmse','bias']])}

{markdown_table(cmp)}

![原播期验证](figures/original_date_validation.png)

## 全年播期响应与可行性

曲线仅连接连续的正常成熟日期。未成熟、死亡及初始化拒绝不以零产量替代。所有播期参数固定，播种时水分由播前过程决定。晚播积温不足常被OSPy初始化拒绝，因而未必有每日模拟输出；这不能称为实测失败或模拟零产。

12月31日播种与收获截止同日，OSPy将其识别为跨年季节，记录calendar_not_supported。模型终止日期为步骤结束日期，可能比最后模拟日多一天；不表示使用次年天气。

{markdown_table(count.reset_index())}

![全年曲线](figures/annual_yield_curves.png)

![产量与可行性热图](figures/yield_and_feasibility_heatmap.png)

![同地点跨年](figures/same_site_across_years.png)

![同年跨地点](figures/same_year_across_sites.png)

## 最优播期及窗口

只在正常成熟、有效正产量候选中定义最大产量。窗口为达到该环境最大模拟产量90%／95%的日期集合；按每日相邻关系分段。邻近异常候选表示峰值可能受可行性边界限制，不能直接解释为农学最优。详见planting_windows.json的完整日期集合。

{markdown_table(wf)}

## 输入核查与过程诊断

核查发现三个地点的两年Field标识均不同，田块中心坐标也不同，不能视为同一物理田块多年。以下表中的stand/area为记录的实现株数密度，尚未确认等同于播种密度；没有自动覆盖75,000株/ha。Farm、Field和田块坐标用于排查，但尚未确认跨年物理地块身份。完整原始信息、土壤LabID、深度、管理缺失记录见input_audit.csv。

{markdown_table(audit[['Env','Farm','Field','soil_texture','field_latitude','field_longitude','observed_stand_per_ha_median','stand_area_valid_pairs']])}

初始50%可利用水、均质2m土壤、最大根深1.9m、无灌溉、无地下水与裸地播前管理仍为共同假设。模型未显式表达的养分及其他田间限制不能靠HI0率定证明已修复。保留每个环境代表日期的每日状态、土壤及作物参数，见representative_runs.csv及runs目录。

![代表日期生长过程](figures/representative_daily_processes.png)

## 验收与证据限制

{markdown_table(pd.DataFrame([dict(check=k,passed=v) for k,v in checks.items()]))}

原始数据哈希未变。天气复用第一版经核验的NASA POWER AG全年驱动。实现版本、完整配置和依赖锁定见config.yaml、../aquacrop_demo/installed_environment.json与项目requirements-aquacrop.lock.txt；代码及配置指纹见execution_manifest.json，单次运行记录另有输入和模型指纹。每次使用三个本地进程，实际耗时见timing.json（包含缓存复用，非纯引擎基准）。

全年极早播期的数值峰值尤其需要谨慎：核读安装版solution/germination.py，其萌发判断主要依据表层可利用水阈值，没有直接以最低气温判定种子冻死；其他过程包含低温影响，但不能据此证明冬季播种可行。全年峰值可能反映模型等待积温积累后的生长，而非真实冬播生存能力。annual_scenarios.csv额外记录播种日起前14天可用天气天数与最低气温低于0℃天数，仅为气温暴露筛查，不是土温、霜冻生存或农学可行性判定。

本实验不以“两边低中间高”作为成功标准，也不以训练误差降低证明播期响应可信。当前只能分别判断模型能否运行、原播期误差及迁移表现；反事实响应仍需多播期实测、成熟／冠层／水分观测进一步支持。

资料依据：安装版本源码和[OSPy官方代码](https://github.com/aquacropos/aquacrop)、[FAO56 ET0方法](https://www.fao.org/4/X0490E/x0490e06.htm)；第一版数据与模型来源细节见../aquacrop_demo/结果报告.md。
'''
    (out/'结果报告.md').write_text(text,encoding='utf-8')
    write_json(out/'execution_manifest.json',{'files':{str(x):sha256_file(x) for x in [Path('aquacrop_demo/model.py'),Path('aquacrop_demo/optimize.py'),Path('aquacrop_demo/annual_report.py'),Path('aquacrop_demo/physics.py'),out/'config.yaml']},'effective_config':cfg,'model_version':'3.1.0'})
    print('Acceptance:',checks,flush=True)
