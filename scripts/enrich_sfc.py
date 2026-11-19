# -*- coding: utf-8 -*-
"""任九（胜负彩14场）逐场分析生成。

原来 enrich_ana 只处理 full.json（竞彩 8 场），sfc_pick.json 里 14 场的 ana 一直是 null，
所以任九卡片「没有分析」——页面里写的是「逐场分析 0/14」。
这个脚本用同一套口径给任九补：
  ①定价（澳客终盘欧赔去水）  ②同档校准（归档同概率档命中率）
  ③联赛平局特性  ④名次·战意（积分榜位次差）
  ⑤爆冷提示（赔率集中度/平局热度/名次逆风合成冷门指数）
  ⑥结论
全部来自赔率与归档真实赛果，不编比分、不编阵容。
"""
import io, json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
PICK = os.path.join(DATA, 'sfc_pick.json')
ARCH = os.path.join(DATA, '_archive_done.json')
OKO = os.path.join(DATA, 'intel_okooo.json')
RETIRE = os.path.join(DATA, 'retire_map.json')
LB = ['主胜', '平局', '客胜']


def load(p):
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return None


def band(p):
    for lo in (75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 0):
        if p >= lo:
            return lo
    return 0


def main():
    ms = load(PICK)
    arch = load(ARCH) or []
    oko = load(OKO) or {}
    rmap = load(RETIRE) or {}
    if not ms:
        print('[sfc-enrich] 没有 sfc_pick.json，跳过')
        return 1

    total = len([x for x in arch if x.get('actual')])
    draw_all = len([x for x in arch if x.get('actual') == '平局'])
    lg_stat, band_stat = {}, {}
    for x in arch:
        lg = x.get('lg') or ''
        if lg and x.get('actual'):
            d = lg_stat.setdefault(lg, [0, 0])
            d[1] += 1
            if x.get('actual') == '平局':
                d[0] += 1
        if x.get('main_p') and x.get('actual'):
            b = band(float(x['main_p']))
            s = band_stat.setdefault(b, [0, 0])
            s[1] += 1
            if x['actual'] == x['main']:
                s[0] += 1

    n = 0
    for m in ms:
        p = m.get('p') or m.get('fus') or []
        if len(p) != 3:
            continue
        i = p.index(max(p))
        main, mp = LB[i], float(max(p))
        alt_i = max([j for j in range(3) if j != i], key=lambda j: p[j])
        parts = []
        src = m.get('src') or 'okooo-m'
        o = m.get('o') or m.get('odds') or [0, 0, 0]
        parts.append('【定价·澳客终盘】欧赔 %.2f/%.2f/%.2f，去水后 主 %.1f%% 平 %.1f%% 客 %.1f%%，主推 %s。'
                     % (o[0], o[1], o[2], p[0], p[1], p[2], main))
        s = band_stat.get(band(mp))
        if s and s[1] >= 8:
            hit = s[0] / s[1] * 100
            parts.append('【同档校准】%d-%d%% 档归档 %d 场命中 %.1f%%（本场 %+.1f 个百分点）。'
                         % (band(mp), band(mp) + 5, s[1], hit, mp - hit))
        else:
            parts.append('【同档校准】%d-%d%% 档归档不足 8 场，样本不足不给命中基准。' % (band(mp), band(mp) + 5))
        lg = m.get('lg') or ''
        ls = lg_stat.get(lg)
        if ls and ls[1] >= 8:
            parts.append('【联赛平局特性】%s 归档 %d 场平局 %.1f%%，本场模型平局 %.1f%%。'
                         % (lg, ls[1], ls[0] / ls[1] * 100, p[1]))
        elif total:
            parts.append('【联赛平局特性】%s 归档不足 8 场；全样本平局率 %.1f%% 作参照。'
                         % (lg or '本场联赛', draw_all / total * 100))
        hr, ar = m.get('hrank'), m.get('arank')
        if hr and ar:
            gap = int(ar) - int(hr)
            side = ('主队位次领先 %d 位' % gap) if gap > 0 else (
                ('客队位次领先 %d 位' % (-gap)) if gap < 0 else '两队位次持平')
            mood = ('主推与名次同向，信心维持' if (main == '主胜' and gap > 0) or (main == '客胜' and gap < 0)
                    else ('主推与名次逆向，降一档看待' if abs(gap) >= 6 else '名次差不大，按中性看'))
            parts.append('【名次·战意】%s 第 %s 名 vs %s 第 %s 名，%s；%s。'
                         % (m.get('h'), hr, m.get('a'), ar, side, mood))
        # 冷门指数：赔率越集中、平局越热、名次越逆，越容易爆冷
        cold = 0
        gap_p = mp - p[alt_i]
        if gap_p < 12:
            cold += 30
        if p[1] >= 27:
            cold += 25
        if hr and ar and abs(int(hr) - int(ar)) >= 6 and (
                (main == '主胜' and int(hr) - int(ar) <= -6) or (main == '客胜' and int(hr) - int(ar) >= 6)):
            cold += 25
        if m.get('draw_p') and float(m['draw_p']) >= 26:
            cold += 10
        tag = '高' if cold >= 60 else ('中' if cold >= 35 else '低')
        tips = ('串关里别当稳胆，建议避开或降注' if cold >= 60
                else ('可作次选位，不建议单独重注' if cold >= 35 else '可当常规单选'))
        parts.append('【爆冷提示】冷门指数 %d/100（%s）：与次选仅差 %.1f 个百分点%s；%s。'
                     % (cold, tag, gap_p, '，平局热度超 27%' if p[1] >= 27 else '', tips))
        # 退役/告别公告：只挂「标题里明确出现该队」的公开新闻
        _rn = []
        for _t in (m.get('h'), m.get('a')):
            for _x in (rmap.get(_t) or [])[:2]:
                if _x not in _rn:
                    _rn.append(_x)
        if _rn:
            parts.append('【退役·告别公告】%s（公开新闻，仅作背景；不代表本场是告别战）。'
                         % '；'.join(_rn))
        conf = '★★☆☆☆' if mp < 55 else ('★★★☆☆' if mp < 65 else ('★★★★☆' if mp < 75 else '★★★★★'))
        if cold >= 60:
            conf = {'★★★★★': '★★★★☆', '★★★★☆': '★★★☆☆', '★★★☆☆': '★★☆☆☆'}.get(conf, conf)
        parts.append('【结论】主推 %s %.1f%%（%s），次选 %s %.1f%%。胜负彩要串 9 场，'
                     '本场按单场口径仅作一注候选，不做胆。'
                     % (main, mp, conf, LB[alt_i], p[alt_i]))
        m['ana'] = '\n'.join(parts)
        m['ana_base'] = m.get('ana_base') or ('%s vs %s，%s %.1f%%。' % (m.get('h'), m.get('a'), main, mp))
        m['ana_ver'] = 'sfc-enrich'
        m['conf'] = round(mp, 1)
        n += 1

    with io.open(PICK, 'w', encoding='utf-8') as f:
        json.dump(ms, f, ensure_ascii=False, indent=1)
    print('[sfc-enrich] 任九逐场分析 %d/%d 场' % (n, len(ms)))
    return 0


if __name__ == '__main__':
    main()
