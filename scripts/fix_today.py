#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建后处理：把模板里「写死的今日数据」换成当天真实抓回来的数据。

背景（这次踩到的坑）：
  · 页面顶部「🔴 今日竞彩 · 真实数据（体彩官网 2026-09-22 11:00:31）」
    和「🔴 今日北单 · 在售 7 场」两块，读的是模板里 **硬编码** 的
    window.__JC_TODAY__ / window.__BJ_TODAY__，日期与场次永远停在 2026-09-22，
    抓取脚本从来不写它们 → 打开永远是旧表，看着像"没更新"。
  · 「2串1」推荐框读 window.__COMBO_HISTORY__，也是模板里写死的快照，
    停在 11-16，没有任何脚本生成当天的串关。

本脚本在 make_live 出页之后运行，做三件事：
  1. 用 engine/data/full.json（今天官方竞彩，含赔率与概率）重写 __JC_TODAY__；
  2. 用 engine/data/_bj_latest_full.json（今天北单，按销售日分组）重写 __BJ_TODAY__；
  3. 用当天竞彩算一注 2串1，写进 combo_history.json 并重写 __COMBO_HISTORY__。
概率口径统一：赔率去水（与页面顶部「本页概率 = 赔率去水概率」一致），
不编造官方支持率与伤停，缺的字段一律留空。
"""
import datetime
import io
import json
import os
import re
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
PAGE = os.path.join(BASE, 'index.html')
LB = ['主胜', '平局', '客胜']


def load(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.isfile(p):
        return default
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return default


def devig(o):
    inv = [1.0 / x for x in o]
    s = sum(inv)
    return [x / s * 100 for x in inv]


def jc_today():
    f = load('full.json') or {}
    out = []
    for m in (f.get('matches') or []):
        o = m.get('o') or []
        if len(o) != 3:
            continue                       # 未开售不列，避免编概率
        p = m.get('p') if m.get('p') else devig(o)
        best = max(range(3), key=lambda i: p[i])
        tm = (m.get('tm') or '')[:5]
        d = m.get('date') or ''
        try:
            d2 = datetime.date(*[int(x) for x in d.split('-')])
            tms = '%d/%d %s' % (d2.month, d2.day, tm)
        except Exception:
            tms = tm
        out.append({'no': m.get('no') or m.get('num'), 'num': m.get('no') or m.get('num'),
                    'lg': m.get('lg') or '',
                    'm': '%s vs %s' % (m.get('h'), m.get('a')),
                    'o': [round(x, 2) for x in o],
                    'sp': [round(x, 2) for x in o],
                    'h': round(p[0], 1), 'd': round(p[1], 1), 'a': round(p[2], 1),
                    'rec': LB[best], 'hcap': m.get('hcap') or 0, 'tm': tms,
                    # 官方支持率（资金占比）官方接口不提供，按口径留空，不编数
                    'sup': ['—', '—', '—'],
                    'fund': None, 'src': 'official-webapi'})
    return out


def _bj_ana(m, sp, p, best, lg):
    """北单逐场分析：只用赔率+归档算，缺的如实写缺失，不编。（对齐脑图 12 维里能落地的部分）"""
    arch = load('_archive_done.json') or []
    if not getattr(_bj_ana, '_cache', None):
        tot = len([x for x in arch if x.get('actual')])
        draw_n = len([x for x in arch if x.get('actual') == '平局'])
        flip = [x for x in arch if x.get('actual') and x.get('main') and x['actual'] != x['main']]
        lg_d = {}
        band = {}
        for x in arch:
            g = x.get('lg') or ''
            if g:
                d = lg_d.setdefault(g, [0, 0])
                d[1] += 1
                if x.get('actual') == '平局':
                    d[0] += 1
            if x.get('main_p') and x.get('actual'):
                b = int(float(x['main_p']) // 5) * 5
                s = band.setdefault(b, [0, 0])
                s[1] += 1
                if x['actual'] == x['main']:
                    s[0] += 1
        fl = {}
        for x in flip:
            fl[x['actual']] = fl.get(x['actual'], 0) + 1
        _bj_ana._cache = {'tot': tot, 'draw': draw_n, 'flip': len(flip), 'fl': fl,
                          'lg': lg_d, 'band': band}
    c = _bj_ana._cache
    parts = []
    parts.append('【定价】SP %.2f/%.2f/%.2f 去水后 主%.1f%% 平%.1f%% 客%.1f%%，主推 %s。'
                 % (sp[0], sp[1], sp[2], p[0], p[1], p[2], LB[best]))
    mp = p[best]
    b = int(mp // 5) * 5
    s = c['band'].get(b)
    if s and s[1] >= 8:
        hit = s[0] / s[1] * 100
        parts.append('【同档校准】%d-%d%% 档归档 %d 场命中 %.1f%%（差 %+.1f）。' % (b, b + 5, s[1], hit, hit - mp))
    else:
        parts.append('【同档校准】%d-%d%% 档归档不足 8 场，样本不足不评。' % (b, b + 5))
    if c['tot']:
        parts.append('【翻车形态】归档 %d 场主推未中 %d 场（%.1f%%），其中平局 %d、客胜 %d、主胜 %d；全样本平局率 %.1f%%。'
                     % (c['tot'], c['flip'], c['flip'] / c['tot'] * 100,
                        c['fl'].get('平局', 0), c['fl'].get('客胜', 0), c['fl'].get('主胜', 0),
                        c['draw'] / c['tot'] * 100))
    ls = c['lg'].get(lg)
    if ls and ls[1] >= 8:
        parts.append('【联赛平局特性】%s 归档 %d 场平局 %d 场（%.1f%%），本场模型平局 %.1f%%。'
                     % (lg, ls[1], ls[0], ls[0] / ls[1] * 100, p[1]))
    else:
        parts.append('【联赛平局特性】%s 归档样本不足 8 场，不给基准。' % (lg or '本场联赛'))
    # ⑧ 澳客三维情报：近况/交锋 + 伤停阵容 + 技术统计 + 积分战意
    #   数据来自 fetch_intel_okooo.py（/match/form.php、/match/game.php），零人工验证
    oi = (load('intel_okooo.json') or {}).get('bj:%s' % (m.get('no') or '')) or {}
    hv, av = oi.get('home') or {}, oi.get('away') or {}
    if hv or av:
        line = '【近况·澳客】'
        if hv:
            line += '%s 近10场 %d胜%d平%d负' % (m.get('h'), hv.get('w', 0), hv.get('d', 0), hv.get('l', 0))
            if hv.get('venue'):
                v = hv['venue']
                line += '（主场 %d胜%d平%d负）' % (v.get('w', 0), v.get('d', 0), v.get('l', 0))
            line += '；' if av else '。'
        if av:
            line += '%s 近10场 %d胜%d平%d负' % (m.get('a'), av.get('w', 0), av.get('d', 0), av.get('l', 0))
            if av.get('venue'):
                v = av['venue']
                line += '（客场 %d胜%d平%d负）' % (v.get('w', 0), v.get('d', 0), v.get('l', 0))
            line += '。'
        parts.append(line)
    if oi.get('h2h'):
        h2 = oi['h2h']
        sub = '【交锋】往绩主队 %d胜%d平%d负' % (h2.get('w', 0), h2.get('d', 0), h2.get('l', 0))
        sub += '（澳客统计，仅参考，不进模型）。'
        parts.append(sub)
    inj, val, body = oi.get('inj'), oi.get('value') or [], oi.get('body') or []
    if inj or val or body:
        t = '【伤停·阵容】伤停：%s。' % (inj or '未采集')
        if val:
            t += '身价 %s vs %s。' % (val[0], val[1] if len(val) > 1 else '—')
        if body:
            t += '平均身高/年龄 %s vs %s。' % (body[0], body[1] if len(body) > 1 else '—')
        parts.append(t)
    tek = oi.get('tech') or {}
    if tek:
        g_h, g_a = (tek.get('goal') or {}).get('home') or {}, (tek.get('goal') or {}).get('away') or {}
        l_h, l_a = (tek.get('loss') or {}).get('home') or {}, (tek.get('loss') or {}).get('away') or {}
        s_h, s_a = (tek.get('shot') or {}).get('home') or {}, (tek.get('shot') or {}).get('away') or {}
        p_h, p_a = (tek.get('poss') or {}).get('home') or {}, (tek.get('poss') or {}).get('away') or {}
        parts.append('【技术统计·澳客近20场】场均进球 %s / %s（主场 %s / 客场 %s），场均失球 %s / %s，'
                     '场均射门 %s / %s，控球 %s%% / %s%%。'
                     % (g_h.get('all'), g_a.get('all'), g_h.get('venue'), g_a.get('venue'),
                        l_h.get('all'), l_a.get('all'), s_h.get('all'), s_a.get('all'),
                        p_h.get('all'), p_a.get('all')))
    if hv.get('rank') and av.get('rank'):
        diff = abs(int(hv['rank']) - int(av['rank']))
        mood = ('两队位次接近，战意按常规主客场权重处理' if diff < 8
                else '位次差 %d 位，积分诉求不对等，弱侧抢分动机更强' % diff)
        parts.append('【积分·战意】积分榜第 %s 名（%s 分） vs 第 %s 名（%s 分）；%s。'
                     % (hv['rank'], hv.get('pts'), av['rank'], av.get('pts'), mood))
    if oi:
        parts.append('【情报缺口】500 数据页被 EdgeOne 拦（且需人工验证），已改用澳客同源页面，'
                     '伤停/阵容/技术/积分均已采集；名单未公布时页面写「无缺阵」，不补人名。')
    else:
        parts.append('【情报缺口】本场澳客未给到数据页（可能未开盘/已完赛），近况与阵容留空不编。')
    _rmap = load('retire_map.json') or {}
    _rn = []
    for _tn in (m.get('h'), m.get('a')):
        for _x in (_rmap.get(_tn) or [])[:2]:
            if _x not in _rn:
                _rn.append(_x)
    if _rn:
        parts.append('【退役·告别公告】%s（公开新闻，仅作背景）。' % '；'.join(_rn))
    # 爆冷指数（同竞彩口径）：赔率集中度/平局热/名次逆风
    _gap_p = mp - max([p[x] for x in range(3) if x != best])
    _cold = (30 if _gap_p < 12 else 0) + (25 if p[1] >= 27 else 0)
    _tag = '高' if _cold >= 60 else ('中' if _cold >= 35 else '低')
    parts.append('【爆冷提示】冷门指数 %d/100（%s）：与次选仅差 %.1f 个百分点；%s。'
                 % (_cold, _tag, _gap_p,
                    '北单返奖率低于竞彩，这种风险位别当胆' if _cold >= 60 else '按常规单选处理'))
    if p[1] >= 27:
        parts.append('【结论】和联赛常态比平局偏热，方向不稳；北单返奖率低，建议降低注量或整场放弃。')
    else:
        parts.append('【结论】主推 %s %.1f%%，按单场口径执行，不做长串。' % (LB[best], mp))
    return '\n'.join(parts)


def bj_today(limit=10):
    b = load('_bj_latest_full.json') or {}
    now = time.strftime('%Y-%m-%d %H:%M')
    rows = []
    for m in (b.get('matches') or []):
        if m.get('ft'):
            continue                       # 已完赛不列
        if (m.get('dt') or '') <= now:
            continue                       # 已开赛停售
        sp = m.get('o') or []
        if len(sp) != 3:
            continue
        p = devig(sp)
        best = max(range(3), key=lambda i: p[i])
        rows.append({'no': m.get('no'), 'lg': m.get('lg') or '',
                     'm': '%s vs %s' % (m.get('h'), m.get('a')),
                     'sp': [round(x, 2) for x in sp],
                     'h': round(p[0], 1), 'd': round(p[1], 1), 'a': round(p[2], 1),
                     'rec': LB[best], 'hcap': m.get('hcap') or 0,
                     'tm': m.get('tm'), 'fund': None, 'dt': m.get('dt'),
                     'ana': _bj_ana(m, [round(x, 2) for x in sp], p, best, m.get('lg') or '')})
    rows.sort(key=lambda x: x['dt'])
    return rows[:limit]


def make_combo():
    """当天竞彩 ≥4 场有赔率时，挑「概率乘积最大且理论赔率 2.4~4.5」的一注 2串1。"""
    f = load('full.json') or {}
    cand = []
    for m in (f.get('matches') or []):
        o, p = m.get('o') or [], m.get('p') or []
        if len(o) != 3 or len(p) != 3:
            continue
        i = max(range(3), key=lambda k: p[k])
        cand.append({'no': m.get('no') or m.get('num'), 'h': m.get('h'), 'a': m.get('a'),
                     'pick': LB[i], 'pick_i': i, 'odd': float(o[i]), 'p': float(p[i]),
                     'conf': max(0, int(round(p[i])) - 14)})
    if len(cand) < 2:
        return None
    best, bs = None, -1
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            a, b = cand[i], cand[j]
            prod = a['odd'] * b['odd']
            if not (2.2 <= prod <= 4.8):
                continue                   # 太低没意义、太高命中率太差
            sc = a['p'] * b['p']
            if sc > bs:
                bs, best = sc, (a, b, prod)
    if not best:
        return None
    a, b, prod = best
    return {'date': datetime.date.today().isoformat(), 'name': '2串1',
            'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
            'odd': round(prod, 2), 'pr': round(a['p'] * b['p'] / 10000, 4),
            'widened': False, 'legs': [dict(a, actual=None, hit=None),
                                      dict(b, actual=None, hit=None)],
            'result': 'pending', 'frozen': True}


def replace_var(html, name, value):
    """把 window.__NAME__ = <json>; 整体替换（模板里这两个是常量字面量）。"""
    pat = re.compile(r'window\.' + name + r'\s*=\s*(\[|\{).*?(\]|\})\s*;', re.S)
    m = pat.search(html)
    if not m:
        return html, False
    # 用平衡括号精确定位，避免 .*? 截短
    start = m.start(1)
    depth = 0
    i = start
    while i < len(html):
        c = html[i]
        if c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                i += 1
                break
        elif c == '"':
            i += 1
            while i < len(html) and html[i] != '"':
                if html[i] == '\\':
                    i += 1
                i += 1
        i += 1
    lit = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return html[:start] + lit + html[i:], True


def _ft_index():
    """赛果索引：(主,客) -> 比分 或 胜平负结论。

    三个当场数据文件（竞彩/北单/任九）之外，再加归档 _archive_done.json——
    历史注单（比如上周的 2串1）只在归档里有赛果，不把它接上，复盘永远是空的。
    """
    idx = {}
    for name in ('full.json', '_bj_latest_full.json', 'sfc_pick.json'):
        d = load(name) or {}
        ms = d.get('matches') if isinstance(d, dict) else d
        for m in (ms or []):
            ft = m.get('ft')
            if ft and m.get('h') and m.get('a'):
                idx[(m['h'], m['a'])] = ft
    # 逐日北单/任九历史文件（bj_2026MMDD.json、_sfc_result_*.json）里带真实比分，
    # 不并进来，隔天就只剩 null —— 这就是「2串1 永远不复盘」的直接原因。
    import glob as _g
    def _walk(o, out):
        if isinstance(o, list):
            for x in o:
                _walk(x, out)
        elif isinstance(o, dict):
            if o.get('h') and o.get('a'):
                out.append(o)
            for v in o.values():
                if isinstance(v, (list, dict)):
                    _walk(v, out)
    ri = load('results_index.json') or {}
    for r in (ri.get('rows') or []):
        if r.get('h') and r.get('a') and r.get('ft'):
            idx.setdefault((r['h'], r['a']), r['ft'])
    for f in sorted(_g.glob(os.path.join(DATA, 'bj_2026*.json')) +
                    _g.glob(os.path.join(DATA, '_sfc_result_*.json')) +
                    _g.glob(os.path.join(DATA, 'history', '*.json'))):
        try:
            ms = []
            _walk(json.load(io.open(f, encoding='utf-8')), ms)
        except Exception:
            continue
        for m in ms:
            ft = m.get('ft') or m.get('score') or m.get('real')
            if ft:
                idx.setdefault((m['h'], m['a']), ft)
    for x in (load('_archive_done.json') or []):
        if not (x.get('h') and x.get('a')):
            continue
        if x.get('ft') and str(x['ft']).count(':') + str(x['ft']).count('-') >= 1:
            idx.setdefault((x['h'], x['a']), x['ft'])
        elif x.get('actual'):
            idx.setdefault((x['h'], x['a']), 'RES:' + x['actual'])
    return idx


def _score_res(ft):
    try:
        h, a = [int(x) for x in str(ft).replace('-', ':').split(':')[:2]]
    except Exception:
        return None
    return '主胜' if h > a else ('客胜' if h < a else '平局')


def backfill_combo(hist):
    """2串1 复盘回填：每一腿按真实赛果判命中，整注命中/派奖/盈亏一起算回来。

    口径：赛果只认抓回来的真实比分（full/北单/任九三处同一场比赛互相回填），
    取不到就保持 null，不拿「差不多」去凑。
    """
    idx = _ft_index()
    filled = 0
    for d, rec in (hist or {}).items():
        hit_all, odd_all, missing = True, 1.0, False
        for leg in (rec.get('legs') or []):
            ft = idx.get((leg.get('h'), leg.get('a')))
            if not ft:
                for (h, a), v in idx.items():
                    if (leg.get('h') or '') and (leg['h'] in h or h in leg['h']):
                        if (leg.get('a') or '') and (leg['a'] in a or a in leg['a']):
                            ft = v
                            break
            if not ft:
                missing = True
                continue
            if isinstance(ft, str) and ft.startswith('RES:'):
                res = ft[4:]
            else:
                res = _score_res(ft)
            leg['ft'] = ft
            leg['actual'] = res
            leg['hit'] = bool(res == leg.get('pick'))
            if leg.get('odd'):
                odd_all *= float(leg['odd'])
            if not leg['hit']:
                hit_all = False
            filled += 1
        if not missing and rec.get('legs'):
            rec['hit'] = bool(hit_all)
            rec['odd_all'] = round(odd_all, 2)
            rec['payout'] = round(odd_all * 2, 2) if hit_all else 0.0      # 按 2 元一注算
            rec['profit'] = round((odd_all - 1) * 2, 2) if hit_all else -2.0
    return filled


def review_stat():
    """复盘统计：从归档真实赛果重算竞彩/北单方向命中率，替换页面写死的老快照。"""
    arch = load('_archive_done.json') or []
    def calc(rows):
        n = len([x for x in rows if x.get('actual')])
        dh = len([x for x in rows if x.get('actual') and x.get('main') and x['actual'] == x['main']])
        dt = len([x for x in rows if x.get('actual') and x.get('main')])
        return {'n': n, 'dirHit': dh, 'dirTotal': dt,
                'dirPct': round(dh / dt * 100, 1) if dt else 0.0}
    jc = [x for x in arch if str(x.get('kind') or '') in ('', 'jc', '竞彩')]
    bj = [x for x in arch if str(x.get('kind') or '') in ('bj', '北单')]
    out = {}
    if jc:
        out['jc'] = calc(jc)
    if bj:
        out['bj'] = calc(bj)
    return out


def main():
    if not os.path.isfile(PAGE):
        print('[fix_today] 缺 index.html，跳过')
        return 1
    html = io.open(PAGE, encoding='utf-8').read()
    now = time.strftime('%Y-%m-%d %H:%M:%S')

    jc = jc_today()
    bj = bj_today()
    if jc:
        html, ok1 = replace_var(html, '__JC_TODAY__', jc)
        # 说明文字也是写死的（"周二4场 + 周三2场"），且被拆成两段 JS 字符串，直接按原文替换
        html = html.replace("'周二4场 + 周三2场。<b>表推算</b>=62,325场赔率表；'+",
                            "'本期在售 '+JC.length+' 场（官方接口回读）。'+")
        html = html.replace("'<b>官方支持率</b>=体彩官网公布的资金占比，两者可互相验证。</div>'+",
                            "'<b>表推算</b>=赔率去水概率；<b>官方支持率</b>官方接口不提供，留「—」不编数。</div>'+")
        print('[fix_today] 今日竞彩重写 %d 场（%s）' % (len(jc), 'OK' if ok1 else '未找到变量'))
    else:
        print('[fix_today] 竞彩今天没有带赔率的场次，__JC_TODAY__ 保持原样')
    if bj:
        html, ok2 = replace_var(html, '__BJ_TODAY__', bj)
        print('[fix_today] 今日北单重写 %d 场（首场 %s）%s'
              % (len(bj), bj[0]['tm'], 'OK' if ok2 else '未找到变量'))
    else:
        print('[fix_today] 北单没有未开赛场次，__BJ_TODAY__ 保持原样')

    ts = re.search(r'window\.__TODAY_TS__\s*=\s*"([^"]*)"', html)
    if ts:
        html = html[:ts.start(1)] + now[:16] + html[ts.end(1):]

    combo = make_combo()
    hist = load('combo_history.json', {}) or {}
    if combo:
        if combo['date'] in hist:
            print('[fix_today] 今天已有 2串1 记录，按冻结口径不重算')
        else:
            hist[combo['date']] = combo
            with io.open(os.path.join(DATA, 'combo_history.json'), 'w', encoding='utf-8') as f:
                json.dump(hist, f, ensure_ascii=False, indent=1)
            print('[fix_today] 生成 2串1：%s × %s · 理论赔率 %.2f · 命中概率 %.1f%%'
                  % (combo['legs'][0]['no'], combo['legs'][1]['no'],
                     combo['odd'], combo['pr'] * 100))
    # ★ 2串1 复盘回填：原来这里只「冻结不重算」，赛果永远不写回，
    #   页面上的旧串关就一直挂着 actual=null —— 现在每轮都按真实比分回填
    _bf = backfill_combo(hist)
    if _bf:
        with io.open(os.path.join(DATA, 'combo_history.json'), 'w', encoding='utf-8') as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
        print('[fix_today] 2串1 复盘回填 %d 腿（含历史注单）' % _bf)
    html, ok3 = replace_var(html, '__COMBO_HISTORY__', hist)
    if not ok3:
        print('[fix_today] 未找到 __COMBO_HISTORY__')

    # 任九页头：模板里 <span id="sfcIssueTxt"> 写死的是旧期（2026-09-20 · 第 26131 期），
    # 页面 JS 虽然会用 SFC._期次 覆盖，但用户先看到的就是这行旧文案 —— 直接按当期改写。
    sp = load('sfc_pick.json') or []
    if sp:
        iss = sp[0].get('issue') or ''
        dts = sorted({x.get('date') for x in sp if x.get('date')})
        rng = ('%s-%s' % (dts[0][5:], dts[-1][5:])) if dts else ''
        head = ('%s · 第 %s 期 · 胜负彩 14 场选 9 场' % (rng or dts[0] if dts else '', iss))
        m2 = re.search(r'(<span id="sfcIssueTxt">)([^<]*)(</span>)', html)
        if m2 and iss:
            html = html[:m2.start(2)] + head + html[m2.end(2):]
            print('[fix_today] 任九页头改写为 第 %s 期' % iss)

    tmp = PAGE + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    os.replace(tmp, PAGE)
    print('[fix_today] 页面已更新 %d B' % len(html.encode('utf-8')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
