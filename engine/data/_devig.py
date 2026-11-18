# -*- coding: utf-8 -*-
import json, math, collections, datetime
def load(f): return json.load(open(f,encoding='utf-8'))
D=[];seen=set()
for f in ['odds_hist.json','odds_multi.json','odds_all.json']:
    for x in load(f):
        try: oh,od,oa=float(x['oh']),float(x['od']),float(x['oa'])
        except: continue
        if min(oh,od,oa)<=1.0: continue
        k=(x['c'],x['d'],x['h'],x['a'])
        if k in seen: continue
        seen.add(k); D.append((x['c'],x['d'],x['h'],x['a'],x['ftr'],oh,od,oa))
print('总场次',len(D))

def prop(o):
    s=sum(1/v for v in o); return [ (1/v)/s for v in o]

def shin(o):
    # Shin (1993) 方法：估计内幕交易比例 z
    lo,hi=0.0,0.99
    for _ in range(60):
        z=(lo+hi)/2
        s=0.0
        for v in o:
            p=1/v
            s+= (z*p + (1-z)*p*p/ (1-z+ z*p) ) if False else 0
        # 用标准 Shin 方程：sum over i of  pi(z) = 1
        tot=0.0
        for v in o:
            p=1/v
            tot += (z + (1-z)*p) and 0
        break
    # 简化：用等价形式 sum_i [ (z + (1-z)*p_i)^? ] 直接数值解
    def eq(z):
        tot=0.0
        for v in o:
            p=1/v
            tot += ( (z**2 + 4*(1-z)*p**2)**0.5 - z ) / (2*(1-z)) if z<1 else p
        return tot-1
    lo,hi=1e-9,0.5
    for _ in range(80):
        mid=(lo+hi)/2
        if eq(mid)>0: lo=mid
        else: hi=mid
    z=(lo+hi)/2
    out=[]
    for v in o:
        p=1/v
        out.append(( (z*z + 4*(1-z)*p*p)**0.5 - z )/(2*(1-z)))
    s=sum(out)
    return [v/s for v in out]

def oratio(o):
    # odds-ratio (logarithmic) 方法
    import math
    s=sum(1/v for v in o)
    # 数值解 c
    lo,hi=0.01,10.0
    def f(c):
        return sum(1.0/(v**c) for v in o)-1
    for _ in range(80):
        mid=(lo+hi)/2
        if f(mid)>0: lo=mid
        else: hi=mid
    c=(lo+hi)/2
    raw=[ (1/v)**c for v in o ]
    s=sum(raw); return [v/s for v in raw]

RES={}
for name,fn in (('比例法',prop),('Shin法',shin),('赔率比法',oratio)):
    rows=[]
    for c,d,h,a,ftr,oh,od,oa in D:
        try: ph,pdd,pa=fn([oh,od,oa])
        except: continue
        cand=[('H',oh,ph),('D',od,pdd),('A',oa,pa)]
        side,o,p=min(cand,key=lambda t:t[1])
        rows.append(dict(side=side,odds=o,p=p,upset=1 if ftr!=side else 0,
                         draw=1 if ftr=='D' else 0, pd=pdd, y=int(d.split('/')[-1][-2:])))
    RES[name]=rows
    print(f'\n===== {name} =====')
    print(f'{"赔率档":>12} {"场次":>7} {"实际%":>7} {"隐含%":>7} {"差pp":>7} {"±CI":>6}')
    for lo_b,hi_b in [(1.0,1.5),(1.5,2.0),(2.0,2.5),(2.5,9)]:
        rs=[r for r in rows if lo_b<=r['odds']<hi_b]
        n=len(rs)
        if n<50: continue
        a=sum(r['upset'] for r in rs)/n
        imp=sum(1-r['p'] for r in rs)/n
        se=math.sqrt(a*(1-a)/n)
        d=(a-imp)*100; ci=1.96*se*100
        flag='★' if abs(d)>3 and abs(d)>ci else ''
        print(f'{f"{lo_b}-{hi_b}":>12} {n:>7} {a*100:>7.2f} {imp*100:>7.2f} {d:>+7.2f} {ci:>6.2f} {flag}')
json.dump({k:[{kk:vv for kk,vv in r.items()} for r in v] for k,v in RES.items()},
          open('_devig_res.json','w'))
