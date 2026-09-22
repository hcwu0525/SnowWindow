from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from aquacrop_demo.model import Experiment
from aquacrop_demo.physics import planting_windows


def test_daily_windows_keep_gaps_and_abnormal_neighbors():
    d=pd.DataFrame(dict(offset_days=[0,1,2,3,4,5],planting_date=pd.date_range('2023-04-01',periods=6).strftime('%Y-%m-%d'),status=['matured']*5+['insufficient_thermal_time'],dry_yield_Mg_ha=[10,9.8,8,9.8,10,np.nan]))
    w=planting_windows(d,[.95],step_days=1)[0]
    assert w['segments']==[['2023-04-01','2023-04-02'],['2023-04-04','2023-04-05']]
    assert w['adjacent_abnormal_candidate']


def test_explicit_dates_and_year_boundaries():
    cfg=yaml.safe_load(Path('aquacrop_demo/config.yaml').read_text()); e=Experiment(cfg); u=e.units[1]
    a=e.run(u,scale=.94,hi0=.35); b=e.run(u,planting_date=u['planting_date'],scale=.94,hi0=.35)
    assert a['run_id']==b['run_id'] and a['dry_yield_Mg_ha']==b['dry_yield_Mg_ha']
    first=e.run(u,planting_date='2023-01-01',scale=.94,hi0=.35,store_daily=True)
    assert first['status'] in ['matured','crop_died','not_germinated','not_matured']
    assert first['preplant_days_simulated']==0 and first['day_before_planting_soil_water_mm'] is None
    assert first['water_balance_max_abs_mm_day']<1e-7
    last=e.run(u,planting_date='2023-12-31',scale=.94,hi0=.35)
    assert last['status']=='calendar_not_supported' and last['dry_yield_Mg_ha'] is None
