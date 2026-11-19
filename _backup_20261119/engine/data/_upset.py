# -*- coding: utf-8 -*-
import json, math, collections, datetime

def load(f):
    return json.load(open(f,encoding='utf-8'))

D=[]
seen=set()
for f in ['odds_hist.json','odds_multi.json','odds_all.json']:
    for x in load(f):
        try:
            oh,od,oa=float(x['oh']),float(x['od']),float(x['oa'])
        except: continue
        if min(oh,od,oa)<=1.0: continue
        k=(x['c'],x['d'],x['h'],x['a'])
        if k in seen: continue
        seen.add(k); D.append(dict(x,oh=oh,od=od,oa=oa))
print('合并去重后场次:',len(D))

def pd(s):
    p=s.split('/')
    if len(p)!=3: return None
    dd,mm,yy=p; y=int(yy); y=2000+y if y<50 else y
    try: return datetime.date(y,int(mm),int(dd))
    except: return None
for x in D: x['dt']=pd(x['d'])
D=[x for x in D if x['dt']]
print('日期可解析:',len(D),'| 范围',min(x['dt'] for x in D),'→',max(x['dt'] for x in D))

# overround
ov=[1/x['oh']+1/x['od']+1/x['oa'] for x in D]
print('平均赔付率(overround): %.4f' % (sum(ov)/len(ov)))

def devig(oh,od,oa):
    s=1/oh+1/od+1/oa
    return (1/oh)/s,(1/od)/s,(1/oa)/s

rows=[]
for x in D:
    ph,pd_,pa=devig(x['oh'],x['od'],x['oa'])
    cand=[('H',x['oh'],ph),('D',x['od'],pd_),('A',x['oa'],pa)]
    side,o,p=min(cand,key=lambda t:t[1])   # 最低赔率=热门
    upset = 1 if x['ftr']!=side else 0
    rows.append(dict(c=x['c'],side=side,odds=o,p=p,upset=upset,dt=x['dt'],
                     res=x['ftr'],draw=1 if x['ftr']=='D' else 0))

def rate(rs):
    n=len(rs); u=sum(r['upset'] for r in rs)
    imp=sum(1-r['p'] for r in rs)/n
    a=u/n
    se=math.sqrt(a*(1-a)/n)
    return n,a,imp,se

print('\n【全样本】')
n,a,imp,se=rate(rows)
print(f'  场次{n}  实际冷门率 {a*100:.2f}%  赔率隐含 {imp*100:.2f}%  差 {(a-imp)*100:+.2f}pp  95%CI ±{1.96*se*100:.2f}pp')

BANDS=[(1.0,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,99)]
print('\n【按热门赔率分档】  实际 vs 隐含')
print(f'{"档":>10} {"场次":>7} {"实际%":>8} {"隐含%":>8} {"差pp":>8} {"±CI":>6}  判定')
for lo,hi in BANDS:
    rs=[r for r in rows if lo<=r['odds']<hi]
    if len(rs)<50: 
        print(f'{f"{lo}-{hi}":>10} {len(rs):>7}   样本不足50，不采信'); continue
    n,a,imp,se=rate(rs)
    d=(a-imp)*100; ci=1.96*se*100
    flag='★可疑' if abs(d)>3 and abs(d)>ci else ('样本<100' if n<100 else '吻合')
    print(f'{f"{lo}-{hi}":>10} {n:>7} {a*100:>8.2f} {imp*100:>8.2f} {d:>+8.2f} {ci:>6.2f}  {flag}')

print('\n【按联赛】平局率 & 冷门率')
print(f'{"联赛":>12} {"场次":>7} {"平局%":>7} {"实际冷门%":>9} {"隐含%":>8} {"差pp":>8} 判定')
for c,rs in sorted(collections.Counter(r['c'] for r in rows).items(), key=lambda kv:-kv[1]):
    rs=[r for r in rows if r['c']==c]
    n=len(rs)
    if n<100: print(f'{c:>12} {n:>7}   样本<100不采信'); continue
    dr=sum(r['draw'] for r in rs)/n
    nn,a,imp,se=rate(rs); d=(a-imp)*100; ci=1.96*se*100
    flag='★可疑' if abs(d)>3 and abs(d)>ci else '吻合'
    print(f'{c:>12} {n:>7} {dr*100:>7.2f} {a*100:>9.2f} {imp*100:>8.2f} {d:>+8.2f} {flag}')

print('\n【主队热门 vs 客队热门】')
for side,lab in (('H','主队热门'),('A','客队热门'),('D','平局热门')):
    rs=[r for r in rows if r['side']==side]
    if len(rs)<50: continue
    n,a,imp,se=rate(rs); d=(a-imp)*100; ci=1.96*se*100
    flag='★可疑' if abs(d)>3 and abs(d)>ci else '吻合'
    print(f'  {lab}  n={n:>6}  实际{a*100:>6.2f}%  隐含{imp*100:>6.2f}%  差{d:>+6.2f}pp  ±{ci:.2f}  {flag}')

json.dump([{'c':r['c'],'d':r['dt'].isoformat(),'side':r['side'],'odds':r['odds'],
            'p':round(r['p'],4),'upset':r['upset'],'res':r['res']} for r in rows],
          open('_upset_rows.json','w'), ensure_ascii=False)
print('\n已导出 _upset_rows.json')
