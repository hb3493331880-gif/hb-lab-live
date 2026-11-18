# -*- coding: utf-8 -*-
import json, csv, collections
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
        D.append((x['c'],x['d'],x['h'],x['a'],x['ftr'],oh,od,oa))
D.sort(key=lambda r:(r[0],r[1]))
ZH={'england':'英格兰','spain':'西班牙','italy':'意大利','france':'法国','germany':'德国',
    'scotland':'苏格兰','netherlands':'荷兰','turkey':'土耳其','belgium':'比利时',
    'portulgal':'葡萄牙','greece':'希腊'}
with open('/data/workspace/hb-football-lab/历史数据_70418场.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f)
    w.writerow(['联赛','联赛中文','日期','主队','客队','赛果','主赔','平赔','客赔'])
    ZHr={'H':'主胜','D':'平','A':'客胜'}
    for c,d,h,a,ftr,oh,od,oa in D:
        w.writerow([c,ZH.get(c,c),d,h,a,ZHr.get(ftr,ftr),oh,od,oa])
print('CSV 已导出，行数',len(D))
print('联赛分布:',collections.Counter(r[0] for r in D).most_common())
