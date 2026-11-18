#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 500 数据页（odds.500.com/fenxi/shuju-{fid}.shtml）的页面文本 → intel500.json

为什么要单独一步：500 的赔率域名有腾讯 EdgeOne 人机验证，云端脚本直接抓会拿到验证页。
所以在浏览器里抓下纯文本，落到本地目录，再由本脚本解析成结构化 JSON。
抓取目录默认 E:\\没用\\_intel500（浏览器抓取输出），也可用 --dir 指定。

解析字段（只取页面上明确写着的，取不到就留空，不推断）：
  近10场：胜率 / 胜平负 / 进球 / 失球 / 净胜
  主客场：主队主场、客队客场的胜率与进失球
  场均：总/主/客 的平均入球、平均失球
  阵型：如 4-2-3-1
  交锋：对赛成绩「A 1胜2和7负」
  推介：500 自己给的心水推荐（只当第三方观点引用，不并入模型）
  伤停：页面伤病/停赛栏有名字才记录，空则标"未公布"
"""
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
FULL = os.path.join(DATA, 'full.json')
OUT = os.path.join(DATA, 'intel500.json')
DEF_DIR = r'E:\没用\_intel500'

RE_REC = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,12})\s*近10场战绩\s*胜率\s*(\d+)%\s*'
                    r'(\d+)\s*胜\s*(\d+)\s*平\s*(\d+)\s*负\s*进球\s*(\d+)\s*失球\s*(\d+)\s*净胜\s*(-?\d+)')
RE_HOME_SPLIT = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,12})\s*\n?\s*主场\s*\n([\u4e00-\u9fa5]{0,20})')
RE_FORM = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,12})阵型[:：]\s*([\d\-]+)')
RE_H2H = re.compile(r'对赛成绩\s*-\s*([\u4e00-\u9fa5A-Za-z·\s]+?)\s*(\d+胜\s*\d+和\s*\d+负)')
RE_TIP = re.compile(r'推介\s*-\s*([^\n]{4,60})')
RE_AVG = re.compile(r'平均入球\s*([\d.]+)球\s*([\d.]+)球\s*([\d.]+)球\s*平均失球\s*'
                    r'([\d.]+)球\s*([\d.]+)球\s*([\d.]+)球')


def parse_one(txt):
    d = {}
    recs = RE_REC.findall(txt)
    if recs:
        # 页面顺序：主队总近10 → 客队总近10 → 主队主场近10 → 客队客场近10
        order = ['home', 'away', 'home_home', 'away_away']
        for key, r in zip(order, recs[:4]):
            d[key] = {'team': r[0], 'win_pct': int(r[1]), 'w': int(r[2]),
                      'd': int(r[3]), 'l': int(r[4]), 'gf': int(r[5]),
                      'ga': int(r[6]), 'gd': int(r[7])}
    avg = RE_AVG.findall(txt)
    if avg:
        d['home_avg'] = {'gf': [float(x) for x in avg[0][:3]],
                         'ga': [float(x) for x in avg[0][3:]]}
        if len(avg) > 1:
            d['away_avg'] = {'gf': [float(x) for x in avg[1][:3]],
                             'ga': [float(x) for x in avg[1][3:]]}
    form = RE_FORM.findall(txt)
    if form:
        d['home_form'] = form[0][1]
        if len(form) > 1:
            d['away_form'] = form[1][1]
    h2h = RE_H2H.findall(txt)
    if h2h:
        d['h2h'] = h2h[0][0].strip()
        d['h2h_rec'] = re.sub(r'\s+', '', h2h[0][1])
    tip = RE_TIP.findall(txt)
    if tip:
        d['tip'] = re.sub(r'\s+', ' ', tip[0]).strip()

    # 伤停：页面在两处写"伤病 停赛"，有名字才有内容；只认紧跟在后面的中文姓名串
    seg = txt.split('伤病')
    names = []
    for s in seg[1:]:
        m = re.match(r'[^\n]{0,6}\n?(?:停赛)?\n?([\u4e00-\u9fa5·]{2,6}(?:[\u060c、，][\u4e00-\u9fa5·]{2,6})*)', s)
        if m and m.group(1).strip():
            cand = m.group(1).strip()
            if cand not in ('停赛', '伤停') and len(cand) >= 2:
                names.append(cand)
    if names:
        d['inj'] = '「伤病/停赛」栏列有：' + '；'.join(names[:6])
    return d


def similar(a, b):
    a, b = (a or '').strip(), (b or '').strip()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return len(set(a) & set(b)) >= 2


def main():
    d = DEF_DIR
    if '--dir' in sys.argv:
        d = sys.argv[sys.argv.index('--dir') + 1]
    files = sorted([f for f in os.listdir(d) if f.endswith('.txt')]) if os.path.isdir(d) else []
    if not files:
        print('[intel500] 没有本地抓取目录或目录为空（%s），跳过；线上沿用上一次的 intel500.json' % d)
        return 0
    full = json.load(io.open(FULL, encoding='utf-8'))
    ms = full.get('matches') or []
    intel = {}
    warn = []
    # 500 的队名与体彩口径偶有差异，这里只登记确认过的别名
    alias = {'巴甘蒂诺': '布拉干RB', '巴竞技': '巴拉纳竞技', '弗鲁米嫩塞': '弗鲁米嫩',
             '奥兰多城': '奥兰多', '辛辛那提FC': '辛辛那提', '皇家盐湖城': '盐湖城',
             '西雅图海湾人': '西雅图'}
    used = set()
    for fn in files:
        txt = io.open(os.path.join(d, fn), encoding='utf-8').read()
        title = txt.split('\n', 1)[0]
        parts = title.split('VS')
        t_home, t_away = (parts[0] or ''), (parts[1].split('(')[0] if len(parts) > 1 else '')
        t_home = alias.get(t_home.strip(), t_home.strip())
        t_away = alias.get(t_away.strip(), t_away.strip())
        best, best_score = None, 0
        for m in ms:
            if m['no'] in used:
                continue
            sc = (1 if similar(t_home, m.get('h')) else 0) + (1 if similar(t_away, m.get('a')) else 0)
            if sc > best_score:
                best, best_score = m, sc
        if not best or best_score == 0:
            warn.append('%s（%s）没能对上本地场次，跳过' % (fn, title[:30]))
            continue
        if best_score < 2:
            warn.append('%s 只对上一侧队名：500=%s vs %s / 本地=%s vs %s'
                        % (fn, t_home, t_away, best.get('h'), best.get('a')))
        one = parse_one(txt)
        one['src'] = 'odds.500.com/fenxi/shuju-%s' % fn[:-4]
        one['file'] = fn
        one['pair500'] = t_home + ' vs ' + t_away
        intel[best['no']] = one
        used.add(best['no'])
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(intel, f, ensure_ascii=False, indent=1)
    got = {k: sorted(v.keys()) for k, v in intel.items()}
    print('[intel500] 解析 %d 场 → %s' % (len(intel), OUT))
    for k, v in list(got.items())[:3]:
        print('   ', k, v)
    if warn:
        print('[intel500][警告] ' + '；'.join(warn))
    return 0


if __name__ == '__main__':
    sys.exit(main())
