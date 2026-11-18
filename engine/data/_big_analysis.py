# -*- coding: utf-8 -*-
"""综合多因子分析：自己的预测样本 + 足球大样本交叉验证"""
import json, math
from collections import defaultdict

d = json.load(open('_archive_done.json', encoding='utf-8'))

def is_spf(m):  # 只保留胜平负方向，剔除让球盘
    return m in ('主胜','客胜','平局')

def dir_of_ft(ft):
    if not ft: return None
    ft = ft.replace(':', '-')
    try:
        a, b = ft.split('-')[:2]
        a, b = int(a), int(b)
    except: return None
    return '主胜' if a > b else ('客胜' if a < b else '平局')

# 构建干净样本：有赛果、有主推(胜平负)、有概率
rows = []
for t in d:
    ft = t.get('ft')
    m  = t.get('main')
    p  = t.get('main_p')
    if not is_spf(m): continue
    r  = dir_of_ft(ft) or t.get('actual')
    if not is_spf(r): continue
    if not isinstance(p, (int, float)): continue
    od = t.get('odds') or []
    try: od = [float(x) for x in od if x not in (None,'')]
    except: od = []
    rows.append({
        'no': t.get('no'), 'lg': t.get('lg'), 'h': t.get('h'), 'a': t.get('a'),
        'main': m, 'p': float(p), 'real': r,
        'hit': 1 if m == r else 0,
        'odds': od,
        'fav': min(od) if len(od) >= 3 else None,
        'draw_od': od[1] if len(od) >= 3 else None,
        'mod': t.get('_m'),
    })

print('干净样本(有赛果+胜平负主推+概率):', len(rows))
print('总命中: %d / %d = %.1f%%' % (sum(r['hit'] for r in rows), len(rows),
      100.0*sum(r['hit'] for r in rows)/len(rows)))
print()

def ci(k, n):
    """Wilson 95% 置信区间"""
    if n == 0: return (0, 0)
    z = 1.96
    ph = k / n
    den = 1 + z*z/n
    ctr = (ph + z*z/(2*n)) / den
    hw  = z * math.sqrt(ph*(1-ph)/n + z*z/(4*n*n)) / den
    return (max(0, ctr-hw), min(1, ctr+hw))

def show(title, buckets, minn=30):
    print('─'*72)
    print(title)
    print('%-22s %5s %6s %7s %7s  %s' % ('分组','样本','命中','实际率','预期率','差(pp) 95%CI'))
    out = []
    for name, rs in buckets:
        n = len(rs); 
        if n == 0: continue
        k = sum(r['hit'] for r in rs)
        act = 100.0*k/n
        exp = sum(r['p'] for r in rs)/n
        lo, hi = ci(k, n)
        flag = '  ' if n >= minn else '⚠'
        print('%-22s %5d %6d %6.1f%% %6.1f%%  %+6.1f  [%.0f,%.0f]%s' %
              (name, n, k, act, exp, act-exp, 100*lo, 100*hi, flag))
        out.append((name, n, k, act, exp))
    print()
    return out

# ① 按概率档
bins = [(0,40,'0-40%'),(40,50,'40-50%'),(50,55,'50-55%'),(55,60,'55-60%'),
        (60,70,'60-70%'),(70,80,'70-80%'),(80,100,'80%+')]
b = []
for lo,hi,nm in bins:
    b.append((nm, [r for r in rows if lo <= r['p'] < hi]))
show('① 按主推概率档（核心校准）', b)

# ② 按热门赔率档
bins2 = [(0,1.5,'赔率<1.5'),(1.5,2.0,'1.5-2.0'),(2.0,2.5,'2.0-2.5'),
         (2.5,3.5,'2.5-3.5'),(3.5,99,'3.5+')]
b = []
for lo,hi,nm in bins2:
    b.append((nm, [r for r in rows if r['fav'] and lo <= r['fav'] < hi]))
show('② 按热门赔率档', b)

# ③ 按平局赔率（平局风险）
b = [
    ('平赔<3.0(高危)', [r for r in rows if r['draw_od'] and r['draw_od'] < 3.0]),
    ('3.0-3.3',        [r for r in rows if r['draw_od'] and 3.0 <= r['draw_od'] < 3.3]),
    ('3.3-3.6',        [r for r in rows if r['draw_od'] and 3.3 <= r['draw_od'] < 3.6]),
    ('>3.6(低危)',     [r for r in rows if r['draw_od'] and r['draw_od'] >= 3.6]),
]
show('③ 按平局赔率（平局风险）', b)

# ④ 按主推方向
b = [('主胜', [r for r in rows if r['main']=='主胜']),
     ('客胜', [r for r in rows if r['main']=='客胜'])]
show('④ 按主推方向', b)

# ⑤ 按联赛（样本>=25）
lg = defaultdict(list)
for r in rows: lg[r['lg']].append(r)
b = sorted([(k, v) for k, v in lg.items() if len(v) >= 25], key=lambda x: -len(x[1]))
show('⑤ 按联赛（样本≥25）', b, minn=25)

# ⑥ 按模块
b = [('竞彩', [r for r in rows if r['mod']=='竞彩']),
     ('北单', [r for r in rows if r['mod']=='北单']),
     ('任九', [r for r in rows if r['mod']=='任九'])]
show('⑥ 按模块', b)

# ⑦ 交叉：概率档 × 主推方向
print('─'*72)
print('⑦ 交叉：概率档 × 主推方向')
for lo,hi,nm in bins:
    for md in ('主胜','客胜'):
        rs = [r for r in rows if lo <= r['p'] < hi and r['main']==md]
        if len(rs) < 20: continue
        n=len(rs); k=sum(r['hit'] for r in rs)
        lo2,hi2 = ci(k,n)
        print('  %-8s %-3s n=%3d 命中%3d 实际%5.1f%% 预期%5.1f%% 差%+5.1f CI[%.0f,%.0f]'
              % (nm, md, n, k, 100*k/n, sum(r['p'] for r in rs)/n,
                 100*k/n - sum(r['p'] for r in rs)/n, 100*lo2, 100*hi2))
print()

# ⑧ 翻车形态：主推没中，实际是什么
print('─'*72)
print('⑧ 翻车形态分解（主推未中时，实际结果是什么）')
miss = [r for r in rows if not r['hit']]
print('  总翻车 %d 场' % len(miss))
from collections import Counter
c = Counter(r['real'] for r in miss)
for k,v in c.most_common():
    print('    → %s  %d 场 (%.1f%%)' % (k, v, 100*v/len(miss)))
# 平局在其中的占比 vs 平局总体占比
draw_all = sum(1 for r in rows if r['real']=='平局')
print('  对比：全部样本中平局占 %.1f%% (%d/%d)' % (100*draw_all/len(rows), draw_all, len(rows)))
json.dump(rows, open('_clean_rows.json','w',encoding='utf-8'), ensure_ascii=False)
