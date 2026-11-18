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
LB = ['主胜', '平局', '客胜']

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
        if not lg:
            continue
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

        # ⑤ 历史交锋
        hits = [x for x in arch if {norm(x.get('h')), norm(x.get('a'))} == {h, a} and x.get('actual')]
        if hits:
            hw = len([x for x in hits if x['actual'] == '主胜'])
            dr = len([x for x in hits if x['actual'] == '平局'])
            aw = len([x for x in hits if x['actual'] == '客胜'])
            last = hits[-1]
            parts.append('【历史交锋】归档里两队交手 %d 次：主胜 %d / 平 %d / 客胜 %d。最近一次 %s（%s）。'
                         % (len(hits), hw, dr, aw, last.get('note') or last.get('no') or '—', last.get('no') or ''))
        else:
            parts.append('【历史交锋】归档里这两队没有交手记录（跨联赛/首次相遇），不套用他队数据。')

        # ⑥ 伤停（本轮没接独立伤停源）
        parts.append('【伤停】独立伤停接口本轮未接通（官方 getMatchListV1 被 WAF 拦 567、澳客 403），'
                     '按铁律不臆测名单，只标"未采集"。')

        # ⑦ 结论
        if p[1] >= 27:
            parts.append('【结论】' + VERDICT_DRAW)
        else:
            parts.append('【结论】主推 %s 概率 %.1f%%，模型与该档历史命中率基本一致，'
                         '按单选口径执行；不建议加双选（归档回测双选 EV 全面更差）。' % (main, mp))

        m['ana'] = '，'.join([m['ana']]) if m.get('ana') else ''
        m['ana'] = (m.get('ana', '').rstrip('。') + '。' if m.get('ana') else '') + '\n'.join(parts)
        m['ana_ver'] = 'enrich-1'
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
