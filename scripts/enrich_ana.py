#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按归档真实赛果，把每场分析从一句话扩成多段（本地算，不联网、不编数）。

口径来源：项目《每日更新全流程说明》§4 —— 分析文字是本地算出来的，不是抓来的。
  · 概率：系数去水（full.json 已有 p）
  · 同档校准：归档按主推概率分档，算同档实际命中率（样本 <8 场写"样本不足不评"）
  · 翻车形态：归档里 actual != main 的比例与结构
  · 联赛平局特性：归档按联赛算平局率（样本 <8 场不评）
  · 历史交锋：归档里同两队（主客双向）交手记录
  · 结论：平局率 ≥27 时按项目铁律写范本原句（逐字，不改数字）

缺的一律如实写"未采集 / 样本不足"，不臆测名单、不硬套范本数字。
"""
import io
import json
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
FULL = os.path.join(DATA, 'full.json')
ARCH = os.path.join(DATA, '_archive_done.json')
INTEL = os.path.join(DATA, 'intel500.json')
LB = ['主胜', '平局', '客胜']


def _load_json(p):
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return {}


# 澳客三维情报（伤停阵容 / 技术统计 / 积分战意），由 scripts/fetch_intel_okooo.py 抓
OKO = _load_json(os.path.join(DATA, 'intel_okooo.json')) or {}
RMAP = _load_json(os.path.join(DATA, 'retire_map.json')) or {}

VERDICT_DRAW = ('胜平负：平局率28.4%偏高、方向不稳，建议降低单注信心或整场放弃'
                '（注：双选虽能提高命中率，但成本翻倍，实测EV更差，不建议）')


def norm(s):
    s = (s or '').strip()
    s = re.sub(r'[（(].*?[)）]', '', s)
    s = re.sub(r'\s+', '', s)
    return s.replace('　', '')


def band(p):
    for lo in (75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 0):
        if p >= lo:
            return lo
    return 0


def main():
    arch = json.load(io.open(ARCH, encoding='utf-8'))
    full = json.load(io.open(FULL, encoding='utf-8'))
    intel = {}
    if os.path.exists(INTEL):
        try:
            intel = json.load(io.open(INTEL, encoding='utf-8'))
        except Exception as e:
            print('[enrich] intel500.json 读取失败，按无情报处理：%s' % e)
    ms = full.get('matches') or []
    if not ms:
        print('[enrich] full.json 没有场次，跳过')
        return 1

    # 全局：翻车结构
    flips = [x for x in arch if x.get('actual') and x.get('main') and x.get('actual') != x.get('main')]
    tot = len([x for x in arch if x.get('actual')])
    flip_n = len(flips)
    flip_cnt = Counter(x['actual'] for x in flips)
    draw_all = len([x for x in arch if x.get('actual') == '平局'])

    # 联赛平局率
    lg_stat = {}
    for x in arch:
        lg = x.get('lg') or ''
        if not lg or not x.get('actual'):
            continue      # 没有赛果的场次不能进分母，否则平局率会被稀释成 0.x%
        d = lg_stat.setdefault(lg, [0, 0])
        d[1] += 1
        if x.get('actual') == '平局':
            d[0] += 1

    # 同档校准
    band_stat = {}
    for x in arch:
        if not x.get('main_p') or not x.get('actual'):
            continue
        b = band(float(x['main_p']))
        s = band_stat.setdefault(b, [0, 0])
        s[1] += 1
        if x['actual'] == x['main']:
            s[0] += 1

    updated = 0
    for m in ms:
        p = m.get('p') or []
        if len(p) != 3:
            continue
        h, a, lg = norm(m.get('h')), norm(m.get('a')), (m.get('lg') or '')
        # 幂等：首次运行时把原始一句话分析存进 ana_base，之后每次都从底稿重建，避免重复追加
        if m.get('ana_base') is None:
            m['ana_base'] = (m.get('ana') or '').strip()
        base = (m.get('ana_base') or '').strip()
        mp = float(m.get('main_p') or max(p))
        main = m.get('main') or LB[p.index(max(p))]
        parts = []

        # ① 定价·排名一致性（官方名次标签，随赛程抓来）
        hr, ar = m.get('hrank'), m.get('arank')
        if hr and ar:
            gap = int(ar) - int(hr)
            side = '主队位次领先' if gap > 0 else ('客队位次领先' if gap < 0 else '两队位次持平')
            parts.append('【定价·排名一致性】%s 排第 %d、%s 排第 %d，%s %d 位。'
                         '名次口径＝体彩官网赛程接口给的联赛名次标签，不是积分榜实时换算。'
                         % (m.get('h'), int(hr), m.get('a'), int(ar), side, abs(gap)))
        else:
            parts.append('【定价·排名一致性】本场官方赛程未给名次标签，不作位次推断。')

        # ② 同档校准
        b = band(mp)
        s = band_stat.get(b, [0, 0])
        if s[1] >= 8:
            hit = s[0] / s[1] * 100
            parts.append('【校准·表A】主推概率 %.1f%% 落入 %d-%d%% 档，归档同档 %d 场实测命中率 %.1f%%'
                         '（差 %+.1f 个百分点）。' % (mp, b, b + 5, s[1], hit, hit - mp))
        else:
            parts.append('【校准·表A】主推概率 %.1f%% 落入 %d-%d%% 档，归档同档仅 %d 场，样本不足不评。'
                         % (mp, b, b + 5, s[1]))

        # ③ 翻车形态
        if tot:
            parts.append('【翻车形态】归档 %d 场有赛果，主推未中 %d 场（%.1f%%）；其中平局 %d 场(%.1f%%)、'
                         '客胜 %d 场(%.1f%%)、主胜 %d 场(%.1f%%)。全样本平局率 %.1f%%。'
                         % (tot, flip_n, flip_n / tot * 100,
                            flip_cnt.get('平局', 0), flip_cnt.get('平局', 0) / max(1, flip_n) * 100,
                            flip_cnt.get('客胜', 0), flip_cnt.get('客胜', 0) / max(1, flip_n) * 100,
                            flip_cnt.get('主胜', 0), flip_cnt.get('主胜', 0) / max(1, flip_n) * 100,
                            draw_all / max(1, tot) * 100))
        else:
            parts.append('【翻车形态】归档无赛果样本，不评估。')

        # ④ 联赛平局特性
        ls = lg_stat.get(lg)
        if ls and ls[1] >= 8:
            parts.append('【联赛平局特性】%s 在本库归档 %d 场里平局 %d 场，占 %.1f%%（本场模型平局率 %.1f%%，%s）。'
                         % (lg, ls[1], ls[0], ls[0] / ls[1] * 100, p[1],
                            '高于该联赛常态' if p[1] > ls[0] / ls[1] * 100 else '不高于该联赛常态'))
        else:
            parts.append('【联赛平局特性】%s 在本库归档样本不足 8 场，不给联赛平局基准，不编造。' % (lg or '本场联赛'))

        # ⑤ 500 情报：近况 / 主客场 / 场均 / 阵型 / 交锋 / 伤停
        q = intel.get(m.get('no')) if intel else None
        if q and q.get('home'):
            h10, a10 = q['home'], q.get('away') or {}
            parts.append('【近期状态·500】%s 近10场 %d胜%d平%d负（胜率%d%%），进%d失%d（净%d）；'
                         '%s 近10场 %d胜%d平%d负（胜率%s%%），进%s失%s。'
                         % (m.get('h'), h10['w'], h10['d'], h10['l'], h10['win_pct'],
                            h10['gf'], h10['ga'], h10['gd'],
                            m.get('a'), a10.get('w', 0), a10.get('d', 0), a10.get('l', 0),
                            a10.get('win_pct', '—'), a10.get('gf', '—'), a10.get('ga', '—')))
            hh, aa = q.get('home_home'), q.get('away_away')
            if hh and aa:
                parts.append('【主客场拆分】%s 主场近10场 %d胜%d平%d负（胜率%d%%，进%d失%d）；'
                             '%s 客场近10场 %d胜%d平%d负（胜率%d%%，进%d失%d）。'
                             % (m.get('h'), hh['w'], hh['d'], hh['l'], hh['win_pct'], hh['gf'], hh['ga'],
                                m.get('a'), aa['w'], aa['d'], aa['l'], aa['win_pct'], aa['gf'], aa['ga']))
            if q.get('home_avg'):
                ha = q['home_avg']
                aa2 = q.get('away_avg') or {}
                parts.append('【场均进失】%s 场均进%.2f失%.2f（主场 %.2f/%.2f）；%s 场均进%.2f失%.2f（客场 %.2f/%.2f）。'
                             % (m.get('h'), ha['gf'][0], ha['ga'][0], ha['gf'][1], ha['ga'][1],
                                m.get('a'), (aa2.get('gf') or [0])[0], (aa2.get('ga') or [0])[0],
                                (aa2.get('gf') or [0, 0])[2] if len(aa2.get('gf') or []) > 2 else 0,
                                (aa2.get('ga') or [0, 0])[2] if len(aa2.get('ga') or []) > 2 else 0))
            if q.get('home_form'):
                parts.append('【预计阵型·500】%s %s / %s %s（500 赛前预计，仅供参考布置，不参与概率）。'
                             % (m.get('h'), q['home_form'], m.get('a'), q.get('away_form') or '未列'))
        else:
            parts.append('【近期状态·500】本场未取到 500 数据页，近况与阵型留空。')

        # ⑥ 战术对位（脑图第四条：阵型 / 局型 / 攻防倾向；只用页面已有数据，不编打法细节）
        lam = m.get('tot') or m.get('lam') or m.get('tot_p')
        feat = m.get('feat') or ''
        top3 = m.get('top3') or []
        hf = (q or {}).get('home_form') if isinstance(q, dict) else None
        af = (q or {}).get('away_form') if isinstance(q, dict) else None
        if hf and af:
            same = '两边同为 %s，属同阵型对位，拼的是执行与个人能力。' % hf if hf == af else \
                   '%s 对 %s，宽度与中场人数不对等，边路与中路谁先被打穿是关键。' % (hf, af)
            parts.append('【战术对位】' + same)
        else:
            parts.append('【战术对位】本场没取到双方阵型，战术对位不作推断。')
        if lam or feat or top3:
            parts.append('【局型推演】总进球预期 %s 球%s；比分主推 %s。这是按 λ 与赔率算出的分布，'
                         '不是脚本假设：λ 高则对攻局、λ 低则闷战局，比赛进程会跟着变。'
                         % (('%.1f' % float(lam)) if lam else '—',
                            ('（%s）' % feat) if feat else '',
                            '、'.join([str(x) if not isinstance(x, dict) else str(x.get('s')) for x in top3[:3]]) or '—'))


        if q and q.get('h2h_rec'):
            parts.append('【历史交锋·500】对赛成绩 %s %s（500 口径，主队视角）。'
                         % (q.get('h2h') or m.get('h'), q['h2h_rec']))
        else:
            hits = [x for x in arch if {norm(x.get('h')), norm(x.get('a'))} == {h, a} and x.get('actual')]
            if hits:
                hw = len([x for x in hits if x['actual'] == '主胜'])
                dr = len([x for x in hits if x['actual'] == '平局'])
                aw = len([x for x in hits if x['actual'] == '客胜'])
                last = hits[-1]
                parts.append('【历史交锋】归档里两队交手 %d 次：主胜 %d / 平 %d / 客胜 %d。最近一次 %s（%s）。'
                             % (len(hits), hw, dr, aw, last.get('note') or last.get('no') or '—', last.get('no') or ''))
            else:
                parts.append('【历史交锋】本库归档与 500 都没有这两队的交手记录，不套用他队数据。')

        # ⑦ 伤停
        if q and q.get('inj'):
            parts.append('【伤停·500】' + q['inj'])
        else:
            parts.append('【伤停·500】500 数据页「伤病/停赛」栏为空（赛前名单通常开赛前才补），按铁律不臆测名单。')

        # ⑧ 第三方观点（只引用，不进模型）
        if q and q.get('tip'):
            tip = q['tip'].split('对赛成绩')[0].strip()
            if tip:
                parts.append('【第三方观点·500】%s（原样引用，未并入本页概率）。' % tip)

        # ⑨ 综合评估（脑图第十二条：置信度 / 风险等级 / 最终口径）
        gap = m.get('gap')
        star = '★★☆☆☆' if mp < 55 else ('★★★☆☆' if mp < 65 else ('★★★★☆' if mp < 75 else '★★★★★'))
        # ★ 名次真正参与胜负判断：主推方向与联赛名次差明显逆向时降一档信心，
        #   同向时维持。名次差按「每 6 位算一档」粗分，只在文字层做修正，
        #   不改 p（赔率本身已含市场对名次的定价），这样既不编概率也用上了排名。
        rank_note = ''
        if hr and ar:
            d_rank = int(hr) - int(ar)              # 正数=主队位次更好
            side_ok = (main == '主胜' and d_rank > 0) or (main == '客胜' and d_rank < 0)
            side_bad = (main == '主胜' and d_rank <= -6) or (main == '客胜' and d_rank >= 6)
            if side_bad:
                star = {'★★★★★': '★★★★☆', '★★★★☆': '★★★☆☆',
                        '★★★☆☆': '★★☆☆☆', '★★☆☆☆': '★★☆☆☆'}.get(star, star)
                rank_note = '；名次逆风（主队%d位/客队%d位），信心下调一档' % (int(hr), int(ar))
            elif side_ok:
                rank_note = '；名次同向（主队%d位/客队%d位），信心维持' % (int(hr), int(ar))
            else:
                rank_note = '；名次与方向不一致（主队%d位/客队%d位），按中性处理' % (int(hr), int(ar))
        risk = '高' if (gap is not None and float(gap) < 12) or p[1] >= 27 else (
            '中' if mp < 60 else '低')
        parts.append('【综合评估】主推 %s %.1f%%（%s），与次选差 %s 个百分点；风险等级 %s%s。'
                     '本页概率只由赔率去水得出，名次/状态只用于信心与风险，不重算概率。'
                     % (main, mp, star, ('%.1f' % float(gap)) if gap is not None else '—', risk, rank_note))

        # ⑥b 退役/告别公告（只挂标题里明确出现该队的公开新闻）
        _rn = []
        for _tn in (m.get('h'), m.get('a')):
            for _x in (RMAP.get(_tn) or [])[:2]:
                if _x not in _rn:
                    _rn.append(_x)
        if _rn:
            parts.append('【退役·告别公告】%s（公开新闻，仅作背景，不代表本场是告别战）。'
                         % '；'.join(_rn))

        # ⑦ 爆冷指数 + 换代观察（都在【结论】之前，结论要用到 _cold）
        _others = [p[j] for j in range(3) if j != p.index(max(p))]
        _gap_p = mp - max(_others)
        _cold = 0
        if _gap_p < 12:
            _cold += 30
        if p[1] >= 27:
            _cold += 25
        if hr and ar and abs(int(hr) - int(ar)) >= 6 and (
                (main == '主胜' and int(hr) - int(ar) <= -6) or
                (main == '客胜' and int(hr) - int(ar) >= 6)):
            _cold += 25
        if float(m.get('draw_p') or 0) >= 26:
            _cold += 10
        _tag = '高' if _cold >= 60 else ('中' if _cold >= 35 else '低')
        if _cold >= 60:
            add = '不适合当胆，串关避开或降注'
        elif _cold >= 35:
            add = '可作次选位，不建议单独重注'
        else:
            add = '可当常规单选'
        parts.append('【爆冷提示】冷门指数 %d/100（%s）：与次选仅差 %.1f 个百分点%s；%s。'
                     % (_cold, _tag, _gap_p, '，平局热度超 27%' if p[1] >= 27 else '', add))
        _oi0 = OKO.get('jc:%s' % (m.get('no') or '')) or {}
        _b0 = _oi0.get('body') or []
        _ages = [int(x) for x in [re.search(r'(\d{2})岁', str(b)).group(1)
                                 for b in _b0 if re.search(r'(\d{2})岁', str(b))]]
        if _ages:
            _old = max(_ages)
            parts.append('【换代·告别观察】两队平均年龄 %s / %s，%s。公开渠道没有本场球员或教练的退役声明，'
                         '所以不点名、不预测谁在哪场退役；要写「告别战」必须有官方或本人声明做依据。'
                         % (_b0[0], _b0[1] if len(_b0) > 1 else '—',
                            '平均年龄偏高（%d 岁），赛季末存在主力换代/离队可能，阵容稳定性打折扣' % _old
                            if _old >= 29 else '年龄结构正常，换代因素可忽略（最高均龄 %d 岁）' % _old))
        # 结论
        if p[1] >= 27:
            parts.append('【结论】' + VERDICT_DRAW)
        else:
            parts.append('【结论】主推 %s 概率 %.1f%%，%s；不建议加双选（归档回测双选 EV 全面更差）。'
                         % (main, mp,
                            '冷门指数偏高，只作次选或降注' if _cold >= 60
                            else ('按单选口径执行，可作串关胆' if _cold < 35
                                  else '按单选口径执行，串关里别当胆')))

        # ⑧ 澳客三维情报（伤停阵容 / 场均技术 / 积分战意）
        #   500 数据页被 EdgeOne 拦，改走澳客 /match/form.php 与 /match/game.php，
        #   这两个页面无需任何验证，云主机也能直连 —— 不再需要人工过验证。
        _oi = OKO.get('jc:%s' % (m.get('no') or '')) or {}
        _inj = _oi.get('inj')
        _val = _oi.get('value') or []
        _body = _oi.get('body') or []
        if _inj or _val or _body:
            _t = '【伤停·阵容】伤停：%s。' % (_inj or '未采集')
            if _val:
                _t += '身价 %s vs %s。' % (_val[0], _val[1] if len(_val) > 1 else '—')
            if _body:
                _t += '平均身高/年龄 %s vs %s。' % (_body[0], _body[1] if len(_body) > 1 else '—')
            parts.append(_t)
        _tek = _oi.get('tech') or {}
        if _tek:
            def _f(k, side):
                v = (_tek.get(k) or {}).get(side) or {}
                return v.get('all'), v.get('venue')
            _hg, _hgv = _f('goal', 'home')
            _ag, _agv = _f('goal', 'away')
            _hl, _hlv = _f('loss', 'home')
            _al, _alv = _f('loss', 'away')
            _hs, _hsx = _f('shot', 'home')
            _as_, _asx = _f('shot', 'away')
            _hp, _hpx = _f('poss', 'home')
            _ap, _apx = _f('poss', 'away')
            parts.append('【技术统计·澳客近20场】场均进球 %s / %s（主场 %s / 客场 %s），'
                         '场均失球 %s / %s，场均射门 %s / %s，控球 %s%% / %s%%。'
                         % (_hg, _ag, _hgv, _agv, _hl, _al, _hs, _as_, _hp, _ap))
        _hh = (_oi.get('home') or {}).get('rank')
        _aa = (_oi.get('away') or {}).get('rank')
        if _hh and _aa:
            _hp2 = (_oi.get('home') or {}).get('pts')
            _ap2 = (_oi.get('away') or {}).get('pts')
            _mood = '两队位次接近，战意按常规主客场权重处理'
            if abs(_hh - _aa) >= 8:
                _mood = '位次差 %d 位，积分诉求不对等，弱侧抢分动机更强' % abs(_hh - _aa)
            parts.append('【积分·战意】积分榜第 %d 名（%s 分） vs 第 %d 名（%s 分）；%s。'
                         % (_hh, _hp2, _aa, _ap2, _mood))

        m['ana'] = ((base.rstrip('。') + '。') if base else '') + '\n'.join(parts)
        m['ana_ver'] = 'enrich-2'
        updated += 1

    tmp = FULL + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(full, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FULL)
    print('[enrich] %d 场分析已扩写（归档 %d 场 / 联赛 %d 个 / 同档档位 %d 个）'
          % (updated, tot, len(lg_stat), len(band_stat)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
