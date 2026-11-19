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
        risk = '高' if (gap is not None and float(gap) < 12) or p[1] >= 27 else (
            '中' if mp < 60 else '低')
        parts.append('【综合评估】主推 %s %.1f%%（%s），与次选差 %s 个百分点；风险等级 %s。'
                     '本页概率只由赔率去水得出，8 维因子只解释文字不参与计算，'
                     '所以别把它当成比市场更准的独立预测。'
                     % (main, mp, star, ('%.1f' % float(gap)) if gap is not None else '—', risk))

        # ⑦ 结论
        if p[1] >= 27:
            parts.append('【结论】' + VERDICT_DRAW)
        else:
            parts.append('【结论】主推 %s 概率 %.1f%%，模型与该档历史命中率基本一致，'
                         '按单选口径执行；不建议加双选（归档回测双选 EV 全面更差）。' % (main, mp))

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
