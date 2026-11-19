# -*- coding: utf-8 -*-
import json, math, collections
rows=json.load(open('_upset_rows.json',encoding='utf-8'))
for r in rows: r['y']=int(r['d'][:4])

def stat(rs,key):
    n=len(rs)
    if n<50: return None
    a=sum(r[key] for r in rs)/n
    imp=sum(1-r['p'] for r in rs)/n if key=='upset' else sum(r['p'] for r in rs)/n
    se=math.sqrt(a*(1-a)/n)
    return n,a,imp,(a-imp)*100,1.96*se*100

print('【跨期验证】1.0-1.5 热门档：分年度看是否稳定负偏离')
print(f'{"赛季":>8} {"场次":>6} {"实际%":>7} {"隐含%":>7} {"差pp":>7} {"±CI":>6}')
for y in sorted(set(r['y'] for r in rows)):
    rs=[r for r in rows if r['y']==y and r['odds']<1.5]
    s=stat(rs,'upset')
    if not s: continue
    n,a,imp,d,ci=s
    print(f'{y:>8} {n:>6} {a*100:>7.2f} {imp*100:>7.2f} {d:>+7.2f} {ci:>6.2f}')

print('\n【训练/测试切分】1.0-1.5档')
for lab,f in (('训练 2002-2008',lambda r:r['y']<=2008),('测试 2009-2013',lambda r:r['y']>=2009)):
    rs=[r for r in rows if r['odds']<1.5 and f(r)]
    n,a,imp,d,ci=stat(rs,'upset')
    print(f'  {lab}: n={n}  实际{a*100:.2f}%  隐含{imp*100:.2f}%  差{d:+.2f}pp  ±{ci:.2f}')

print('\n【细分短赔率】')
for lo,hi in [(1.0,1.2),(1.2,1.33),(1.33,1.5),(1.5,1.8),(1.8,2.0)]:
    rs=[r for r in rows if lo<=r['odds']<hi]
    s=stat(rs,'upset')
    if not s: print(f'  {lo}-{hi}: 样本<50'); continue
    n,a,imp,d,ci=s
    flag='★' if abs(d)>3 and abs(d)>ci else ''
    print(f'  {lo:>4}-{hi:<5} n={n:>6}  实际{a*100:>6.2f}%  隐含{imp*100:>6.2f}%  差{d:>+6.2f}pp  ±{ci:>5.2f} {flag}')

print('\n【★ 平局专项（任九最关心）：实际平局率 vs 赔率隐含】')
print(f'{"联赛":>12} {"场次":>7} {"实际平局%":>9} {"隐含平局%":>9} {"差pp":>7} {"±CI":>6} 判定')
# 重建平局隐含概率：需要原始赔率，重新算
raw=[]
for x in json.load(open('_upset_rows.json',encoding='utf-8')):
    raw.append(x)
