#!/usr/bin/env python
"""T+ cross-check."""
import json, os, sys
from datetime import datetime, timedelta

BASE = r'C:\Users\Administrator\Desktop\automatic\ccass-debug'
os.chdir(BASE)

with open(os.path.join(BASE, 'data', 'announcements.json'), 'r', encoding='utf-8') as f:
    anns = json.load(f)

EXCLUDE = ['配股完成','COMPLETION OF PLACING','COMPLETION OF SUBSCRIPTION',
    'CONVERTIBLE BOND','ZERO COUPON','復牌','RESUMPTION',
    '澄清公告','CLARIFICATION','SUPPLEMENTAL','補充公告',
    'LAPSE OF','TERMINATION','RIGHTS ISSUE','供股',
    'EXTENSION OF LONG STOP','LONG STOP DATE',
    'UPDATE ON','RESULTS OF','POLL RESULTS',
    'MAJOR TRANSACTION','ACQUISITION OF 100%','VERY SUBSTANTIAL ACQUISITION',
    'CONNECTED TRANSACTION','LOAN CAPITALISATION','PLACING OF NON-LISTED WARRANTS']

def real_plcmt(a):
    if '配股' not in a.get('types',[]): return False
    if '供股' in a.get('types',[]): return False
    return not any(w.upper() in a.get('title','').upper() for w in EXCLUDE)

cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
rp = [a for a in anns if real_plcmt(a) and a.get('date','') >= cutoff]
rp.sort(key=lambda a: a['date'], reverse=True)
print(f"=== Real placements T-7: {len(rp)} ===")
for a in rp: print(f"  {a['code']} {a['name']} | {a['date']} | {a.get('title','')[:90]}")

seen={}
deduped=[]
for a in rp:
    c=a['code']
    if c not in seen or a['date']<seen[c]['date']: seen[c]=a
deduped=sorted(seen.values(), key=lambda a: a['date'])
print(f"\n=== Deduped: {len(deduped)} ===")
for a in deduped: print(f"  {a['code']} {a['name']} | {a['date']}")

targets=[a for a in deduped if a['date']<'2026-06-22' and a['date']>='2026-06-15']
print(f"\n=== T+ targets: {len(targets)} ===")
if not targets:
    json.dump({'targets_checked':0,'red_alerts':[],'all_results':[]}, open(os.path.join(BASE,'scanner/_tplus_result.json'),'w'))
    sys.exit(0)

import yfinance as yf
def hk2yf(c): return f"{c[-4:]}.HK"

results=[]
for a in targets:
    code, name, ad = a['code'], a['name'], a['date']
    try:
        tk=yf.Ticker(hk2yf(code))
        df=tk.history(period='1mo',timeout=15)
        if df.empty: 
            print(f"  {code} {name} | NO DATA")
            results.append({**a,'status':'NoData','vol_ratio':None,'cur_price':None,'pct_change':None})
            continue
        cp=float(df['Close'].iloc[-1])
        cv=float(df['Volume'].iloc[-1])
        av=float(df['Volume'].tail(21).head(20).mean()) if len(df)>=20 else float(df['Volume'].mean())
        vr=cv/av if av>0 else 0
        ad_dt=datetime.strptime(ad,'%Y-%m-%d')
        ac=None; ai=None
        for i in range(len(df)):
            idx=df.index[i]
            if hasattr(idx,'date'): dv=idx.date()
            elif hasattr(idx,'to_pydatetime'): dv=idx.to_pydatetime().date()
            else: dv=datetime(idx.year,idx.month,idx.day).date()
            if dv>=ad_dt.date() and ac is None: ac=float(df['Close'].iloc[i]); ai=i; break
        if ac is None: ac=float(df['Close'].iloc[0])
        pc=((cp-ac)/ac*100) if ac>0 else 0
        td=f"~{len(df)-1-ai}" if ai is not None else "?"
        print(f"  {code} {name} | ann={ad} | T+{td} | px={cp:.3f} | Δ={pc:+.1f}% | vol={vr:.2f}x")
        results.append({**a,'status':'ok','vol_ratio':round(vr,2),'cur_price':round(cp,4),'pct_change':round(pc,2),'t_days':td,'ann_close':round(ac,4)})
    except Exception as e:
        print(f"  {code} {name} | ERR: {e}")
        results.append({**a,'status':f'Err','vol_ratio':None,'cur_price':None,'pct_change':None})

print("\n=== RED CHECK ===")
ra=[]
for r in results:
    ip='配股' in r.get('types',[])
    vo=r.get('vol_ratio') is not None and r['vol_ratio']>=1.5
    jo=r.get('pct_change') is not None and r['pct_change']>0 and r['pct_change']>=8
    m=f"配股={'Y' if ip else 'N'} vol={'Y' if vo else 'N'} Δ={'Y' if jo else 'N'}"
    if ip and vo and jo:
        print(f"  🔴 {r['code']} {r['name']} | {m} | {r['date']} T+{r.get('t_days','?')} +{r['pct_change']}% vol={r['vol_ratio']}x")
        ra.append(r)
    else: print(f"  🟡 {r['code']} {r['name']} | {m}")

print(f"\nSUMMARY: {len(ra)} RED, {len(results)} checked")
out={'run_time':datetime.now().isoformat(),'targets_checked':len(targets),
    'red_alerts':[{'code':r['code'],'name':r['name'],'date':r['date'],'vol_ratio':r['vol_ratio'],'pct_change':r['pct_change'],'cur_price':r['cur_price'],'t_days':r.get('t_days'),'title':r.get('title','')[:100]} for r in ra],
    'all_results':[{'code':r['code'],'name':r['name'],'date':r['date'],'vol_ratio':r['vol_ratio'],'pct_change':r['pct_change'],'status':r['status'],'t_days':r.get('t_days')} for r in results]}
json.dump(out, open(os.path.join(BASE,'scanner/_tplus_result.json'),'w'), ensure_ascii=False,indent=2)
print("Done.")
