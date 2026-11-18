# -*- coding: utf-8 -*-
"""用 62325 场历史赔率+赛果，回测：单选 vs 双选 的真实 EV"""
import json, math
from collections import defaultdict

h = json.load(open('odds_hist.json', encoding='utf-8'))
print('历史库总场次:', len(h))

rows=[]
for r in h:
    try:
        oh,od,oa = float(r['oh']), float(r['od']), float(r['oa'])
    except: continue
    if min(oh,od,oa) <= 1.0: continue          # 赔率异常
    ftr = r.get('ftr')
    if ftr not in ('H','D','A'): continue
    rows.append({'oh':oh,'od':od,'oa':oa,'ftr':ftr,'c':r.get('c')})
print('可用(三项赔率齐全+有赛果):', len(rows))

def ev(win_rate, odds):
    """每注1元，赢了拿odds(含本金)，净收益 odds-1"""
    return win_rate*(odds-1) - (1-win_rate)

# ── 策略A：单选最热门（赔率最低的一方）──
print()
print('='*76)
print('【回测】策略A 单选热门 vs 策略B 热门+平局双选')
print('='*76)
print('%-16s %6s %9s %9s %9s %9s'%('热门赔率档','样本','单选命中','双选覆盖','单选EV','双选EV'))
bins=[(1.0,1.5),(1.5,1.8),(1.8,2.1),(2.1,2.5),(2.5,3.0),(3.0,99)]
names=['1.0-1.5','1.5-1.8','1.8-2.1','2.1-2.5','2.5-3.0','3.0+']
res=[]
for (lo,hi),nm in zip(bins,names):
    sub=[]
    for r in rows:
        m=min(r['oh'],r['od'],r['oa'])
        if lo<=m<hi: sub.append(r)
    if len(sub)<100: continue
    n=len(sub)
    # 单选：押最低赔率那一方
    winA=0; oddsA=[]; winB=0; cost2=[]
    for r in sub:
        cand=[('H',r['oh']),('D',r['od']),('A',r['oa'])]
        cand.sort(key=lambda x:x[1])
        fav_side, fav_od = cand[0]
        if r['ftr']==fav_side: winA+=1
        oddsA.append(fav_od)
        # 双选：热门 + 平局（若热门就是平局，则加热门+次低）
        sides={fav_side}
        for s,o in cand:
            if s=='D': sides.add(s)
        if len(sides)<2:
            sides.add(cand[1][0])
        if r['ftr'] in sides: winB+=1
        # 双选等额分配：各押0.5元，中一个拿 0.5*odds
        tot=0
        for s in sides:
            o=dict(cand)[s]
            tot += 0.5*o if r['ftr']==s else 0
        cost2.append(tot-1.0)   # 净收益（投入1元）
    ra=winA/n; rb=winB/n
    avgA=sum(oddsA)/n
    # 单选EV用平均赔率近似
    evA=ra*(avgA-1)-(1-ra)
    evB=sum(cost2)/n
    print('%-16s %6d %8.1f%% %8.1f%% %8.3f %8.3f'%(nm,n,100*ra,100*rb,evA,evB))
    res.append((nm,n,ra,rb,evA,evB))

print()
print('说明：EV = 每投 1 元的长期净收益。负数=亏（博彩抽水必然为负）')
print('      关键看「双选EV - 单选EV」：哪个离 0 更近，哪种打法失血更慢')
print()
print('%-16s %10s %10s %12s'%('热门赔率档','单选EV','双选EV','双选-单选'))
for nm,n,ra,rb,evA,evB in res:
    print('%-16s %9.3f %10.3f %+12.3f'%(nm,evA,evB,evB-evA))

# ── 策略C：只在平局赔率低（容易平）时双选 ──
print()
print('='*76)
print('【关键】按「平局赔率」分档：什么时候双选最划算')
print('='*76)
print('%-14s %6s %8s %8s %9s %9s %10s'%('平局赔率档','样本','单选%','双选%','单选EV','双选EV','双选-单选'))
db=[(0,3.0),(3.0,3.2),(3.2,3.4),(3.4,3.7),(3.7,4.2),(4.2,99)]
dn=['<3.0','3.0-3.2','3.2-3.4','3.4-3.7','3.7-4.2','>4.2']
for (lo,hi),nm in zip(db,dn):
    sub=[r for r in rows if lo<=r['od']<hi]
    if len(sub)<100: continue
    n=len(sub); winA=0; winB=0; cost=[]; oa=[]
    for r in sub:
        cand=[('H',r['oh']),('D',r['od']),('A',r['oa'])]
        cand.sort(key=lambda x:x[1]); d=dict(cand)
        fav=cand[0][0]
        if r['ftr']==fav: winA+=1
        sides={fav,'D'} if fav!='D' else {fav,cand[1][0]}
        if r['ftr'] in sides: winB+=1
        t=sum(0.5*d[s] for s in sides if r['ftr']==s)
        cost.append(t-1.0); oa.append(d[fav])
    ra=winA/n; rb=winB/n; avg=sum(oa)/n
    evA=ra*(avg-1)-(1-ra); evB=sum(cost)/n
    print('%-14s %6d %7.1f%% %7.1f%% %8.3f %8.3f %+10.3f'%(nm,n,100*ra,100*rb,evA,evB,evB-evA))
