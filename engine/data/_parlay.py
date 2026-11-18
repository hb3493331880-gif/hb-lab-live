# -*- coding: utf-8 -*-
"""关键区分：单关/串关 vs 任九(9场全中) —— 双选价值完全不同"""
import json

h = json.load(open('odds_hist.json', encoding='utf-8'))
rows=[]
for r in h:
    try: oh,od,oa=float(r['oh']),float(r['od']),float(r['oa'])
    except: continue
    if min(oh,od,oa)<=1.0: continue
    if r.get('ftr') not in ('H','D','A'): continue
    rows.append({'oh':oh,'od':od,'oa':oa,'ftr':r['ftr']})

def rates(sub):
    n=len(sub); winA=0; winB=0; oa=[]
    for r in sub:
        cand=[('H',r['oh']),('D',r['od']),('A',r['oa'])]
        cand.sort(key=lambda x:x[1]); d=dict(cand)
        fav=cand[0][0]
        if r['ftr']==fav: winA+=1
        sides={fav,'D'} if fav!='D' else {fav,cand[1][0]}
        if r['ftr'] in sides: winB+=1
        oa.append(d[fav])
    return winA/n, winB/n, sum(oa)/n

print('='*78)
print('【场景1】竞彩单关：双选 = 用双倍成本买更高命中率 → 看 EV')
print('='*78)
print('结论已在上一轮得出：双选 EV 全面劣于单选，短赔率尤其明显')
print()

print('='*78)
print('【场景2】任九：14选9，必须 9 场全中 → 看「全中概率 / 成本」性价比')
print('='*78)
print('%-14s %7s %7s %10s %10s %10s'%('热门赔率档','单选率','双选率','9场全中(单)','9场全中(双)','提升倍数'))
for (lo,hi),nm in zip([(1.0,1.5),(1.5,1.8),(1.8,2.1),(2.1,2.5),(2.5,3.0),(3.0,99)],
                      ['1.0-1.5','1.5-1.8','1.8-2.1','2.1-2.5','2.5-3.0','3.0+']):
    sub=[r for r in rows if lo<=min(r['oh'],r['od'],r['oa'])<hi]
    if len(sub)<100: continue
    ra,rb,avg=rates(sub)
    p1=ra**9; p2=rb**9
    print('%-14s %6.1f%% %6.1f%% %9.4f%% %9.4f%% %9.1fx'%(nm,100*ra,100*rb,100*p1,100*p2,p2/p1))

print()
print('  注：9场全中概率 = 单场命中率^9。双选后每场命中率提高，全中率指数级提升。')
print('  但成本 2^9=512 倍。所以要看「奖金是否同步放大」——任九是浮动奖金池，')
print('  不是 512 倍奖金，所以任九双选同样不划算，除非只挑 2-3 场双选做容错。')
print()

print('='*78)
print('【场景3】最优解：只对「最容易翻车的 2-3 场」双选，其余单选')
print('='*78)
print('假设 9 场里，7 场单选(命中率 ra)、2 场双选(命中率 rb)：')
print('%-14s %10s %10s %10s %12s'%('热门赔率档','全单选','7单+2双','4单+5双','成本(7+2)'))
for (lo,hi),nm in zip([(1.0,1.5),(1.5,1.8),(1.8,2.1),(2.1,2.5),(2.5,3.0),(3.0,99)],
                      ['1.0-1.5','1.5-1.8','1.8-2.1','2.1-2.5','2.5-3.0','3.0+']):
    sub=[r for r in rows if lo<=min(r['oh'],r['od'],r['oa'])<hi]
    if len(sub)<100: continue
    ra,rb,avg=rates(sub)
    p_all=ra**9
    p_2=ra**7 * rb**2
    p_5=ra**4 * rb**5
    print('%-14s %9.4f%% %9.4f%% %9.4f%% %11.0fx'%(nm,100*p_all,100*p_2,100*p_5,2**2))

print()
print('='*78)
print('【场景4】翻倍倍数：双选2场，全中率提升多少倍 / 成本提升多少倍')
print('='*78)
for (lo,hi),nm in zip([(1.5,1.8),(1.8,2.1),(2.1,2.5),(2.5,3.0)],
                      ['1.5-1.8','1.8-2.1','2.1-2.5','2.5-3.0']):
    sub=[r for r in rows if lo<=min(r['oh'],r['od'],r['oa'])<hi]
    if len(sub)<100: continue
    ra,rb,avg=rates(sub)
    gain=(ra**7*rb**2)/(ra**9)
    print('  %-10s 全中率提升 %.2f 倍，成本提升 4 倍 → %s'%(nm,gain,
          '❌不划算' if gain<4 else ('⚠勉强' if gain<5 else '✅划算')))
