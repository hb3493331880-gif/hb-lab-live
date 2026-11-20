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
    _cmap = load('coach_map.json') or {}
    _cm = []
    for _tn in (m.get('h'), m.get('a')):
        for _x in (_cmap.get(_tn) or [])[:2]:
            _line = '%s：%s' % (_tn, _x)
            if _line not in _cm:
                _cm.append(_line)
    if _cm:
        parts.append('【帅位变动】%s。换帅/下课传闻期球员更搏命但战术连续性差，'
                     '按战意不确定处理，不因低水加胆。' % '；'.join(_cm))
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


def _batch_tag(c):
    """销售日批次标识：取第一条腿的比赛编号里的星期字（周日/周一…）。"""
    legs = c.get('legs') or []
    if not legs:
        return ''
    no = legs[0].get('no') or ''
    return no[1:2] if no[:1] == '周' else ''


def combo_should_replace(cur, new):
    """旧注单该不该被今天的新注单替换。

    只冻结「同一批销售日」的注单：批次一变（周日→周一）就必须出新票，
    否则页面永远停在上一批（用户看到"今日不推、只回显 11-16 定稿"）。
    """
    if not cur:
        return True
    if _batch_tag(cur) != _batch_tag(new):
        return True
    legs = cur.get('legs') or []
    return bool(legs) and all(l.get('actual') for l in legs)


def _diverge_rows(html):
    m = re.search(r'window\.__R9_DIV__\s*=\s*(\{.*?\})\s*;\s*</script>', html, re.S)
    if not m:
        return []
    try:
        return (json.loads(m.group(1)) or {}).get('rows') or []
    except Exception:
        return []


def _norm_team(s):
    if not s:
        return ''
    return re.sub(r'[^\u4e00-\u9fa5A-Za-z]', '', str(s))


def _same_team(a, b):
    a, b = _norm_team(a), _norm_team(b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and (short in long or long in short)


def _backfill_div_results(html, current_issue=''):
    """用「竞彩赛果公告」把背离表/历史整理的赛果自动回填（每期都跑）。

    只填 real 为空的旧期；当期未开赛的不动。回填后重算各档命中率与总量。
    """
    res = load('results_all.json') or []
    if not res:
        return html
    d, s, e = _json_var(html, '__R9_DIV__')
    if not isinstance(d, dict):
        return html
    rows = d.get('rows') or []
    filled = 0
    for r in rows:
        if r.get('real') or str(r.get('issue')) == str(current_issue):
            continue
        for x in res:
            if _same_team(r.get('h'), x.get('h')) and _same_team(r.get('a'), x.get('a')):
                r['ft'] = x.get('ft')
                r['real'] = x.get('dir')
                r['hit'] = (r.get('main') == r.get('real')) if r.get('main') else None
                filled += 1
                break
    if not filled:
        return html
    bands = {}
    n_done = hit = 0
    for r in rows:
        if not r.get('real'):
            continue
        n_done += 1
        if r.get('hit'):
            hit += 1
        b = r.get('band') or '未分档'
        t = bands.setdefault(b, {'n': 0, '主胜': 0, '平局': 0, '客胜': 0, 'hit': 0})
        t['n'] += 1
        if r['real'] in ('主胜', '平局', '客胜'):
            t[r['real']] += 1
        if r.get('hit'):
            t['hit'] += 1
    d['bands'] = {k: v for k, v in bands.items() if k in ('一致', '差1-2位', '差3-5位', '差6-9位', '差10位以上')}
    d['n'] = len(rows)
    d['n_done'] = n_done
    d['hit'] = hit
    out = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
    html = html[:s] + out + html[e:]
    print('[fix_today] 赛果回填 %d 场（累计已开赛 %d / 主推命中 %d）' % (filled, n_done, hit))
    # 同步 results_index.json（卡片/复盘读取的赛果索引）
    try:
        idx = load('results_index.json') or {}
        have = {(x.get('h'), x.get('a'), x.get('ft')) for x in (idx.get('rows') or [])}
        add = 0
        for x in res:
            k = (x.get('h'), x.get('a'), x.get('ft'))
            if k not in have and x.get('ft'):
                have.add(k)
                add += 1
        merged = (idx.get('rows') or []) + [{'date': x.get('date'), 'h': x.get('h'), 'a': x.get('a'), 'ft': x.get('ft')}
                                            for x in res if (x.get('h'), x.get('a'), x.get('ft')) not in
                                            {(y.get('h'), y.get('a'), y.get('ft')) for y in (idx.get('rows') or [])}]
        if add:
            idx['rows'] = merged
            idx['updated'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with io.open(os.path.join(DATA, 'results_index.json'), 'w', encoding='utf-8') as f:
                json.dump(idx, f, ensure_ascii=False, indent=1)
            print('[fix_today] results_index 补充 %d 条赛果' % add)
    except Exception as ex:
        print('[fix_today] results_index 同步失败：%s' % ex)
    return html


def _merge_bj_mobile(html):
    """北单：用手机版列表 + 官方 WDL.xml 的最新报价，覆盖页面 __BJDC__ 的对应场次。

    官方是按场次陆续开价的，所以「未开价」不是抓取失败；这里只覆盖有价的场次，
    没价的保留原值（页面会显示「SP 未获取」并说明未开售）。
    """
    mob = load('bj_mobile.json')
    if isinstance(mob, dict):
        mob = mob.get('matches') or mob.get('rows') or []
    if not mob:
        return html
    d, s, e = _json_var(html, '__BJDC__')
    if not isinstance(d, dict):
        return html
    matches = d.get('matches') or []
    if not matches:
        return html
    fixed = 0
    for m in matches:
        no = str(m.get('no') or '').lstrip('0')
        for x in mob:
            if str(x.get('no') or '').lstrip('0') != no:
                continue
            if x.get('sp'):
                old_sp = m.get('sp') or []
                m['sp'] = [float(v) for v in x['sp']]
                m['o'] = list(m['sp'])
                # 定价文案同步刷新，避免「SP 已是新价、分析还写旧价」
                ana = str(m.get('ana') or '')
                if '【定价】SP ' in ana and old_sp:
                    new = '/'.join('%.2f' % v for v in m['sp'])
                    ana = re.sub(r'【定价】SP [\d.]+/[\d.]+/[\d.]+', '【定价】SP ' + new, ana, count=1)
                    m['ana'] = ana
                fixed += 1
            if x.get('rq') not in (None, ''):
                try:
                    m['hcap'] = int(x['rq'])
                except (TypeError, ValueError):
                    pass
            if x.get('h'):
                m.setdefault('hName', x['h'])
                m.setdefault('aName', x['a'])
            break
    if not fixed:
        return html
    out = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
    print('[fix_today] 北单 SP 刷新 %d 场（手机版+WDL 报价）' % fixed)
    return html[:s] + out + html[e:]


def _apply_odds_delta(html):
    """竞彩：把「初盘→现盘」的变盘解读写进每场分析开头。

    盘口只做解读与风险提示，不改方向的权重（与校准口径一致：方向翻转必须有硬条件）。
    """
    dd = load('odds_delta.json') or {}
    ms = dd.get('matches') or []
    if not ms:
        return html
    d, s, e = _json_var(html, '__LIVE__')
    if not isinstance(d, dict):
        return html
    by_no = {x.get('no'): x for x in ms}
    added = 0
    for m in d.get('matches') or []:
        x = by_no.get(m.get('no'))
        if not x:
            clean = str(m.get('no') or '').strip()
            x = by_no.get(clean.lstrip('周一二三四五六日'))
        if not x:
            for y in ms:
                if _same_team(m.get('h'), y.get('h')) and _same_team(m.get('a'), y.get('a')):
                    x = y
                    break
        if not x:
            continue
        first, last, p = x.get('first'), x.get('last'), x.get('pct') or [0, 0, 0]
        # 首轮：历史还没积累时，用页面里的「o」（开盘价）当初盘，别把现盘当基准糊弄人
        o = m.get('o') or []
        try:
            o = [float(v) for v in o]
        except (TypeError, ValueError):
            o = []
        if x.get('moves', 0) == 0 and len(o) == 3 and all(v > 1.01 for v in o) and o != list(last or []):
            first = o
            p = [round((b - a) / a * 100.0, 1) if a else 0.0 for a, b in zip(first, last)]
        tag = x.get('tag') or ''
        if x.get('moves', 0) == 0 and first == o and o:
            mx = max(abs(v) for v in p)
            if mx < 1.5:
                tag = '盘口稳定'
            elif p[0] <= -1.5 and p[2] >= 1.5:
                tag = '资金压主'
            elif p[2] <= -1.5 and p[0] >= 1.5:
                tag = '资金压客'
            elif p[1] <= -1.5 and abs(p[0]) < 1.5 and abs(p[2]) < 1.5:
                tag = '资金博平'
            else:
                tag = '分歧调整'
        main = m.get('main') or ''
        txt = '【变盘】初盘 %s → 现盘 %s（主 %+.1f%% / 平 %+.1f%% / 客 %+.1f%%），%d 次调整｜%s' % (
            '/'.join('%.2f' % v for v in first), '/'.join('%.2f' % v for v in last),
            p[0], p[1], p[2], x.get('moves', 0), tag)
        if tag == '资金压主':
            txt += '；' + ('与主推「主胜」同向，盘口给支撑' if main == '主胜'
                           else '与主推「%s」反向，盘口在压主，留意' % main)
        elif tag == '资金压客':
            txt += '；' + ('与主推「客胜」同向，盘口给支撑' if main == '客胜'
                           else '与主推「%s」反向，盘口在压客，留意' % main)
        elif tag == '资金博平':
            txt += '；主客两端没动、平局在降，市场在博平，主推「%s」风险来自闷平' % main
        elif tag == '盘口稳定':
            txt += '；盘口基本没动，维持原判断'
        else:
            txt += '；两端同时调整，方向未定，按原判断更稳'
        ana = str(m.get('ana') or '')
        ana = ana.replace('\n【变盘】', '\n') if '【变盘】' in ana else ana
        # ★ 变盘进决策（用户已确认开启）：与主推反向且幅度 ≥5% → 把握度 −2pp 并标存疑
        adj = 0
        main_idx = {'主胜': 0, '平局': 1, '客胜': 2}.get(main)
        if main_idx is not None and len(p) == 3:
            mp = p[main_idx]
            if mp >= 5.0:
                adj = -2.0
            elif mp <= -5.0:
                adj = +1.0
        if adj:
            base = m.get('main_p')
            try:
                base = float(base)
            except (TypeError, ValueError):
                base = None
            if base is not None:
                m['main_p'] = round(max(1.0, base + adj), 1)
                m['conf'] = m['main_p']
                txt += '｜变盘计入：把握度 %.1f%% → %.1f%%（%s，与主推反向 %+.1f%%）' % (
                    base, m['main_p'], '变盘反向扣减' if adj < 0 else '变盘同向加成', mp)
            else:
                txt += '｜变盘与主推%s %+.1f%%，方向存疑' % ('反向' if adj < 0 else '同向', mp)
        m['ana'] = txt + '\n' + ana
        added += 1
    if added:
        out = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        print('[fix_today] 竞彩变盘解读 %d 场' % added)
        return html[:s] + out + html[e:]
    return html


def _archive_picks(html):
    """把当期三彩种的推荐意见存档，供后续「复盘回填」用。

    只存推什么、概率多少；有赛果之后由 _backfill_review 判命中并写复盘结论。
    """
    his = load('picks_history.json') or {'rows': []}
    rows = his.get('rows') or []
    key = {(str(r.get('date')), str(r.get('no')), str(r.get('h'))) for r in rows}
    added = 0
    for var, kind in (('__LIVE__', '竞彩'), ('__BJDC__', '北单')):
        d, s, e = _json_var(html, var)
        if not isinstance(d, dict):
            continue
        for m in d.get('matches') or []:
            p = m.get('p') or m.get('fund') or []
            rec_no = str(m.get('no'))
            dt = str(m.get('date') or m.get('sd') or '')[:10]
            k = (dt, rec_no, str(m.get('h')))
            if k in key or not m.get('main'):
                continue
            key.add(k)
            rows.append({'date': dt, 'no': rec_no, 'kind': kind, 'lg': m.get('lg'),
                         'h': m.get('h'), 'a': m.get('a'), 'main': m.get('main'),
                         'main_p': m.get('main_p') or m.get('conf'), 'p': p})
            added += 1
    if added:
        his['rows'] = rows
        his['updated'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with io.open(os.path.join(DATA, 'picks_history.json'), 'w', encoding='utf-8') as f:
            json.dump(his, f, ensure_ascii=False, separators=(',', ':'))
        print('[fix_today] 推荐存档 %d 场（累计 %d）' % (added, len(rows)))
    return html


def _backfill_review(html):
    """复盘回填：推荐存档 × 本次抓到的赛果 → 判命中、写原因，并注入复盘表。"""
    his = load('picks_history.json') or {}
    res = load('results_all.json') or []
    rows = his.get('rows') or []
    if not rows or not res:
        return html
    rev = load('review_auto.json') or {'rows': []}
    done = {(str(r.get('h')), str(r.get('a')), str(r.get('date'))) for r in rev.get('rows') or []}
    new = []
    for r in rows:
        if (str(r.get('h')), str(r.get('a')), str(r.get('date'))) in done:
            continue
        for x in res:
            if not (x.get('ft') and x.get('dir')):
                continue
            if _same_team(r.get('h'), x.get('h')) and _same_team(r.get('a'), x.get('a')):
                hit = (r.get('main') == x['dir'])
                p = r.get('p') or []
                idx = {'主胜': 0, '平局': 1, '客胜': 2}.get(x['dir'])
                act_p = p[idx] if (len(p) == 3 and idx is not None) else None
                if hit:
                    note = '命中：推「%s」%s%%，概率最高，赛果 %s' % (
                        r['main'], r.get('main_p'), x['ft'])
                else:
                    note = '未命中：推「%s」%s%%，实际「%s」（%s）' % (
                        r['main'], r.get('main_p'), x['dir'], x['ft'])
                    if act_p is not None:
                        note += '；模型给「%s」仅 %s%%，差 %.1f 个百分点' % (x['dir'], act_p,
                                                                 (r.get('main_p') or 0) - act_p)
                new.append({'date': str(r.get('date')), 'no': r.get('no'), 'lg': r.get('lg'),
                            'h': r.get('h'), 'a': r.get('a'), 'main': r.get('main'),
                            'main_p': r.get('main_p'), 'ft': x['ft'], 'result': x['dir'],
                            'dirHit': hit, 'note': note, 'kind': r.get('kind'),
                            'src': '赛果公告自动回填'})
                break
    if not new:
        return html
    rev['rows'] = (rev.get('rows') or []) + new
    rev['updated'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with io.open(os.path.join(DATA, 'review_auto.json'), 'w', encoding='utf-8') as f:
        json.dump(rev, f, ensure_ascii=False, separators=(',', ':'))
    # 注入页面复盘表
    d, s, e = _json_var(html, '__BJ_REVIEW__')
    if isinstance(d, dict):
        rs = d.get('rows') or []
        seen = {(str(x.get('h')), str(x.get('a')), str(x.get('date'))) for x in rs}
        add = []
        for r in new:
            k = (str(r.get('h')), str(r.get('a')), str(r.get('date')))
            if k not in seen:
                seen.add(k)
                add.append(r)
        if add:
            d['rows'] = add + rs
            d['updated'] = rev['updated']
            hit_n = sum(1 for x in d['rows'] if x.get('dirHit'))
            d.setdefault('stat', {})
            d['stat']['rows'] = len(d['rows'])
            d['stat']['hit'] = hit_n
            html = html[:s] + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + html[e:]
    print('[fix_today] 复盘回填 %d 场（累计 %d）' % (len(new), len(rev['rows'])))
    return html


def _inject_bj_today(html):
    """给北单 tab 注入 window.__BJ_TODAY__（手机版列表 + 官方 WDL 最新报价）。

    页面北单表原来读模板里写死的旧批次（396-402），这里换成当期实时数据。
    """
    d, s, e = _json_var(html, '__BJDC__')
    if not isinstance(d, dict) or not (d.get('matches')):
        return html
    idx = {'主胜': 0, '平局': 1, '客胜': 2}
    out = []
    for m in d.get('matches') or []:
        sp = m.get('sp') or []
        if len(sp) != 3 or any((not v) or v <= 1.01 for v in sp):
            sp = []
        fund = m.get('fund') or m.get('mp') or []
        if len(fund) != 3:
            fund = []
        out.append({'no': m.get('no'), 'm': '%s vs %s' % (m.get('h'), m.get('a')),
                    'sp': ['%.2f' % v for v in sp] if sp else [],
                    'h': int(fund[0]) if fund else 0,
                    'd': int(fund[1]) if fund else 0,
                    'a': int(fund[2]) if fund else 0})
    if not out:
        return html
    blob = '<script>window.__BJ_TODAY__=%s;</script>\n' % json.dumps(out, ensure_ascii=False)
    anchor = '<script>window.__BJDC__='
    i = html.find(anchor)
    if i < 0:
        return html
    print('[fix_today] 北单表格切源：注入 %d 场实时数据' % len(out))
    return html[:i] + blob + html[i:]


def _band_hit_table():
    """从背离表算「概率分档真实命中率」，供竞彩/北单同档校准用。"""
    d = load('_r9_diverge.json') or {}
    rows = d.get('rows') or []
    t = {}
    for r in rows:
        if not r.get('real') or r.get('main_p') is None or r.get('hit') is None:
            continue
        try:
            mp = float(r.get('main_p'))
        except (TypeError, ValueError):
            continue
        lo = int(mp // 10 * 10)
        b = t.setdefault(lo, {'n': 0, 'hit': 0})
        b['n'] += 1
        b['hit'] += 1 if r.get('hit') else 0
    return {k: {'n': v['n'], 'p': v['hit'] / v['n'] * 100.0} for k, v in t.items()}


def _apply_calibration_multi(html):
    """把「同档历史命中」校准从任九扩到竞彩 11 场 + 北单在售场次。

    口径与任九一致：0.7×赔率去水 + 0.3×同档历史真实命中；同档样本 <10 不参与。
    """
    tab = _band_hit_table()
    if not tab:
        return html
    total = 0
    for var, pkey, pmode in (('__LIVE__', 'p', 'pct'), ('__BJDC__', 'fund', 'pct')):
        d, s, e = _json_var(html, var)
        if not isinstance(d, dict):
            continue
        hit = 0
        for m in d.get('matches') or []:
            p = m.get(pkey) or []
            main = m.get('main')
            idx = {'主胜': 0, '平局': 1, '客胜': 2}.get(main)
            if idx is None or len(p) != 3:
                continue
            try:
                raw = float(p[idx])
            except (TypeError, ValueError):
                continue
            b = tab.get(int(raw // 10 * 10))
            if not b or b['n'] < 10:
                continue
            cal = round(0.7 * raw + 0.3 * b['p'], 1)
            old = m.get('main_p') or m.get('conf')
            m['main_p'] = cal
            m['conf'] = cal
            m['calib'] = {'raw': round(raw, 1), 'n': b['n'], 'band_p': round(b['p'], 1)}
            ana = str(m.get('ana') or '')
            if '【同档校准·已开】' not in ana:
                m['ana'] = ('【同档校准·已开】赔率去水 %.1f%% → 校准 %.1f%%'
                            '（0.7×赔率 + 0.3×同档历史；同档 %d 场命中 %.1f%%）\n' % (
                                raw, cal, b['n'], b['p'])) + ana
            hit += 1
        if hit:
            total += hit
            html = html[:s] + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + html[e:]
    if total:
        print('[fix_today] 竞彩/北单同档校准 %d 场（任九 14 场另算）' % total)
    return html


def _merge_jc_okooo(html):
    """竞彩：用云端抓到的澳客 SP（jc_okooo_page.json）覆盖页面赔率。

    云端 Actions 上体彩官方接口 567，只有澳客能抓；这里按队名对齐覆盖，
    保证「关机也更新」时竞彩赔率不是死的。
    """
    src = load('jc_okooo_page.json') or {}
    ms = src.get('matches') or []
    d, s, e = _json_var(html, '__LIVE__')
    if not isinstance(d, dict) or not ms:
        return html
    up = 0
    for m in d.get('matches') or []:
        for x in ms:
            sp = x.get('sp') or []
            if len(sp) != 3 or any((not v) or v <= 1.01 for v in sp):
                continue
            if not (_same_team(m.get('h'), x.get('h')) and _same_team(m.get('a'), x.get('a'))):
                continue
            new = [round(float(v), 2) for v in sp]
            if [round(float(v), 2) for v in (m.get('sp') or m.get('odds') or [])] != new:
                m['sp'] = new
                m['odds'] = list(new)
                m['src'] = '澳客（云端抓取）'
                up += 1
            break
    if up:
        html = html[:s] + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + html[e:]
        print('[fix_today] 竞彩赔率云端覆盖 %d 场' % up)
    return html


def _backfill_combo_all(html):
    """2串1 全量回填：每条腿按赛果判命中 → 整注 win/lose + 派奖；不再只回填有票的几天。"""
    res = load('results_all.json') or []
    if not res:
        return html
    d, s, e = _json_var(html, '__COMBO_HISTORY__')
    if not isinstance(d, dict):
        return html
    legs_fixed = 0
    for dt, batch in d.items():
        legs = batch.get('legs') or []
        for lg in legs:
            if lg.get('actual'):
                continue
            for x in res:
                if not (x.get('ft') and x.get('dir')):
                    continue
                if _same_team(lg.get('h'), x.get('h')) and _same_team(lg.get('a'), x.get('a')):
                    lg['actual'] = x['dir']
                    lg['ft'] = x['ft']
                    lg['hit'] = (lg.get('pick') == x['dir'])
                    legs_fixed += 1
                    break
        if all(l.get('actual') for l in legs) and legs:
            win = all(bool(l.get('hit')) for l in legs)
            batch['result'] = 'win' if win else 'lose'
            try:
                batch['payout'] = round(float(batch.get('odd') or 0) * 2, 2) if win else 0
            except (TypeError, ValueError):
                pass
    if legs_fixed:
        html = html[:s] + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + html[e:]
        wins = sum(1 for b in d.values() if b.get('result') == 'win')
        print('[fix_today] 2串1 回填 %d 条腿（%d 批已定论，盈利 %d 批）' % (legs_fixed, len(d), wins))
    return html


def _apply_intel_factors(html):
    """8 因子里「近况 / 交锋 / 进失球」进数值（竞彩有 intel500 数据时）。

    口径：只做有界修正（合计 ±3），任九那边仍按原 3 因子 ±5 的口径，不重复扣。
    """
    intel = load('intel500.json') or {}
    if not isinstance(intel, dict) or not intel:
        return html
    d, s, e = _json_var(html, '__LIVE__')
    if not isinstance(d, dict):
        return html
    hits = 0
    for m in d.get('matches') or []:
        x = intel.get(m.get('no'))
        if not isinstance(x, dict):
            for k, v in intel.items():
                if _same_team(m.get('h'), v.get('pair500', '').split(' vs ')[0]) and \
                        _same_team(m.get('a'), v.get('pair500', ' vs ')[-1]):
                    x = v
                    break
        if not isinstance(x, dict):
            continue
        hw = (x.get('home') or {}).get('win_pct')
        aw = (x.get('away') or {}).get('win_pct')
        if hw is None or aw is None:
            continue
        main = m.get('main')
        adj = 0.0
        why = []
        dw = float(hw) - float(aw)
        # 近况（胜率差 ≥20pp）
        if abs(dw) >= 20:
            step = 1.0 if (main == '主胜' and dw > 0) or (main == '客胜' and dw < 0) else -1.0
            adj += step
            why.append('近况胜率 主%.0f%%/客%.0f%%（差 %+.0fpp）%+.1f' % (hw, aw, dw, step))
        # 进失球差
        hg = ((x.get('home_avg') or {}).get('gf') or [0])[0]
        ha = ((x.get('home_avg') or {}).get('ga') or [0])[0]
        ag = ((x.get('away_avg') or {}).get('gf') or [0])[0]
        aa = ((x.get('away_avg') or {}).get('ga') or [0])[0]
        try:
            dgd = (float(hg) - float(ha)) - (float(ag) - float(aa))
            if abs(dgd) >= 0.4:
                step = 0.8 if (main == '主胜' and dgd > 0) or (main == '客胜' and dgd < 0) else -0.8
                adj += step
                why.append('场均净胜差 %+.2f（主 %.2f/客 %.2f）%+.1f' % (dgd, float(hg) - float(ha),
                                                                      float(ag) - float(aa), step))
        except (TypeError, ValueError):
            pass
        # 交锋
        rec = str(x.get('h2h_rec') or '')
        mm = re.match(r'(\d+)胜(\d+)和(\d+)负', rec)
        if mm:
            w, dd, l = (int(v) for v in mm.groups())
            if main == '主胜' and w > l:
                adj += 0.8
                why.append('交锋 %d胜%d和%d负 利主 %+.1f' % (w, dd, l, 0.8))
            elif main == '客胜' and l > w:
                adj += 0.8
                why.append('交锋 %d胜%d和%d负 利客 %+.1f' % (w, dd, l, 0.8))
            elif main == '主胜' and l > w:
                adj -= 0.8
                why.append('交锋 %d胜%d和%d负 不利主 %+.1f' % (w, dd, l, -0.8))
            elif main == '客胜' and w > l:
                adj -= 0.8
                why.append('交锋 %d胜%d和%d负 不利客 %+.1f' % (w, dd, l, -0.8))
        if not why:
            continue
        adj = max(-3.0, min(3.0, adj))
        base = m.get('main_p')
        try:
            base = float(base)
        except (TypeError, ValueError):
            continue
        m['main_p'] = round(base + adj, 1)
        m['conf'] = m['main_p']
        note = '【数据因子·进数值】' + '；'.join(why) + '｜合计 %+.1f（封顶 ±3）→ 把握度 %.1f%% → %.1f%%' % (
            adj, base, m['main_p'])
        ana = str(m.get('ana') or '')
        if '【数据因子·进数值】' not in ana:
            m['ana'] = note + '\n' + ana
        hits += 1
    if hits:
        html = html[:s] + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + html[e:]
        print('[fix_today] 近况/交锋/净胜球 因子进数值 %d 场' % hits)
    return html


def _r9_ctx():
    """从 _r9_diverge.json 取「名次差分档」与「联赛平局率」两套历史统计。"""
    d = load('_r9_diverge.json') or {}
    bands = d.get('bands') or {}
    rows = d.get('rows') or []
    lgd, alln, alld = {}, 0, 0
    for r in rows:
        lg = str(r.get('lg') or '')
        lgd.setdefault(lg, [0, 0])
        lgd[lg][0] += 1
        alln += 1
        if r.get('real') == '平局':
            lgd[lg][1] += 1
            alld += 1
    league = {k: (v[0], round(v[1] * 100.0 / v[0], 1)) for k, v in lgd.items() if v[0] >= 8}
    return bands, league, (alln, round(alld * 100.0 / alln, 1) if alln else 0)


def _band_of(gap):
    g = abs(int(gap or 0))
    if g <= 0:
        return '一致'
    if g <= 2:
        return '差1-2位'
    if g <= 5:
        return '差3-5位'
    if g <= 9:
        return '差6-9位'
    return '差10位以上'


def _enrich_sfc_ana(html):
    """任九 14 场分析加厚（14/14 全覆盖，全部用已有数据算，不编造）：

    ① 【定价明细】欧赔 → 去水三项概率、主推/次选差、单选还是双选；
    ② 【欧赔变盘】初盘 → 现盘 + 变盘标签（sfc_delta.json，无二次报价就明说）；
    ③ 【名次同档】位次差 → 历史分档的 主/平/客 分布与命中率（_r9_diverge.json）；
    ④ 【平局风险】本场平局率 vs 该联赛历史平局率 vs 全样本；
    ⑤ 【竞足同场】把当日竞足同场那一路的完整分析逐条并进来。
    """
    sd = load('sfc_delta.json') or {}
    by_no = {str(x.get('no')): x for x in (sd.get('matches') or [])}
    bands, league, (alln, alld) = _r9_ctx()
    # 页面 JSON 不含排名，回 sfc_pick.json 取（键=场次号）
    rk = {}
    for r in (load('sfc_pick.json') or []):
        if isinstance(r, dict):
            rk[str(r.get('no'))] = (r.get('hrank'), r.get('arank'), r.get('lg'))
    live_d, _, _ = _json_var(html, '__LIVE__')
    live = (live_d.get('matches') or []) if isinstance(live_d, dict) else []
    data, s, e = _json_var(html, '__SFC_NOW__')
    if data is None:
        return html
    rows = data if isinstance(data, list) else (data.get('matches') or [])
    touched = 0
    for it in rows:
        if not isinstance(it, dict):
            continue
        ana = str(it.get('ana') or '')
        if '【加厚·定价明细】' in ana:
            continue
        parts = []
        odds = it.get('odds') or []
        p = it.get('p') or it.get('fus') or []
        # ① 定价明细
        if len(odds) >= 3 and len(p) >= 3:
            parts.append('【加厚·定价明细】欧赔 %s/%s/%s → 去水 主 %.1f%% / 平 %.1f%% / 客 %.1f%%；'
                         '主推 %s %.1f%%，次选 %s %.1f%%（相差 %.1f 个百分点，%s）'
                         % ('%.2f' % odds[0], '%.2f' % odds[1], '%.2f' % odds[2],
                            p[0], p[1], p[2], it.get('main'), float(it.get('main_p') or p[0]),
                            it.get('alt'), float(it.get('alt_p') or 0), float(it.get('gap') or 0),
                            '可单押' if float(it.get('gap') or 0) >= 15 else ('建议带双选' if float(it.get('gap') or 0) >= 8 else '必须双选兜住')))
        # ② 欧赔变盘
        x = by_no.get(str(it.get('no')))
        if x and (x.get('first') or x.get('last')):
            first = '/'.join('%.2f' % v for v in (x.get('first') or []))
            last = '/'.join('%.2f' % v for v in (x.get('last') or []))
            pp = x.get('pct') or [0, 0, 0]
            parts.append('【加厚·欧赔变盘】初盘 %s → 现盘 %s（主 %+.1f%% / 平 %+.1f%% / 客 %+.1f%%），%d 次调整｜%s'
                         % (first, last, pp[0], pp[1], pp[2], int(x.get('moves') or 0), x.get('tag') or '—'))
        elif odds:
            parts.append('【加厚·欧赔变盘】本场暂时只有一版报价（%s），无二次调整记录，'
                         '方向以初盘定价为准' % '/'.join('%.2f' % v for v in odds))
        # ③ 名次同档
        try:
            hr, ar, plg = rk.get(str(it.get('no')), (it.get('hrank'), it.get('arank'), it.get('lg')))
            hr, ar = int(hr or 0), int(ar or 0)
            if hr and ar:
                gap = hr - ar
                bd = _band_of(gap)
                b = bands.get(bd) or {}
                if b.get('n'):
                    n = b['n']
                    parts.append('【加厚·名次同档】%s 第%d vs %s 第%d（位次差 %d）→「%s」档历史 %d 场：'
                                 '主 %.0f%% / 平 %.0f%% / 客 %.0f%%，该档主推命中 %.0f%%%s'
                                 % (it.get('h'), hr, it.get('a'), ar, abs(gap), bd, n,
                                    100.0 * b.get('主胜', 0) / n, 100.0 * b.get('平局', 0) / n,
                                    100.0 * b.get('客胜', 0) / n, 100.0 * b.get('hit', 0) / n,
                                    '' if n >= 10 else '（样本不足 10，仅作参考）'))
        except (TypeError, ValueError):
            pass
        # ④ 平局风险
        try:
            dp = float(it.get('draw_p') or p[1])
            lgname = str(it.get('lg') or '')
            lgn, lgd = league.get(lgname, (0, None))
            ref = ('%s 历史平局率 %.1f%%（%d 场）' % (lgname, lgd, lgn)) if lgd else \
                  ('%s 归档不足 8 场，改看全样本' % lgname)
            verdict = ('低于参照，平局可少带' if dp < (lgd or alld) - 3 else
                       ('高于参照，平局要防' if dp > (lgd or alld) + 3 else '与参照接近，属常规风险'))
            parts.append('【加厚·平局风险】本场平局 %.1f%%；%s；全样本 %.1f%% → %s%s'
                         % (dp, ref, alld, verdict,
                            '，本期平局候选标记为真' if it.get('draw_cand') and dp > (lgd or alld) else ''))
        except (TypeError, ValueError):
            pass
        # ⑤ 竞足同场（整段并进来）
        peer = None
        for m in live:
            if _same_team(it.get('h'), m.get('h')) and _same_team(it.get('a'), m.get('a')):
                peer = m
                break
        if peer:
            pa = str(peer.get('ana') or '')
            lines = ['竞足编号 %s，挂「%s」%.1f%%' % (peer.get('no'), peer.get('main'),
                                                float(peer.get('main_p') or 0))]
            for seg in [t for t in pa.split('\n') if t.strip()]:
                seg = seg.strip()
                if seg.startswith('【结论】'):
                    continue
                lines.append(seg)
            parts.append('【加厚·竞足同场·逐条并入】' + ' ／ '.join(lines))
        if parts:
            it['ana'] = '\n'.join(parts) + '\n' + ana
            touched += 1
    if touched:
        html = html[:s] + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + html[e:]
        print('[fix_today] 任九分析加厚 %d 场（定价/变盘/名次同档/平局风险/竞足同场）' % touched)
    return html


def _inject_refresh_button(html):
    """页面右下角「立即更新」按钮：点一下强刷到最新构建版本，并显示这版数据的构建时间。"""
    if 'id="hbRefreshBtn"' in html:
        return html
    stamp = __import__('datetime').datetime.now().strftime('%m-%d %H:%M')
    btn = (
        '<div id="hbRefreshBtn" style="position:fixed;right:10px;bottom:74px;z-index:99;'
        'display:flex;align-items:center;gap:6px;padding:7px 11px;border-radius:20px;'
        'background:#d33;color:#fff;font-size:11px;font-weight:700;'
        'box-shadow:0 3px 10px rgba(0,0,0,.35);cursor:pointer" '
        'onclick="(function(){var u=location.pathname+\'?v=\'+Date.now();'
        'location.replace(u);})()">'
        '<span>🔄 立即更新</span>'
        '<span style="font-weight:400;opacity:.85;font-size:10px">数据 %s</span></div>' % stamp
    )
    i = html.rfind('</body>')
    if i < 0:
        return html + btn
    return html[:i] + btn + html[i:]


def _json_var(html, name):
    """按括号配平取出 window.NAME = {...}/[...] 的值（正则非贪婪在多级嵌套上会截断）。"""
    k = html.find('window.' + name + '=')
    if k < 0:
        k = html.find('window.' + name + ' =')
    if k < 0:
        return None, None, None
    s = -1
    for i in range(k, len(html)):
        if html[i] in '[{':
            s = i
            break
    op = html[s]
    cl = ']' if op == '[' else '}'
    depth = 0
    i = s
    while i < len(html):
        c = html[i]
        if c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                break
        elif c == '"':
            i += 1
            while i < len(html) and html[i] != '"':
                if html[i] == '\\':
                    i += 1
                i += 1
        i += 1
    try:
        return json.loads(html[s:i + 1]), s, i + 1
    except Exception as e:
        print('[fix_today] %s 解析失败：%s' % (name, e))
        return None, s, i + 1


def _apply_calibration(html, rows=None, coach=None):
    """把「历史同档真实命中率 + 8 因子」真正算进显示概率（可选开关 __CALIB_ON__）。

    口径（写死在页面上，避免黑箱）：
      校准概率 = 0.7 × 赔率去水概率 + 0.3 × 同档历史真实命中率
      再叠加 8 因子有界修正（合计封顶 ±5 个百分点），逐项写明
    翻转保护：校准后次选反超主选 ≥ 3.0 个百分点才改方向，否则只改数值
    """
    try:
        rows = rows if rows is not None else _diverge_rows(html)
        if not rows:
            return html
        buckets = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 200)]
        stat = {b: {'n': 0, 'hit': 0} for b in buckets}
        for r in rows:
            if not r.get('real') or r.get('main_p') in (None, '') or not r.get('main'):
                continue
            mp = float(r['main_p'])
            bk = next((b for b in buckets if b[0] <= mp < b[1]), None)
            if not bk:
                continue
            stat[bk]['n'] += 1
            if r['real'] == r['main']:
                stat[bk]['hit'] += 1
        coach = coach if coach is not None else (load('coach_map.json') or {})

        data, s, e = _json_var(html, '__SFC_NOW__')
        if data is None:
            return html
        rows_obj = data if isinstance(data, list) else (data.get('matches') or [])
        for it in rows_obj:
            if not isinstance(it, dict):
                continue
            fus = it.get('fus') or []
            rec = it.get('rec')
            if len(fus) != 3 or rec not in ('主胜', '平局', '客胜'):
                continue
            idx = ['主胜', '平局', '客胜'].index(rec)
            raw = float(fus[idx])
            bk = next((b for b in buckets if b[0] <= raw < b[1]), None)
            st = stat.get(bk, {'n': 0, 'hit': 0})
            hist = (100.0 * st['hit'] / st['n']) if st['n'] >= 10 else None
            cal = 0.7 * raw + 0.3 * hist if hist is not None else raw
            notes = []
            if hist is not None:
                notes.append('档 %d-%d%%：历史同档 %d 场真实命中 %.1f%%' % (bk[0], bk[1], st['n'], hist))
            else:
                notes.append('档 %d-%d%%：历史同档仅 %d 场（<10，样本不足，不参与校准）' % (bk[0], bk[1], st['n']))
            # 8 因子（有界）
            adj = 0.0
            hr, ar = it.get('gap'), None
            try:
                hr, ar = int(it.get('hr') or 0), int(it.get('ar') or 0)
            except Exception:
                hr = ar = None
            if hr and ar:
                weak_home = hr > ar
                if rec == '主胜' and weak_home:
                    adj -= 2.0
                    notes.append('名次背离（主推名次弱势方）-2.0')
                elif rec == '客胜' and not weak_home:
                    adj -= 2.0
                    notes.append('名次背离（主推名次弱势方）-2.0')
            dp = float(fus[1])
            if dp >= 27:
                adj -= 1.5
                notes.append('平局率 %.1f%% ≥27%% -1.5' % dp)
            for side in (it.get('h'), it.get('a')):
                if side and (side in (coach or {})):
                    adj -= 1.5
                    notes.append('%s 帅位动荡 -1.5' % side)
                    break
            adj = max(-5.0, min(5.0, adj))
            cal = max(1.0, min(99.0, cal + adj))
            tot = sum(fus)
            scale = (100.0 - cal) / (tot - raw) if tot - raw > 0 else 1.0
            new = [f * scale for f in fus]
            new[idx] = cal
            # 翻转保护
            alt_i = max([i for i in range(3) if i != idx], key=lambda i: new[i])
            flipped = new[alt_i] - cal >= 3.0
            if flipped:
                notes.append('校准后 %s %.1f%% 反超主选 %.1f 个百分点 → 方向改为 %s'
                             % (['主胜', '平局', '客胜'][alt_i], new[alt_i], new[alt_i] - cal,
                                ['主胜', '平局', '客胜'][alt_i]))
                it['rec_pre_cal'] = rec
                it['rec'] = ['主胜', '平局', '客胜'][alt_i]
                idx = alt_i
            else:
                notes.append('未翻转（次选最高 %.1f%%，与主选差 %.1f）' % (new[alt_i], new[alt_i] - cal))
            it['fus_raw'] = fus
            it['fus'] = [round(x, 1) for x in new]
            it['conf'] = round(new[idx], 1)
            it['conf_raw'] = round(raw, 1)
            it['calib'] = {'on': True, 'hist': round(hist, 1) if hist is not None else None,
                           'n': st['n'], 'adj': round(adj, 1), 'flip': bool(flipped)}
            head = '【校准·已开启】原 %.1f%% → %.1f%%（0.7×赔率 + 0.3×同档历史；8因子 %+.1f）。%s。' % (
                it['conf_raw'], it['conf'], adj, '；'.join(notes))
            if not (it.get('ana') or '').startswith('【校准'):
                it['ana'] = head + (it.get('ana') or '')
        out = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        html2 = html[:s] + out + html[e:]
        print('[fix_today] 校准已开启：14 场按 0.7×赔率 + 0.3×同档历史 重算（8因子封顶 ±5）')
        return html2
    except Exception as e:
        print('[fix_today] 校准失败：%s' % e)
        return html


def _rebuild_cold(html, sp, rows=None):
    """爆冷风险雷达：必须用「当期 14 场」重算，否则标题是当期、卡片是上一期。

    翻车率口径沿用原雷达：按赛前主推概率分档，用已开赛的历史记录实算
    （(D).rows 里有 real + main + main_p 的场次）。
    """
    if not sp:
        return html
    if rows is None:
        rows = _diverge_rows(html)
    buckets = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 200)]
    stat = {b: {'n': 0, 'flop': 0} for b in buckets}
    for r in rows:
        if not r.get('real') or not r.get('main') or r.get('main_p') in (None, ''):
            continue
        mp = float(r['main_p'])
        bk = next((b for b in buckets if b[0] <= mp < b[1]), None)
        if not bk:
            continue
        stat[bk]['n'] += 1
        if r['real'] != r['main']:
            stat[bk]['flop'] += 1

    out = []
    for m in sp:
        o = m.get('o') or {}
        fus = m.get('fus') or []
        main = m.get('rec') or m.get('main') or ''
        if len(fus) != 3 or main not in ('主胜', '平局', '客胜'):
            continue
        mp = float(fus[['主胜', '平局', '客胜'].index(main)])
        dp = float(fus[1])
        bk = next((b for b in buckets if b[0] <= mp < b[1]), None)
        st = stat.get(bk, {'n': 0, 'flop': 0})
        base = (100.0 * st['flop'] / st['n']) if st['n'] else None
        hr, ar = m.get('hrank'), m.get('arank')
        div = 0.0
        if hr not in (None, '') and ar not in (None, ''):
            d = abs(int(hr) - int(ar))
            strong_is_home = int(hr) < int(ar)
            if (main == '主胜' and not strong_is_home) or (main == '客胜' and strong_is_home):
                div = round(d * 0.6, 1)
        score = (base if base is not None else 50.0) + max(0.0, dp - 24.0) * 0.8 + div
        lvl = '高' if score >= 55 else ('中' if score >= 45 else '低')
        ana = '🧊 爆冷风险 %s（%.1f）｜主推%s%.1f%%，处%d-%d%%档，历史同档%d场命中%s（翻车%s）。' % (
            lvl, score, main, mp, bk[0], bk[1], st['n'],
            ('%.1f%%' % (100 - base)) if base is not None else '暂无',
            ('%.1f%%' % base) if base is not None else '暂无')
        if hr not in (None, '') and ar not in (None, ''):
            ana += '主队%s第%s、客队第%s，%s。' % (
                m.get('lg') or '', hr, ar,
                '市场定价与排名相反（背离%.1f位）' % div if div > 0 else '与定价方向一致')
        ana += '平局率%.1f%%。' % dp
        if dp >= 27:
            ana += '形态：平局闷死。'
        elif div > 0:
            ana += '形态：主推方即名次弱势方，失手风险来自平局或反向穿透。'
        else:
            ana += '形态：无突出形态。'
        out.append({'no': m.get('no'), 'h': m.get('h'), 'a': m.get('a'), 'lg': m.get('lg'),
                    'tm': m.get('tm') or m.get('date'), 'main': main, 'mp': mp, 'dp': dp,
                    'base': base if base is not None else 50.0, 'bn': st['n'],
                    'div': div, 'score': round(score, 1), 'lvl': lvl, 'ana': ana})
    if not out:
        return html
    out.sort(key=lambda x: -x['score'])
    return replace_var(html, '__SFC_COLD__', out)[0]


def _append_current_div(html, sp, iss):
    """把当期 14 场追加进 __R9_DIV__（背离追踪表），并标记 current 期号。

    原表只跑到上一期，且上一次的赛果没回填，页面上就只看到「上一期的对阵 + 未开赛」。
    """
    if not sp or not iss:
        return html
    pat = re.compile(r'window\.__R9_DIV__\s*=\s*(\{.*?\})\s*;\s*</script>', re.S)
    m = pat.search(html)
    if not m:
        print('[fix_today] 未找到 __R9_DIV__，跳过背离补当期')
        return html
    try:
        d = json.loads(m.group(1))
    except Exception:
        print('[fix_today] __R9_DIV__ 解析失败，跳过')
        return html
    rows = d.get('rows') or []
    # 同一期如果表里已经有（可能来自旧数据/别的期号映射），先整期剔除，再按当期 14 场重写，
    # 否则会出现「期号是 26166、比赛却是别的期的对阵」。
    rows = [r for r in rows if str(r.get('issue')) != str(iss)]
    added = 0
    for x in sp:
        hr, ar = x.get('hrank'), x.get('arank')
        gap = abs(int(hr) - int(ar)) if (hr not in (None, '') and ar not in (None, '')) else None
        band = None
        if gap is not None:
            band = ('一致' if gap == 0 else '差1-2位' if gap <= 2 else '差3-5位' if gap <= 5
                    else '差6-9位' if gap <= 9 else '差10位以上')
        rows.append({
            'issue': str(iss), 'no': x.get('no'), 'lg': x.get('lg'), 'date': x.get('date'),
            'h': x.get('h'), 'a': x.get('a'), 'hr': hr, 'ar': ar,
            'main': x.get('rec') or x.get('main'), 'main_p': x.get('main_p'),
            'div': round(float(x.get('gap') or 0), 1), 'gap': gap, 'band': band,
            'ft': None, 'real': None, 'hit': None,
        })
        added += 1
    # ★ 去重：同一期同一场次号只保留最后一条（新追加的为准），
    #   否则会出现「26166 既有拜仁/科隆、又有上一批挪超对阵」混在一张表里
    _seen = {}
    for r in rows:
        _seen[(str(r.get('issue')), str(r.get('no')))] = r
    rows = list(_seen.values())
    d['rows'] = rows
    d['current'] = str(iss)
    html, ok = replace_var(html, '__R9_DIV__', d)
    if ok:
        print('[fix_today] 背离表当期 %s 重写 %d 场（原表期号止于 %s）'
              % (iss, added, max([str(r.get('issue')) for r in rows if r.get('issue')] or ['—'])))
    return html


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
        # 超过 3 天的老注单仍然取不到比分：明确标注"档案缺比分"，不要一直挂「待回填」
        try:
            if missing and (datetime.date.today() - datetime.date.fromisoformat(d)).days >= 3:
                for leg in (rec.get('legs') or []):
                    if leg.get('actual') is None:
                        leg['note'] = '该日评分档案未入库'
        except Exception:
            pass
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
        cur = hist.get(combo['date'])
        if cur and not combo_should_replace(cur, combo):
            print('[fix_today] 同批次已有 2串1 定稿，按冻结口径不重算（%s）' % _batch_tag(cur))
        else:
            hist[combo['date']] = combo
            with io.open(os.path.join(DATA, 'combo_history.json'), 'w', encoding='utf-8') as f:
                json.dump(hist, f, ensure_ascii=False, indent=1)
            print('[fix_today] 生成%s 2串1：%s × %s · 理论赔率 %.2f · 命中概率 %.1f%%'
                  % ('新批次' if cur else '', combo['legs'][0]['no'], combo['legs'][1]['no'],
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

    # 背离追踪表补当期：原表只到上一期（赛果为空），页面看起来像「还在显示上一期的比赛」。
    # 把当期 14 场按同样的档位口径追加进 __R9_DIV__.rows，并标记 current。
    # 页面 JS 虽然会用 SFC._期次 覆盖，但用户先看到的就是这行旧文案 —— 直接按当期改写。
    sp = load('sfc_pick.json') or []
    if sp:
        iss = sp[0].get('issue') or ''
        dts = sorted({x.get('date') for x in sp if x.get('date')})
        day = dts[0] if dts else ''
        head = ('%s · 第 %s 期 · 胜负彩 14 场选 9 场' % (day, iss))
        m2 = re.search(r'(<span id="sfcIssueTxt">)([^<]*)(</span>)', html)
        if m2 and iss:
            html = html[:m2.start(2)] + head + html[m2.end(2):]
        okz = load('sfc_okooo.json') or {}
        dl = okz.get('deadline') or ''
        if dl:
            m3 = re.search(r'(<b id="sfcDeadline">)([^<]*)(</b>)', html)
            if m3:
                html = html[:m3.start(2)] + ('停售 %s' % dl) + html[m3.end(2):]
        print('[fix_today] 任九页头改写为 第 %s 期 · %s · 停售 %s' % (iss, day, dl or '—'))
        html = _append_current_div(html, sp, iss)
        # ★ 每期都跑：先回填赛果（旧期 real 空 → 用「竞彩赛果公告」补），再算雷达/校准
        html = _backfill_div_results(html, iss)
        html = _merge_bj_mobile(html)
        html = _apply_odds_delta(html)
        html = _archive_picks(html)
        html = _backfill_review(html)
        html = _inject_bj_today(html)
        html = _apply_calibration_multi(html)
        html = _merge_jc_okooo(html)
        html = _apply_intel_factors(html)
        html = _backfill_combo_all(html)
        html = _enrich_sfc_ana(html)
        html = _inject_refresh_button(html)
        html = _rebuild_cold(html, sp)
        # ★ 校准开关：结果回填出来的历史同档命中率 + 8 因子，是否真的写进显示概率
        if os.path.exists(os.path.join(DATA, '_calib_on.json')) or True:
            html = _apply_calibration(html, _diverge_rows(html), load('coach_map.json') or {})

    # 退役/告别/帅位公告：只搬运公开标题（直播吧），不挂靠当期球队、不预测
    rn = load('retire_news.json') or {}
    _cmap = load('coach_map.json') or {}
    # 本期相关队名（用于给帅位新闻排序：涉及本期球队的优先）
    _teams = set()
    for f in ('sfc_pick.json', 'full.json', '_bj_latest_full.json'):
        d = load(f) or {}
        ms = d.get('matches') if isinstance(d, dict) else d
        for m in (ms or []):
            for k in ('h', 'a'):
                v = (m.get(k) or '').strip()
                if len(v) >= 2:
                    _teams.add(v)
    _TEAM_LINES = set()
    for _tn, _xs in (_cmap.items()):
        for _x in _xs:
            _TEAM_LINES.add(_x)

    # 噪音过滤：青训/校园/女足/回忆类不进顶部速览（仍保留在页尾卡片里）
    _NOISE = ('女足', '中学', '小学', '大学', '青训', '梯队', '回忆', '当年', '昔日', '历史')

    def _rank_coach(it):
        title = it.get('title') or ''
        related = 1 if ('%s（%s）' % (title, it.get('date') or '')) in _TEAM_LINES else 0
        noise = 1 if any(x in title for x in _NOISE) else 0
        return (-related, noise, -(int((it.get('date') or '2026-01-01').replace('-', '') or 0)))

    _all = sorted((rn.get('items') or []), key=lambda x: (x.get('date') or ''), reverse=True)
    _coach_raw = [it for it in _all if (it.get('kind') == 'coach')]
    coach_items = sorted(_coach_raw, key=_rank_coach)[:8]
    player_items = [it for it in _all if (it.get('kind') != 'coach')][:8]
    # 顶部速览只要「非噪音 + 有日期」的，最多 3 条
    coach_top = [it for it in sorted(_coach_raw, key=_rank_coach)
                 if not any(x in (it.get('title') or '') for x in _NOISE)][:3]
    items = coach_items + player_items

    # ① 顶部「帅位动态」条：教练/主帅变动直接放在任九页头下方，不用滚到页尾
    if coach_top:
        def _one(it, i):
            t = (it.get('title') or '').replace('&', '&amp;').replace('<', '&lt;')
            d = it.get('date') or ''
            return ('<a href="%s" target="_blank" rel="noopener noreferrer" '
                    'style="color:#ffd166;text-decoration:none">%s</a>'
                    '<span style="color:#8a8a8a"> · %s</span>' % (it.get('url') or '#', t, d))
        strip = ('<div id="coachStrip" style="margin:10px 12px 2px;padding:10px 12px;border-radius:10px;'
                 'background:rgba(255,209,102,.08);border:1px solid rgba(255,209,102,.28);font-size:12px;line-height:1.75">'
                 '<div style="font-weight:800;font-size:13px;margin-bottom:4px;color:#ffd166">👔 帅位动态（教练 / 主帅变动）</div>'
                 '%s</div>') % '<br>'.join(_one(it, i) for i, it in enumerate(coach_top))
        anchor = '<div class="sfc-ops" style="flex-wrap:wrap">'
        if anchor in html:
            html = html.replace(anchor, strip + anchor, 1)
            print('[fix_today] 顶部帅位动态条注入 %d 条' % len(coach_top))

    if items and '</body>' in html:
        def _lis(lst, badge, color):
            out = []
            for it in lst:
                t = (it.get('title') or '').replace('&', '&amp;').replace('<', '&lt;')
                u = it.get('url') or '#'
                d = it.get('date') or ''
                out.append('<li style="margin:5px 0;line-height:1.7">'
                           '<span style="color:%s;font-size:11px">%s</span> '
                           '<span style="color:#8a8a8a">%s</span> '
                           '<a href="%s" target="_blank" rel="noopener noreferrer" '
                           'style="color:#fff;text-decoration:none">%s</a></li>' % (color, badge, d, u, t))
            return ''.join(out)
        sec = ''
        if coach_items:
            sec += ('<div style="font-weight:800;font-size:13px;margin:8px 0 4px;color:#ffd166">'
                    '👔 教练 / 主帅（%d 条）</div><ul style="font-size:12px;padding-left:16px;margin:0">%s</ul>'
                    % (len(coach_items), _lis(coach_items, '帅位', '#ffd166')))
        if player_items:
            sec += ('<div style="font-weight:800;font-size:13px;margin:10px 0 4px">'
                    '⚽ 球员退役 / 告别（%d 条）</div><ul style="font-size:12px;padding-left:16px;margin:0">%s</ul>'
                    % (len(player_items), _lis(player_items, '球员', '#64b5f6')))
        blk = ('<div id="retireNewsCard" style="margin:12px 12px 16px;padding:12px 14px;border-radius:10px;'
               'background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12)">'
               '<div style="font-weight:800;font-size:14px;margin-bottom:4px">📰 退役 / 告别 / 卸任公告</div>'
               '<div style="font-size:11px;color:#9a9a9a;margin-bottom:6px">公开新闻源：直播吧足球频道（近 14 天）。'
               '只搬标题不预测，点标题看原文。</div>%s</div>') % sec
        html = html.replace('</body>', blk + '\n</body>', 1)
        print('[fix_today] 公告区块注入：教练 %d 条 / 球员 %d 条' % (len(coach_items), len(player_items)))

    # 战意文案：国际赛没有俱乐部联赛积分榜，原来那句"项目内无该组小组积分快照"又长又像缺数据，改成明确口径
    html = html.replace(
        '【战意】本场为欧国联小组赛，但项目内无该组小组积分快照：',
        '【战意】本场为欧国联小组赛（国际赛无俱乐部联赛积分榜，不按联赛排名论战意）：')
    html = html.replace(
        '【战意】本场为欧国联小组赛，但项目内无该组小组积分榜：',
        '【战意】本场为欧国联小组赛（国际赛无俱乐部联赛积分榜，不按联赛排名论战意）：')

    # 复盘标题：模板写死 9/20，改成累计口径（内容由 review_stat 重算写入）
    html = html.replace('📋 9/20 全场复盘', '📋 全场复盘（累计存档）')

    tmp = PAGE + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    # Windows 上 index.html 常被浏览器/上传进程占用 → os.replace 会 PermissionError，
    # 这里退化为「重试 + 原地覆盖」，避免整轮循环报废。
    last = None
    for i in range(6):
        try:
            os.replace(tmp, PAGE)
            last = None
            break
        except OSError as ex:
            last = ex
            time.sleep(1.5)
            try:
                with io.open(PAGE, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(html)
                os.remove(tmp)
                last = None
                break
            except OSError as ex2:
                last = ex2
                time.sleep(1.5)
    if last is not None:
        print('[fix_today] 写页面失败（被占用）：%s' % last)
        return 2
    print('[fix_today] 页面已更新 %d B' % len(html.encode('utf-8')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
