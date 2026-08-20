# FAST DOWNLOAD BUILD — first three drop-in CSVs
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

YEAR=2026
OUT=Path('savant_refresh_output')
STAMP=datetime.now(timezone.utc).isoformat()
SOURCE='BASEBALL_SAVANT_CURRENT_SEASON'

def profile(raw, schema):
    out=raw.rename(columns={
        'last_name, first_name':'player_name','year':'season','pa':'PA','strikeout':'SO',
        'k_percent':'K%','bb_percent':'BB%','whiff_percent':'Whiff%','swing_percent':'Swing%',
        'xwoba':'xwOBA','xba':'xBA','xslg':'xSLG','hard_hit_percent':'Hard-Hit%',
        'barrel_batted_rate':'Barrel%','avg_swing_speed':'average_swing_speed',
        'fast_swing_rate':'fast_swing_rate','swords':'swords',
        'squared_up_contact':'squared_up_contact','woba':'wOBA'}).copy()
    cols=['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%','xwOBA','xBA','xSLG',
          'Hard-Hit%','Barrel%','average_swing_speed','fast_swing_rate','swords','squared_up_contact','wOBA']
    for c in cols:
        if c not in out.columns: out[c]=pd.NA
    out=out[cols]
    out['source']=SOURCE; out['source_timestamp']=STAMP; out['schema_version']=schema; out['refresh_status']='CURRENT'
    return out

braw=pd.read_csv(OUT/'raw_custom_batter.csv', low_memory=False)
praw=pd.read_csv(OUT/'raw_custom_pitcher.csv', low_memory=False)
ars=pd.read_csv(OUT/'raw_pitcher_arsenal.csv', low_memory=False)
batter=profile(braw,'SAVANT_BATTER_PROFILE_SCHEMA_V1')
pitcher=profile(praw,'SAVANT_PITCHER_SCHEMA_V1')
batter.to_csv(OUT/'savant_batter_profiles.csv',index=False)
pitcher.to_csv(OUT/'savant_pitcher_stats.csv',index=False)
shutil.copyfile(OUT/'savant_batter_profiles.csv',OUT/'savant_batter_profiles.last_good.csv')
shutil.copyfile(OUT/'savant_pitcher_stats.csv',OUT/'savant_pitcher_stats.last_good.csv')
base_cols=['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%','xwOBA','xBA','xSLG',
           'Hard-Hit%','Barrel%','average_swing_speed','fast_swing_rate','swords','squared_up_contact']
base=pitcher[base_cols].copy()
r=ars.rename(columns={'last_name, first_name':'arsenal_player_name','pitches':'Pitches','put_away':'PutAway%',
                      'ba':'BA','slg':'SLG','woba':'wOBA'}).copy()
r['player_id']=pd.to_numeric(r['player_id'],errors='coerce').astype('Int64')
base['player_id']=pd.to_numeric(base['player_id'],errors='coerce').astype('Int64')
out=r.merge(base,on='player_id',how='left')
out['player_name']=out['player_name'].fillna(out.get('arsenal_player_name'))
out['season']=out['season'].fillna(YEAR)
spec=['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%','xwOBA','xBA','xSLG','Hard-Hit%',
      'Barrel%','average_swing_speed','fast_swing_rate','swords','squared_up_contact','pitch_type','pitch_name',
      'pitch_usage','Pitches','PutAway%','BA','SLG','wOBA','run_value_per_100']
for c in spec:
    if c not in out.columns: out[c]=pd.NA
out=out[spec]
out['source']=SOURCE; out['source_timestamp']=STAMP; out['schema_version']='SAVANT_ARSENAL_SCHEMA_V1'; out['refresh_status']='CURRENT'
out.to_csv(OUT/'pitch_mix_matchups.csv',index=False)
shutil.copyfile(OUT/'pitch_mix_matchups.csv',OUT/'pitch_mix_matchups.last_good.csv')
summary={'status':'SUCCESS','timestamp':STAMP,'batter_rows':len(batter),'pitcher_rows':len(pitcher),'arsenal_rows':len(out)}
(OUT/'fast_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
