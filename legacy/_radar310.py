# -*- coding: utf-8 -*-
"""★ 第三一〇条 B：爆冷雷达必须随期次动态生成。
根因（已复发两次）：__SFC_COLD__ 是模板里的硬编码块，只改产物 index_live.html
不改模板，refresh build 从模板生成时又把旧期数据带回来 —— "标题对了内容是旧的"。
本脚本在 make_live 之前跑，直接改写【模板 index.html】里的 __SFC_COLD__。
"""
import json, os, re, io, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
ARCHIVE = os.path.join(BASE, 'data', '_archive_done.json')
TPL = os.path.join(BASE, 'index.html')
LIVE = os.path.join(BASE, 'index_live.html')

BUCKETS = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 200)]


import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import dir_of_ft as _lib_dir_of_ft

def dir_of(ft):
    """比分 -> W/D/L —— 委托 _lib.dir_of_ft（第三二九条：单一实现）"""
    return _lib_dir_of_ft(ft)


def dir_hit(rec_main, ft):
    """赛前主推方向是否命中"""
    r = dir_of(ft)
    if not r:
        return None
    mp = {'主胜': 'W', '平局': 'D', '客胜': 'L'}
    want = mp.get(rec_main)
    if not want:
        return None
    return 1 if want == r else 0


def calib_table():
    """从归档真实赛果算各概率档的历史命中/翻车率"""
    try:
        arc = json.load(io.open(ARCHIVE, encoding='utf-8'))
    except Exception:
        arc = []
    tab = {}
    for lo, hi in BUCKETS:
        tab[(lo, hi)] = {'n': 0, 'hit': 0}
    n_all = 0
    for t in arc:
        p = t.get('main_p') or t.get('mp') or t.get('pre_p')
        ft = t.get('ft')
        main = t.get('main') or t.get('pre_main')
        if p is None or not ft or not main:
            continue
        try:
            p = float(p)
        except Exception:
            continue
        if p > 1:
            p = p  # 已是百分比
        elif p <= 1:
            p = p * 100
        h = dir_hit(main, ft)
        if h is None:
            continue
        n_all += 1
        for lo, hi in BUCKETS:
            if lo <= p < hi:
                tab[(lo, hi)]['n'] += 1
                tab[(lo, hi)]['hit'] += h
                break
    out = {}
    for lo, hi in BUCKETS:
        d = tab[(lo, hi)]
        n = d['n']
        rate = (d['hit'] / n) if n else None
        out[(lo, hi)] = {'n': n, 'hit': d['hit'], 'rate': rate,
                         'flop': (100 - rate * 100) if rate is not None else None}
    return out, n_all


def bucket_of(p):
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return (lo, hi)
    return BUCKETS[-1]


def rank_div(main, hr, ar):
    """排名背离分：市场方向与排名优劣相反时计入"""
    if hr is None or ar is None:
        return 0.0
    try:
        hr, ar = int(hr), int(ar)
    except Exception:
        return 0.0
    # 主推主胜但主队排名更差 → 背离；主推客胜但客队排名更差 → 背离
    if (main == '主胜' and hr > ar) or (main == '客胜' and ar > hr):
        return min(20.0, abs(hr - ar) * 0.6)
    return 0.0


def rank_phrase(m):
    """★ 第三七一条：名次口径优先取官方 homeRank 自带的赛事标签（如 [欧罗巴10]）。
    标签是官方给的，不要用联赛名去猜；没有标签才回退到 lg。"""
    lg = m.get('hrank_lg') or m.get('arank_lg') or m.get('lg') or ''
    return ('名次口径：竞彩官方%s积分榜' % lg) if lg else '名次口径：竞彩官方积分榜'


def uel_segments():
    """独立源交叉校验段（_uel_ana.py 产出）。缺文件 = 没有独立源，返回空，不编造。"""
    try:
        d = json.load(io.open(os.path.join(DATA, 'uel_ana.json'), encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def motiv_segments():
    """★ 第三七二条：排名+积分推导的【战意】段（_uel_motivation.py 产出）。
    缺快照 / 模板文件 → 文件为 {}，这里返回空串，绝不编战意。"""
    try:
        d = json.load(io.open(os.path.join(DATA, 'uel_motiv.json'), encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def build(ms, issue):
    tab, n_all = calib_table()
    uel = uel_segments()
    mot = motiv_segments()
    out = []
    for m in ms:
        p = m.get('p') or []
        if len(p) != 3:
            continue
        main = m.get('main')
        if main not in ('主胜', '平局', '客胜'):
            main = ['主胜', '平局', '客胜'][p.index(max(p))]
        mp = p[['主胜', '平局', '客胜'].index(main)]
        dp = p[1]
        bk = bucket_of(mp)
        st = tab.get(bk, {'n': 0, 'flop': None})
        base = st['flop'] if st['flop'] is not None else 50.0
        bn = st['n']
        div = rank_div(main, m.get('hrank'), m.get('arank'))
        score = base + max(0.0, dp - 24.0) * 0.8 + div
        lvl = '高' if score >= 55 else ('中' if score >= 45 else '低')
        hr, ar = m.get('hrank'), m.get('arank')
        rk = ''
        if hr and ar:
            rk = ('主队%s第%d、客队第%d，' % (m.get('lg') or '', hr, ar))
            if div >= 2.0:
                rk += ('市场定价与排名相反（名次差%.1f位 = |第%d − 第%d| × 0.6），'
                       '名次背离显著，为突出项。' % (div, hr, ar))
            elif div > 0:
                 rk += '市场定价与排名相反，名次背离%.1f位（未达突出项阈值2.0）。' % div
            else:
                rk += '与定价方向一致。'
            rk += rank_phrase(m) + '。'
        # ★ 第三七一条：独立源【欧战排名】段，只读本地 uel_ana.json；
        #   没有独立源时为空串，绝不编一个名次。
        _uk = str(m.get('no') or '')
        _key2 = '%s|%s' % (m.get('h'), m.get('a'))
        _useg = uel.get(_uk) or uel.get(_key2) or ''
        _mseg = mot.get(_uk) or mot.get(_key2) or ''
        shape = []
        if dp >= 27:
            shape.append('平局闷死')
        if div > 0:
            shape.append('主推方即名次弱势方（背离项），失手风险来自平局或反向穿透')
        if mp < 40:
            shape.append('低概率档本身不稳')
        ana = ('🧊 爆冷风险 %s（%.1f）｜主推%s%.1f%%，处%d-%d%%档，'
               '历史同档%d场命中%.1f%%（翻车%.1f%%）。%s%s%s平局率%.1f%%。形态：%s。') % (
            lvl, score, main, mp, bk[0], bk[1], bn,
            (100 - base) if bn else 0, base, rk, _useg, _mseg, dp,
            '／'.join(shape) if shape else '无突出形态')
        out.append({
            'no': m.get('no'), 'h': m.get('h'), 'a': m.get('a'),
            'lg': m.get('lg'), 'tm': m.get('tm') or m.get('date'),
            'main': main, 'mp': mp, 'dp': dp, 'base': base, 'bn': bn,
            'div': round(div, 2), 'score': round(score, 1), 'lvl': lvl, 'ana': ana,
        })
    out.sort(key=lambda x: -x['score'])
    return out, tab, n_all


def inject(html, payload):
    pat = re.compile(r'(window\.__SFC_COLD__\s*=\s*)(\[.*?\])\s*;', re.S)
    m = pat.search(html)
    if not m:
        return html, False
    return pat.sub(lambda _m: _m.group(1) + payload + ';', html, count=1), True


def main():
    fp = os.path.join(DATA, 'sfc_pick.json')
    if not os.path.exists(fp):
        print('缺 data/sfc_pick.json')
        return 1
    cur = json.load(io.open(fp, encoding='utf-8'))
    if not cur:
        print('sfc_pick.json 为空')
        return 1
    issue = cur[0].get('issue')
    ms = cur if isinstance(cur, list) else cur.get('matches', [])
    out, tab, n_all = build(ms, issue)
    # ★ 第三七三条：样例/链路自检必须走 --dry，只算不写。
    #   过去直接跑会把样例段注入模板+产物，看着「有了」，清掉又「没了」——
    #   这就是「第一次可以第二次不行」的假象来源之一。
    if '--dry' in sys.argv:
        print('DRY 只算不写：%d 条' % len(out))
        for x in out[:2]:
            print('  %s %s' % (x['no'], x['ana'][:220]))
        return 0
    payload = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    # 1) 模板（★ 关键：不改模板，下次 build 还会带回旧数据）
    h = io.open(TPL, encoding='utf-8').read()
    h2, ok1 = inject(h, payload)
    if ok1:
        io.open(TPL, 'w', encoding='utf-8').write(h2)
    # 2) 产物
    ok2 = False
    if os.path.exists(LIVE):
        l = io.open(LIVE, encoding='utf-8').read()
        l2, ok2 = inject(l, payload)
        if ok2:
            io.open(LIVE, 'w', encoding='utf-8').write(l2)
    # ★ 样本数必须与实际一致（模板里写死的 490 曾与实际 442 不符）
    for pth in (TPL, LIVE):
        if not os.path.exists(pth):
            continue
        t = io.open(pth, encoding='utf-8').read()
        if '__CALIB_N__' in t or re.search(r'基于\d+场历史复盘', t):
            t = re.sub(r'基于(?:__CALIB_N__|\d+)场历史复盘', '基于%d场历史复盘' % n_all, t)
            io.open(pth, 'w', encoding='utf-8').write(t)
    print('雷达 %s 期：%d 场（归档样本 %d 场）' % (issue, len(out), n_all))
    print('  模板替换 %s / 产物替换 %s' % (ok1, ok2))
    for x in out[:4]:
        print('   %s %s vs %s  推%s %.1f%%  风险%.1f %s' % (
            x['no'], x['h'], x['a'], x['main'], x['mp'], x['score'], x['lvl']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
