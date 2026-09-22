"""Version-two constrained calibration and full-year daily planting experiment."""
from __future__ import annotations
import json
import shutil
import time
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from .data import write_json, sha256_file, _coordinate
from .model import Experiment
from .pipeline import run_many, choose_parameter, metrics
from .physics import planting_windows

OUT = Path('outputs/aquacrop_annual')

def prepare():
    cfg = yaml.safe_load(Path('aquacrop_demo/config.yaml').read_text())
    source = Path(cfg['output_dir']); cfg['output_dir'] = str(OUT)
    cfg['experiment_revision'] = 'annual-v2-constrained-refinement'
    OUT.mkdir(exist_ok=True)
    for name in ['environments.csv', 'selection_manifest.json', 'weather_manifest.json', 'selection_audit.csv']:
        shutil.copy2(source / name, OUT / name)
    shutil.copytree(source / 'weather', OUT / 'weather', dirs_exist_ok=True)
    (OUT / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    e = Experiment(cfg)
    src = Path(cfg['data_dir'])
    meta = pd.read_csv(src / '2_Training_Meta_Data_2014_2023.csv').fillna('')
    soil = pd.read_csv(src / '3_Training_Soil_Data_2015_2023.csv')
    traits = pd.read_csv(src / '1_Training_Trait_Data_2014_2023.csv', low_memory=False)
    rows = []
    for u in e.units:
        m = meta.loc[meta.Env.eq(u['Env'])].iloc[0]; t = traits.loc[traits.Env.eq(u['Env']) & traits.Experiment.eq(u['experiment'])].copy()
        dates = pd.to_datetime(t.Date_Planted, format='mixed', errors='coerce')
        t = t.loc[dates.eq(pd.Timestamp(u['planting_date']))]
        samples = soil.loc[soil.Env.eq(u['Env'])]
        lat, lat_source = _coordinate(m, 'Latitude'); lon, lon_source = _coordinate(m, 'Longitude')
        area = pd.to_numeric(t.Plot_Area_ha, errors='coerce'); stand = pd.to_numeric(t.Stand_Count_plants, errors='coerce')
        valid = area.gt(0) & stand.ge(0)
        w = e.weather[u['Env']]; date = pd.DatetimeIndex(w.Date); expected = pd.date_range(f"{u['year']}-01-01", f"{u['year']}-12-31")
        rows.append(dict(Env=u['Env'], site=u['site'], year=u['year'], Farm=m.Farm, Field=m.Field,
          latitude=lat, longitude=lon, coordinate_source=f'{lat_source}/{lon_source}',
          field_latitude=_coordinate(m.drop(labels=[c for c in m.index if c.startswith('Weather_Station_')]), 'Latitude')[0],
          field_longitude=_coordinate(m.drop(labels=[c for c in m.index if c.startswith('Weather_Station_')]), 'Longitude')[0],
          same_physical_field_confirmed=False, Irrigated=m.Irrigated, Previous_Crop=m.Previous_Crop,
          Treatment=m.Treatment, soil_texture=u['texture'], soil_sample_count=len(samples),
          soil_LabID=';'.join(samples.LabID.astype(str)), soil_depth_record=';'.join(samples['E Depth'].astype(str)),
          observed_stand_per_ha_median=float((stand[valid]/area[valid]).median()) if valid.any() else None,
          stand_area_valid_pairs=int(valid.sum()), model_density=cfg['plant_population_ha'],
          density_note='realized stand divided by recorded plot area; not confirmed sowing density, no automatic parameter replacement',
          management_note='irrigation explicitly no; fertilizer event schedule and initial hydraulic state unavailable',
          weather_rows=len(w), missing_dates=len(expected.difference(date)), duplicate_dates=int(date.duplicated().sum()),
          missing_weather_values=int(w[['MinTemp','MaxTemp','Precipitation','ReferenceET']].isna().sum().sum())))
    pd.DataFrame(rows).to_csv(OUT / 'input_audit.csv', index=False)
    write_json(OUT / 'source_manifest.json', {str(p): sha256_file(p) for p in src.glob('*.csv')})
    return cfg


def fit(cfg):
    e = Experiment(cfg); units = e.units
    folds = [dict(name='heldout_year', train_ids=[u['unit_id'] for u in units if u['year']==2022], test_ids=[u['unit_id'] for u in units if u['year']==2023])]
    for site in sorted({u['site'] for u in units}):
        folds.append(dict(name='leave_site_'+site, train_ids=[u['unit_id'] for u in units if u['site']!=site], test_ids=[u['unit_id'] for u in units if u['site']==site]))
        folds.append(dict(name='training_leave_site_'+site, train_ids=[u['unit_id'] for u in units if u['year']==2022 and u['site']!=site], test_ids=[u['unit_id'] for u in units if u['year']==2022 and u['site']==site]))
    logs=[]; params=[]
    coarse=np.round(np.arange(.8,1.2001,.02),6)
    result=run_many(e, [(u,dict(scale=float(v))) for v in coarse for u in units])
    for fold in folds:
        train=[u for u in units if u['unit_id'] in fold['train_ids']]
        value, losses=choose_parameter(result, train, 'phenology_scale','observed_pollen_DAP',1.)
        logs.extend(dict(**r,fold=fold['name'],phase='phenology_coarse') for r in losses)
        fine=np.round(np.arange(max(.8,value-.02),min(1.2,value+.02)+.0001,.005),6)
        refined=run_many(e, [(u,dict(scale=float(v))) for v in fine for u in train])
        value, losses=choose_parameter(refined,train,'phenology_scale','observed_pollen_DAP',1.)
        logs.extend(dict(**r,fold=fold['name'],phase='phenology_fine') for r in losses)
        hi_result=run_many(e,[(u,dict(scale=value,hi0=float(v))) for v in np.round(np.arange(.35,.5501,.01),6) for u in train])
        hi, losses=choose_parameter(hi_result,train,'HI0','observed_dry_yield_Mg_ha',e.base['HI0'])
        logs.extend(dict(**r,fold=fold['name'],phase='yield_coarse') for r in losses)
        fine_hi=np.round(np.arange(max(.35,hi-.01),min(.55,hi+.01)+.00001,.0025),6)
        refined=run_many(e,[(u,dict(scale=value,hi0=float(v))) for v in fine_hi for u in train])
        hi, losses=choose_parameter(refined,train,'HI0','observed_dry_yield_Mg_ha',e.base['HI0'])
        logs.extend(dict(**r,fold=fold['name'],phase='yield_fine') for r in losses)
        best=min(r['training_mae'] for r in losses)
        ensemble=[r['HI0'] for r in losses if r['training_mae'] <= best+.20]
        params.append(dict(**fold,phenology_scale=value,HI0=hi,hi0_boundary=hi in [.35,.55],phenology_boundary=value in [.8,1.2],sensitivity_hi0=ensemble,training_yield_mae=best))
        print('Fitted',params[-1],flush=True)
        pd.DataFrame(logs).to_csv(OUT / 'calibration_search.csv',index=False)
        write_json(OUT / 'calibration_parameters.json',params)
    return params


def validate(cfg,params):
    e=Experiment(cfg); old=json.loads(Path('outputs/aquacrop_demo/calibration_parameters.json').read_text()); rows=[]
    for p in params:
        oldp=next((x for x in old if x['name']==p['name']),None)
        modes=[('default',1.,.48),('optimized',p['phenology_scale'],p['HI0'])]
        if oldp: modes.append(('first_calibration',oldp['phenology_scale'],oldp['HI0']))
        for name,scale,hi in modes:
            results=run_many(e,[(u,dict(scale=scale,hi0=hi,store_daily=p['name']=='heldout_year')) for u in e.units if u['unit_id'] in p['train_ids']+p['test_ids']])
            for r in results:
                u=next(u for u in e.units if u['unit_id']==r['unit_id'])
                rows.append(dict(**r,fold=p['name'],parameter_set=name,validation_split='train' if u['unit_id'] in p['train_ids'] else 'test',observed_pollen_DAP=u['observed_pollen_DAP'],observed_dry_yield_Mg_ha=u['observed_dry_yield_Mg_ha']))
    d=pd.DataFrame(rows); d.to_csv(OUT/'validation_predictions.csv',index=False)
    met=[]
    for (fold,mode,split),g in d.groupby(['fold','parameter_set','validation_split']):
        met.extend(dict(**r,fold=fold,parameter_set=mode,split=split) for r in metrics(g))
    pd.DataFrame(met).to_csv(OUT/'validation_metrics.csv',index=False)


def scan(cfg,params):
    e=Experiment(cfg); p=next(p for p in params if p['name']=='heldout_year')
    modes=[('default',1.,.48),('first_calibration',.94,.35),('optimized',p['phenology_scale'],p['HI0'])]
    modes += [(f'HI_sensitivity_{hi:.4f}',p['phenology_scale'],hi) for hi in p['sensitivity_hi0'] if hi != p['HI0']]
    rows=[]; windows=[]
    for name,scale,hi in modes:
        print('Annual scan:',name,flush=True)
        tasks=[(u,dict(planting_date=str(date.date()),scale=scale,hi0=hi)) for u in e.units for date in pd.date_range(f"{u['year']}-01-01",f"{u['year']}-12-31")]
        results=run_many(e,tasks)
        rows.extend(dict(**r,parameter_set=name) for r in results)
        d=pd.DataFrame(rows); d.to_csv(OUT/'annual_scenarios.csv',index=False)
    for (env,mode),g in d.groupby(['Env','parameter_set']):
        windows.extend(dict(**r,Env=env,parameter_set=mode) for r in planting_windows(g,step_days=1))
    write_json(OUT/'planting_windows.json',windows)
    # Persist representative processes, and document what each date represents.
    reps=[]
    for u in e.units:
        g=d.loc[d.Env.eq(u['Env']) & d.parameter_set.eq('optimized')]; valid=g.loc[g.status.eq('matured')]
        dates={u['planting_date']:'observed_planting'}
        if len(valid):
            dates[valid.loc[valid.dry_yield_Mg_ha.idxmax(),'planting_date']]='maximum_yield'
            for date in [valid.planting_date.min(),valid.planting_date.max()]: dates[date]='maturity_feasibility_boundary'
        for w in windows:
            if w['Env']==u['Env'] and w['parameter_set']=='optimized' and w['fraction']==.95:
                for segment in w['segments']:
                    for date in segment: dates[date]='95pct_window_boundary'
        for date,role in dates.items():
            r=e.run(u,planting_date=date,scale=p['phenology_scale'],hi0=p['HI0'],store_daily=True)
            reps.append(dict(Env=u['Env'],date=date,role=role,run_id=r['run_id'],status=r['status']))
    pd.DataFrame(reps).to_csv(OUT/'representative_runs.csv',index=False)
    return d


def main():
    start=time.perf_counter(); cfg=prepare(); params=fit(cfg); validate(cfg,params); scan(cfg,params)
    from .annual_report import build
    build(cfg)
    write_json(OUT/'timing.json',dict(elapsed_seconds=time.perf_counter()-start,workers=cfg['workers'],includes_cache=True))

if __name__=='__main__': main()
