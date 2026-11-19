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
        seen.add(k)
        yy=x['d'].split('/')[-1]
        yr=int(yy) if len(yy)==4 else 2000+int(yy)
        D.append((x['c'],yr,x['ftr'],oh,od,oa))
def shin(o):
    def eq(z):
        tot=0.0
        for v in o:
            p=1/v; tot += (( z*z + 4*(1-z)*p*p )**0.5 - z)/(2*(1-z))
        return tot-1
    lo,hi=1e-9,0.5
    for _ in range(80):
        mid=(lo+hi)/2
        if eq(mid)>0: lo=mid
        else: hi=mid
    z=(lo+hi)/2
    out=[(( z*z + 4*(1-z)*(1/v)**2 )**0.5 - z)/(2*(1-z)) for v in o]
    s=sum(out); return [v/s for v in out]

rows=[]
for c,yr,ftr,oh,od,oa in D:
    ph,pdd,pa=shin([oh,od,oa])
    rows.append(dict(c=c,y=yr,draw=1 if ftr=='D' else 0,pd=pdd,od=od))

def st(rs):
    n=len(rs); a=sum(r['draw'] for r in rs)/n
    imp=sum(r['pd'] for r in rs)/n
    se=math.sqrt(a*(1-a)/n)
    return n,a,imp,(a-imp)*100,1.96*se*100

print('【平局专项 · Shin去水 · 全70,418场】实际平局率 vs 赔率隐含平局率')
print(f'{"联赛":>12} {"场次":>7} {"实际平局%":>9} {"隐含%":>8} {"差pp":>7} {"±CI":>6} 判定')
for c in sorted(set(r["c"] for r in rows), key=lambda c:-sum(1 for r in rows if r["c"]==c)):
    rs=[r for r in rows if r['c']==c]
    if len(rs)<100: continue
    n,a,imp,d,ci=st(rs)
    flag='★平局被低估(易出冷)' if d>3 and d>ci else ('平局被高估' if d<-3 and abs(d)>ci else '吻合')
    print(f'{c:>12} {n:>7} {a*100:>9.2f} {imp*100:>8.2f} {d:>+7.2f} {ci:>6.2f} {flag}')

print('\n【按平局赔率分档】平局赔率越低=市场越看好平局')
print(f'{"平赔档":>10} {"场次":>7} {"实际%":>7} {"隐含%":>7} {"差pp":>7} {"±CI":>6}')
for lo,hi in [(2.0,3.0),(3.0,3.4),(3.4,3.8),(3.8,4.5),(4.5,99)]:
    rs=[r for r in rows if lo<=r['od']<hi]
    if len(rs)<50: continue
    n,a,imp,d,ci=st(rs)
    flag='★' if abs(d)>3 and abs(d)>ci else ''
    print(f'{f"{lo}-{hi}":>10} {n:>7} {a*100:>7.2f} {imp*100:>7.2f} {d:>+7.2f} {ci:>6.2f} {flag}')

print('\n【跨期验证：平局率最高的两个联赛】')
for c in ('italy','france'):
    for lab,f in (('2002-2008',lambda y:y<=2008),('2009-2013',lambda y:y>=2009)):
        rs=[r for r in rows if r['c']==c and f(r['y'])]
        n,a,imp,d,ci=st(rs)
        print(f'  {c:>8} {lab}: n={n:>5}  实际{a*100:.2f}%  隐含{imp*100:.2f}%  差{d:+.2f}pp  ±{ci:.2f}')
