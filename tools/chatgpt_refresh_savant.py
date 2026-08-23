#!/usr/bin/env python3
from __future__ import annotations
import hashlib, io, json, math, shutil, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

SEASON=2026
OUT=Path('savant_refresh_output')
OUT.mkdir(parents=True, exist_ok=True)
SOURCE='BASEBALL_SAVANT_CURRENT_SEASON'
CUSTOM='https://baseballsavant.mlb.com/leaderboard/custom'
SEARCH='https://baseballsavant.mlb.com/statcast_search/csv'
ARSENAL='https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats'
HEAD={'User-Agent':'Mozilla/5.0 OneWayPickz Savant Refresh','Accept':'text/csv,text/plain,*/*','Referer':'https://baseballsavant.mlb.com/'}

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def n(v):
    try:
        x=float(str(v).replace('%','').replace(',','').strip()); return x if math.isfinite(x) else None
    except: return None
def p(v):
    x=n(v); return None if x is None else (x*100 if abs(x)<=1 else x)
def norm(c): return str(c).lower().strip().replace('%','percent').replace(' ','_').replace('-','_').replace('.','').replace('/','_')
def cmap(df): return {norm(c):c for c in df.columns}
def col(df,*names):
    m=cmap(df)
    for x in names:
        if norm(x) in m:return m[norm(x)]
    return None
def ser(df,*names,default=None):
    c=col(df,*names); return df[c] if c else pd.Series([default]*len(df),index=df.index)
def csv(url,params=None,retries=4):
    err=None
    for i in range(retries):
        try:
            r=requests.get(url,params=params,headers=HEAD,timeout=90); r.raise_for_status(); t=r.text.strip()
            if not t or '<html' in t[:500].lower(): raise RuntimeError('HTML/empty response')
            d=pd.read_csv(io.StringIO(t),low_memory=False)
            if d.empty: raise RuntimeError('empty CSV')
            return d
        except Exception as e:
            err=e; time.sleep(2*(i+1))
    raise RuntimeError(f'CSV pull failed {url}: {err}')

def custom(kind):
    selections='pa,k_percent,bb_percent,woba,xwoba,xba,xslg,barrel_batted_rate,hard_hit_percent,avg_best_speed,whiff_percent,swing_percent'
    frames=[]
    for mf in ('q','0'):
        u=f'{CUSTOM}?year={SEASON}&type={kind}&filter=&min={mf}&selections={requests.utils.quote(selections,safe="")}&chart=false&x=pa&y=pa&r=no&chartType=beeswarm&sort=xwoba&sortDir=asc&csv=true'
        try:
            d=csv(u); d['_min']=mf; frames.append(d)
        except Exception as e: print('custom fallback',kind,mf,e)
    if not frames: raise RuntimeError(f'No custom leaderboard for {kind}')
    d=pd.concat(frames,ignore_index=True,sort=False)
    idc=col(d,'player_id','entity_id','mlb_id','batter','pitcher')
    nc=col(d,'player_name','last_name, first_name','name')
    if not idc or not nc: raise RuntimeError(f'custom columns missing: {d.columns.tolist()}')
    d['_id']=pd.to_numeric(d[idc],errors='coerce'); d['_name']=d[nc].astype(str).str.strip()
    d=d[d['_id'].notna()].sort_values('_min').drop_duplicates('_id',keep='first')
    return d

def profile(kind,schema):
    d=custom(kind); ts=now()
    pa=pd.to_numeric(ser(d,'pa'),errors='coerce'); kp=ser(d,'k_percent','k%').map(p)
    so=(pa*pd.to_numeric(kp,errors='coerce')/100).round()
    out=pd.DataFrame({
      'player_id':d['_id'].astype(int),'player_name':d['_name'],'season':SEASON,'PA':pa,'SO':so,'K%':kp,
      'BB%':ser(d,'bb_percent','bb%').map(p),'Whiff%':ser(d,'whiff_percent','whiff%').map(p),'Swing%':ser(d,'swing_percent','swing%').map(p),
      'xwOBA':pd.to_numeric(ser(d,'xwoba'),errors='coerce'),'xBA':pd.to_numeric(ser(d,'xba'),errors='coerce'),'xSLG':pd.to_numeric(ser(d,'xslg'),errors='coerce'),
      'Hard-Hit%':ser(d,'hard_hit_percent','hardhit_percent').map(p),'Barrel%':ser(d,'barrel_batted_rate','barrel_percent').map(p),
      'average_swing_speed':pd.to_numeric(ser(d,'avg_best_speed','bat_speed','average_swing_speed'),errors='coerce'),
      'fast_swing_rate':pd.NA,'swords':pd.NA,'squared_up_contact':pd.NA,'wOBA':pd.to_numeric(ser(d,'woba'),errors='coerce'),
      'source':SOURCE,'source_timestamp':ts,'schema_version':schema,'refresh_status':'CURRENT'})
    return out.drop_duplicates('player_id').reset_index(drop=True)

def search_summary(hand):
    params={'all':'true','type':'details','hfGT':'R|','hfSea':f'{SEASON}|','player_type':'batter','pitcher_throws':hand,'group_by':'name','min_pitches':0,'min_results':0,'min_pas':0,'sort_col':'pitches','sort_order':'desc','chk_stats_pa':'on','chk_stats_so':'on','chk_stats_strikeouts':'on','chk_stats_k_percent':'on'}
    return csv(SEARCH,params)
def side(hand,prefix):
    d=search_summary(hand); idc=col(d,'player_id','entity_id','mlbam_id','batter'); nc=col(d,'player_name','last_name, first_name','name'); pac=col(d,'pa'); soc=col(d,'so','strikeouts'); kpc=col(d,'k_percent','k%')
    if not idc or not nc or not pac: raise RuntimeError(f'platoon columns missing: {d.columns.tolist()}')
    pa=pd.to_numeric(d[pac],errors='coerce'); kp=d[kpc].map(p) if kpc else pd.Series([None]*len(d)); so=pd.to_numeric(d[soc],errors='coerce') if soc else (pa*pd.to_numeric(kp,errors='coerce')/100).round()
    x=pd.DataFrame({'mlbam_id':pd.to_numeric(d[idc],errors='coerce'),'player_name':d[nc].astype(str).str.strip(),f'{prefix}_pa':pa,f'{prefix}_so':so})
    x=x[x.mlbam_id.notna()].copy(); x.mlbam_id=x.mlbam_id.astype(int); return x.drop_duplicates('mlbam_id')
def platoon():
    r=side('R','vs_rhp'); l=side('L','vs_lhp'); o=r.merge(l,on='mlbam_id',how='outer',suffixes=('_r','_l'))
    o['player_name']=o.player_name_r.where(o.player_name_r.notna(),o.player_name_l)
    for c in ['vs_rhp_pa','vs_rhp_so','vs_lhp_pa','vs_lhp_so']: o[c]=pd.to_numeric(o[c],errors='coerce').fillna(0)
    o['vs_rhp_k_pct']=o.vs_rhp_so/o.vs_rhp_pa.replace(0,pd.NA)*100; o['vs_lhp_k_pct']=o.vs_lhp_so/o.vs_lhp_pa.replace(0,pd.NA)*100
    o['overall_pa']=o.vs_rhp_pa+o.vs_lhp_pa; o['overall_so']=o.vs_rhp_so+o.vs_lhp_so; o['overall_k_pct']=o.overall_so/o.overall_pa.replace(0,pd.NA)*100
    o['team']=pd.NA;o['season']=SEASON;o['source']=SOURCE;o['source_timestamp']=now();o['refresh_status']='CURRENT'
    return o[['mlbam_id','player_name','team','season','vs_rhp_pa','vs_rhp_so','vs_rhp_k_pct','vs_lhp_pa','vs_lhp_so','vs_lhp_k_pct','overall_pa','overall_so','overall_k_pct','source','source_timestamp','refresh_status']]

def pitchmix():
    # Savant pitch arsenal page, one row per pitcher/pitch. If this endpoint is unavailable, fail safely rather than fabricate.
    d=csv(ARSENAL,{'type':'pitcher','pitchType':'','year':SEASON,'team':'','min':1,'csv':'true'})
    ts=now(); idc=col(d,'player_id','entity_id','pitcher'); nc=col(d,'player_name','last_name, first_name','name'); pc=col(d,'pitch_type')
    if not idc or not nc or not pc: raise RuntimeError(f'arsenal columns missing: {d.columns.tolist()}')
    out=pd.DataFrame({
      'player_id':pd.to_numeric(d[idc],errors='coerce'),'player_name':d[nc].astype(str).str.strip(),'season':SEASON,
      'PA':pd.to_numeric(ser(d,'pa'),errors='coerce'),'SO':pd.to_numeric(ser(d,'so','strikeouts'),errors='coerce'),'K%':ser(d,'k_percent','k%').map(p),'BB%':ser(d,'bb_percent','bb%').map(p),
      'Whiff%':ser(d,'whiff_percent','whiff%').map(p),'Swing%':ser(d,'swing_percent','swing%').map(p),'xwOBA':pd.to_numeric(ser(d,'xwoba'),errors='coerce'),'xBA':pd.to_numeric(ser(d,'xba'),errors='coerce'),'xSLG':pd.to_numeric(ser(d,'xslg'),errors='coerce'),
      'Hard-Hit%':ser(d,'hard_hit_percent','hardhit_percent').map(p),'Barrel%':ser(d,'barrel_batted_rate','barrel_percent').map(p),'average_swing_speed':pd.to_numeric(ser(d,'avg_best_speed','bat_speed'),errors='coerce'),'fast_swing_rate':pd.NA,'swords':pd.NA,'squared_up_contact':pd.NA,
      'pitch_type':d[pc].astype(str),'pitch_name':ser(d,'pitch_name'),'pitch_usage':ser(d,'pitch_usage','pitch_percent').map(p),'Pitches':pd.to_numeric(ser(d,'pitches'),errors='coerce'),'PutAway%':ser(d,'put_away','put_away_percent').map(p),'BA':pd.to_numeric(ser(d,'ba'),errors='coerce'),'SLG':pd.to_numeric(ser(d,'slg'),errors='coerce'),'wOBA':pd.to_numeric(ser(d,'woba'),errors='coerce'),'run_value_per_100':pd.to_numeric(ser(d,'run_value_per_100'),errors='coerce'),
      'source':SOURCE,'source_timestamp':ts,'schema_version':'SAVANT_ARSENAL_SCHEMA_V1','refresh_status':'CURRENT'})
    out=out[out.player_id.notna() & out.pitch_type.ne('')].copy();out.player_id=out.player_id.astype(int)
    # Backfill season-level pitcher metrics onto pitch rows when arsenal endpoint omits them.
    prof=profile('pitcher','SAVANT_PITCHER_SCHEMA_V1').set_index('player_id')
    for c in ['PA','SO','K%','BB%','Whiff%','Swing%','xwOBA','xBA','xSLG','Hard-Hit%','Barrel%','average_swing_speed','wOBA']:
        fill=out.player_id.map(prof[c]) if c in prof.columns else None
        if fill is not None: out[c]=out[c].where(out[c].notna(),fill)
    return out.drop_duplicates(['player_id','pitch_type']).reset_index(drop=True)

def valid(df,name,minrows):
    if len(df)<minrows: raise RuntimeError(f'{name} only {len(df)} rows')
def pub(df,name,last):
    df.to_csv(OUT/name,index=False); shutil.copy2(OUT/name,OUT/last)

def main():
    started=now(); print('Starting live Savant refresh',started)
    pl=platoon(); valid(pl,'platoon',400)
    ba=profile('batter','SAVANT_BATTER_PROFILE_SCHEMA_V1'); valid(ba,'batter',400)
    pi=profile('pitcher','SAVANT_PITCHER_SCHEMA_V1'); valid(pi,'pitcher',500)
    pm=pitchmix(); valid(pm,'pitchmix',1000)
    pub(pl,'savant_batter_platoon_2026.csv','savant_batter_platoon_2026.last_good.csv')
    pub(ba,'savant_batter_profiles.csv','savant_batter_profiles.last_good.csv')
    pub(pi,'savant_pitcher_stats.csv','savant_pitcher_stats.last_good.csv')
    pub(pm,'pitch_mix_matchups.csv','pitch_mix_matchups.last_good.csv')
    done=now()
    man={'active_path':'learning_data/savant_batter_platoon_2026.csv','dataset':'savant_batter_platoon_2026.csv','error':'','last_good_path':'learning_data/savant_batter_platoon_2026.last_good.csv','last_success_at':done,'query_signature':hashlib.sha256(f'platoon|{SEASON}|live'.encode()).hexdigest(),'refresh_completed_at':done,'refresh_started_at':started,'row_count':len(pl),'schema_version':'SAVANT_BATTER_PLATOON_SCHEMA_V1','season':SEASON,'status':'SUCCESS'}
    (OUT/'savant_refresh_manifest.json').write_text(json.dumps(man,indent=2)+'\n')
    aux={'datasets':{'batter_profiles':{'error':'','row_count':len(ba),'status':'SUCCESS'},'pitch_mix_matchups':{'error':'','row_count':len(pm),'status':'SUCCESS'},'pitcher_stats':{'error':'','row_count':len(pi),'status':'SUCCESS'}},'last_success_at':done,'refresh_completed_at':done,'refresh_started_at':started,'schema_version':'SAVANT_AUX_MANIFEST_SCHEMA_V1','season':SEASON,'status':'SUCCESS'}
    (OUT/'savant_aux_refresh_manifest.json').write_text(json.dumps(aux,indent=2)+'\n')
    print('SUCCESS', {p.name:p.stat().st_size for p in OUT.iterdir()})
if __name__=='__main__': main()
