# PLATOON-ONLY FULL-SEASON BUILD — date-chunked to avoid Savant 25k cap
import io
import json
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests

YEAR=2026
OUT=Path('savant_refresh_output')
STAMP=datetime.now(timezone.utc).isoformat()
SOURCE='BASEBALL_SAVANT_CURRENT_SEASON'
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; OneWayPickz/1.0; +https://baseballsavant.mlb.com/)','Accept':'text/csv,text/plain,*/*'}

def params(a,b):
    return {'all':'true','hfPT':'','hfAB':'','hfGT':'R|','hfPR':'','hfZ':'','hfStadium':'','hfBBL':'',
            'hfNewZones':'','hfPull':'','hfC':'','hfSea':f'{YEAR}|','hfSit':'','player_type':'batter',
            'hfOuts':'','hfOpponent':'','pitcher_throws':'','batter_stands':'','hfSA':'',
            'game_date_gt':a.isoformat(),'game_date_lt':b.isoformat(),'hfMo':'','hfTeam':'','home_road':'',
            'hfRO':'','position':'','hfInfield':'','hfOutfield':'','hfInn':'','hfBBT':'','hfFlag':'',
            'metric_1':'','group_by':'name','min_pitches':'0','min_results':'0','min_pas':'0',
            'sort_col':'pitches','player_event_sort':'api_p_release_speed','sort_order':'desc','type':'details'}

def chunk(sess,a,b):
    r=sess.get('https://baseballsavant.mlb.com/statcast_search/csv',params=params(a,b),headers=HEADERS,timeout=(10,120))
    r.raise_for_status()
    df=pd.read_csv(io.StringIO(r.content.decode('utf-8-sig',errors='replace')),low_memory=False)
    if len(df)>=24990: raise RuntimeError(f'25k cap hit {a}..{b}: {len(df)}')
    needed=['game_pk','at_bat_number','pitch_number','batter','p_throws','events','game_date']
    for c in needed:
        if c not in df.columns: raise RuntimeError(f'missing {c} {a}..{b}')
    return df[needed].copy()

sess=requests.Session(); parts=[]
cur=date(YEAR,3,1); end=datetime.now(timezone.utc).date()
while cur<=end:
    b=min(cur+timedelta(days=3),end)
    df=chunk(sess,cur,b); parts.append(df)
    print(cur,b,len(df),flush=True)
    cur=b+timedelta(days=1); time.sleep(.1)
allp=pd.concat(parts,ignore_index=True)
for c in ['game_pk','at_bat_number','pitch_number','batter']:
    allp[c]=pd.to_numeric(allp[c],errors='coerce')
allp=allp.dropna(subset=['game_pk','at_bat_number','pitch_number','batter','p_throws'])
allp['p_throws']=allp['p_throws'].astype(str).str.upper().str[0]
allp=allp[allp.p_throws.isin(['R','L'])]
allp=allp.sort_values(['game_pk','at_bat_number','pitch_number'])
allp=allp.drop_duplicates(['game_pk','at_bat_number','pitch_number'],keep='last')
pa=allp.groupby(['game_pk','at_bat_number'],as_index=False).tail(1).copy()
pa['is_so']=pa['events'].astype(str).str.lower().isin(['strikeout','strikeout_double_play']).astype(int)
agg=pa.groupby(['batter','p_throws']).agg(PA=('batter','size'),SO=('is_so','sum')).reset_index()
pp=agg.pivot(index='batter',columns='p_throws',values='PA').fillna(0)
sp=agg.pivot(index='batter',columns='p_throws',values='SO').fillna(0)
bp=pd.read_csv(OUT/'savant_batter_profiles.csv',low_memory=False)
name_map=dict(zip(pd.to_numeric(bp.player_id,errors='coerce'),bp.player_name))
rows=[]
for pid in sorted(set(pp.index).union(sp.index)):
    rp=int(pp.loc[pid,'R']) if pid in pp.index and 'R' in pp.columns else 0
    lp=int(pp.loc[pid,'L']) if pid in pp.index and 'L' in pp.columns else 0
    rs=int(sp.loc[pid,'R']) if pid in sp.index and 'R' in sp.columns else 0
    ls=int(sp.loc[pid,'L']) if pid in sp.index and 'L' in sp.columns else 0
    op=rp+lp; os=rs+ls
    if not op: continue
    rows.append({'mlbam_id':int(pid),'player_name':name_map.get(pid,''),'team':'','season':YEAR,
                 'vs_rhp_pa':rp,'vs_rhp_so':rs,'vs_rhp_k_pct':100*rs/rp if rp else pd.NA,
                 'vs_lhp_pa':lp,'vs_lhp_so':ls,'vs_lhp_k_pct':100*ls/lp if lp else pd.NA,
                 'overall_pa':op,'overall_so':os,'overall_k_pct':100*os/op,
                 'source':SOURCE,'source_timestamp':STAMP,'refresh_status':'CURRENT'})
out=pd.DataFrame(rows)
cols=['mlbam_id','player_name','team','season','vs_rhp_pa','vs_rhp_so','vs_rhp_k_pct','vs_lhp_pa','vs_lhp_so','vs_lhp_k_pct','overall_pa','overall_so','overall_k_pct','source','source_timestamp','refresh_status']
out=out[cols].sort_values(['player_name','mlbam_id']).reset_index(drop=True)
if len(out)<500: raise RuntimeError(f'platoon sanity rows={len(out)}')
# cross-check aggregate PA against live batter leaderboard; small differences can exist from edge events, but not large systemic gaps
profile_total=pd.to_numeric(bp.PA,errors='coerce').fillna(0).sum()
platoon_total=out.overall_pa.sum()
ratio=platoon_total/profile_total if profile_total else 0
if not (0.94<=ratio<=1.06): raise RuntimeError(f'PA coverage sanity failed ratio={ratio:.4f}')
out.to_csv(OUT/f'savant_batter_platoon_{YEAR}.csv',index=False)
shutil.copyfile(OUT/f'savant_batter_platoon_{YEAR}.csv',OUT/f'savant_batter_platoon_{YEAR}.last_good.csv')
summary={'status':'SUCCESS','timestamp':STAMP,'rows':len(out),'plate_appearances':int(platoon_total),'profile_pa':int(profile_total),'coverage_ratio':ratio,'pitch_rows':len(allp)}
(OUT/'platoon_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
