# -*- coding: utf-8 -*-
"""策略评估：单选 vs 双选 vs 爆冷预测 vs 比分top3"""
import json, math
from collections import defaultdict, Counter
d = json.load(open('_archive_done.json', encoding='utf-8'))

def is_spf(m): return m in ('主胜','客胜','平局')
def dir_of_ft(ft):
    if not ft: return None
    try: a,b = [int(x) for x in ft.replace(':','-').split('-')[:2]]
    except: return None
    return '主胜' if a>b else ('客胜' if a<b else '平局')

def ci(k,n):
    if n==0: return (0,0)
    z=1.96; ph=k/n; den=1+z*z/n
    c=(ph+z*z/(2*n))/den
    h=z*math.sqrt(ph*(1-ph)/n+z*z/(4*n*n))/den
    return (max(0,c-h),min(1,c+h))

# ═══ 1. 单选 vs 双选 ═══
print('='*74)
print('【核心对比】单选 vs 双选')
print('='*74)
sing=[]; doub=[]
for t in d:
    m=t.get('main'); alt=t.get('alt')
    if not is_spf(m): continue
    r=dir_of_ft(t.get('ft')) or t.get('actual')
    if not is_spf(r): continue
    sing.append(1 if m==r else 0)
    if is_spf(alt) and alt != m:
        doub.append(1 if (r==m or r==alt) else 0)
if sing:
    n=len(sing);k=sum(sing);lo,hi=ci(k,n)
    print('单选   n=%3d 命中%3d  %5.1f%%  CI[%.0f,%.0f]'%(n,k,100*k/n,100*lo,100*hi))
if doub:
    n=len(doub);k=sum(doub);lo,hi=ci(k,n)
    print('双选   n=%3d 命中%3d  %5.1f%%  CI[%.0f,%.0f]'%(n,k,100*k/n,100*lo,100*hi))
    print('双选提升: %+.1f 个百分点 (成本翻倍)'%(100*k/n-100*sum(sing[:len(doub)])/len(doub)))
print()

# ═══ 2. 双选该不该用 —— 按平局概率分档 ═══
print('='*74)
print('【关键】什么时候该双选？按平局概率分档看双选增益')
print('='*74)
print('%-14s %5s %8s %8s %9s   %s'%('平局概率档','样本','单选率','双选率','双选增益','判断'))
buck=defaultdict(lambda: {'s':[],'d':[]})
for t in d:
    m=t.get('main'); alt=t.get('alt'); dp=t.get('draw_p')
    if not is_spf(m): continue
    if not isinstance(dp,(int,float)): continue
    r=dir_of_ft(t.get('ft')) or t.get('actual')
    if not is_spf(r): continue
    for a,b,n2 in ((0,20,'<20%'),(20,25,'20-25%'),(25,28,'25-28%'),(28,32,'28-32%'),(32,100,'≥32%')):
        if a<=dp<b:
            buck[n2]['s'].append(1 if m==r else 0)
            if is_spf(alt) and alt!=m:
                buck[n2]['d'].append(1 if (r==m or r==alt) else 0)
            break
for nm in ('<20%','20-25%','25-28%','28-32%','≥32%'):
    v=buck.get(nm)
    if not v or len(v['s'])<8: continue
    n=len(v['s']); s=100*sum(v['s'])/n
    if v['d']:
        nd=len(v['d']); dd=100*sum(v['d'])/nd
        g=dd-s
        j='✅值得双选' if g>=15 else ('中性' if g>=8 else '❌不必双选')
        print('%-14s %5d %7.1f%% %7.1f%% %+8.1f   %s'%(nm,n,s,dd,g,j))
    else:
        print('%-14s %5d %7.1f%%      —        —'%(nm,n,s))
print()

# ═══ 3. 爆冷预测准确度 ═══
print('='*74)
print('【爆冷预测】upset 字段命中率（我标了可能爆冷的场次，实际爆冷了吗）')
print('='*74)
up_hit=[]; up_all=[]
for t in d:
    u=t.get('upset'); uh=t.get('upsetHit')
    if u is None or uh is None: continue
    up_all.append(1 if uh else 0)
print('有爆冷预测的场次: %d，命中 %d = %.1f%%'%(len(up_all),sum(up_all),
      100*sum(up_all)/len(up_all) if up_all else 0))
# 对照组：没标爆冷的场次，实际爆冷率
no_up=[]
for t in d:
    if t.get('upset') is None and t.get('upsetHit') is not None:
        no_up.append(1 if t['upsetHit'] else 0)
print('未标爆冷的场次: %d，实际爆冷 %d = %.1f%%'%(len(no_up),sum(no_up),
      100*sum(no_up)/len(no_up) if no_up else 0))
if up_all and no_up:
    a=100*sum(up_all)/len(up_all); b=100*sum(no_up)/len(no_up)
    print('区分度: %+.1f 个百分点 %s'%(a-b, '✅预测有效' if a-b>8 else '⚠区分度弱'))
print()

# ═══ 4. 比分 top3 命中率 ═══
print('='*74)
print('【比分】top3 预测命中率')
print('='*74)
tp=[]
for t in d:
    if t.get('top3') and t.get('top3Hit') is not None:
        tp.append(1 if t['top3Hit'] else 0)
if tp:
    n=len(tp);k=sum(tp);lo,hi=ci(k,n)
    print('top3比分  n=%d 命中%d = %.1f%%  CI[%.0f,%.0f]'%(n,k,100*k/n,100*lo,100*hi))
    print('  (随机猜3个比分约 3/36 ≈ 8%%，模型 %0.1f%%)'%(100*k/n))
big=[]
for t in d:
    if t.get('big') and t.get('bigHit') is not None:
        big.append(1 if t['bigHit'] else 0)
if big:
    print('big冷门比分 n=%d 命中%d = %.1f%%'%(len(big),sum(big),100*sum(big)/len(big)))
print()

# ═══ 5. 主推 vs 备选：平局捕获 ═══
print('='*74)
print('【平局捕获】实际打平的场次里，我的主推/备选覆盖了多少')
print('='*74)
draws=[t for t in d if (dir_of_ft(t.get('ft')) or t.get('actual'))=='平局']
print('实际平局场次: %d'%len(draws))
c1=sum(1 for t in draws if t.get('main')=='平局')
c2=sum(1 for t in draws if t.get('alt')=='平局')
print('  主推=平局: %d (%.1f%%)  ← 主推是argmax，平局概率永远不是最大'%(c1,100*c1/len(draws)))
print('  备选=平局: %d (%.1f%%)'%(c2,100*c2/len(draws)))
print('  → 平局只能靠双选捕获，单选结构性抓不到')
