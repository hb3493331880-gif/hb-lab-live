#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全自动情报（澳客三页）—— 替代被封的 500 数据页

为什么换掉 500：
  odds.500.com 全站挂腾讯 EdgeOne 人机验证（脚本只拿到 988 字节验证脚本，
  连按脚本算出 __tst_status / EO_Bot_Ssid 再带着请求也照样被拒），
  所以「必须有人点一下浏览器」并不是必要的，而是我们选错了数据源。
  澳客 m 站同样有这几块，且国内/云主机都能直连、零验证：
    /match/history.php  近10场战绩 + 两队交锋
    /match/form.php     伤停（有名字才写）+ 阵容对比（身价/身高/年龄/首发/前中后）+ 场均技术统计
    /match/game.php     联赛积分榜（排名/已赛/胜平负/进失/积分）→ 战意判断

产物 engine/data/intel_okooo.json：
  {"竞彩序号": {...}, "北单序号": {...}}  —— 两边同队同名时复用同一份

用法：
  python scripts/fetch_intel_okooo.py            # 竞彩 + 北单未开赛
  python scripts/fetch_intel_okooo.py --only jc  # 只跑竞彩
"""
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
FULL = os.path.join(DATA, 'full.json')
BJ = os.path.join(DATA, '_bj_latest_full.json')
OUT = os.path.join(DATA, 'intel_okooo.json')
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')

RE_H10 = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,10})\|?\s*近10场(\d+)胜(\d+)平(\d+)负(?:，主场(\d+)胜(\d+)平(\d+)负)?')
RE_H2H = re.compile(r'两队交锋\|?主队(\d+)胜(\d+)平(\d+)负(?:，主场(\d+)胜(\d+)平(\d+)负)?')
RE_ITEM = re.compile(r'<div class="liveItem jsLiveItem"')
RE_TECH = {
    'shot': re.compile(r'([\d.]+)\|次\| \|([\d.]+)\|次\| \|场均射门\| ([\d.]+)\|次\| \|([\d.]+)\|次'),
    'goal': re.compile(r'([\d.]+)\|个\| \|([\d.]+)\|个\| \|场均进球\| ([\d.]+)\|个\| \|([\d.]+)\|个'),
    'loss': re.compile(r'([\d.]+)\|个\| \|([\d.]+)\|个\| \|场均失球\| ([\d.]+)\|个\| \|([\d.]+)\|个'),
    'poss': re.compile(r'([\d.]+)\|%\| \|([\d.]+)\|%\| \|场均控球率\| ([\d.]+)\|%\| \|([\d.]+)\|%'),
}


def get(path):
    req = urllib.request.Request('https://m.okooo.com' + path,
                                headers={'User-Agent': UA, 'Referer': 'https://m.okooo.com/'})
    with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
        return r.read().decode('gbk', 'ignore')


def piped(html):
    t = re.sub(r'<script.*?</script>', '', html, flags=re.S)
    t = re.sub(r'<[^>]+>', '|', t)
    t = re.sub(r'\|+', '|', t)
    return re.sub(r'\s+', ' ', t)


def norm(s):
    s = (s or '').strip()
    s = re.sub(r'[（(].*?[)）]', '', s)
    return re.sub(r'[\s·]', '', s)


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a in b or b in a or len(set(a) & set(b)) >= 2


def list_ids(lottery):
    """从澳客列表页取 [(no, h, a, MatchID)]"""
    path = '/live/?LotteryType=danchang' if lottery == 'bj' else '/live/'
    h = get(path)
    out = []
    for b in RE_ITEM.split(h)[1:]:
        mid = re.search(r'<!--\s*(\d{6,})\s*-->', b[:400])
        mno = re.search(r'liveItemls">\s*(\d{3})', b)
        mh = re.search(r'name fl txtright">([^<]{2,14})', b)
        ma = re.search(r'name fl txtleft">([^<]{2,14})', b)
        if not (mid and mh and ma):
            continue
        out.append({'no': mno.group(1) if mno else '', 'h': mh.group(1).strip(),
                    'a': ma.group(1).strip(), 'mid': mid.group(1)})
    return out


def parse_history(mid, h, a):
    t = piped(get('/match/history.php?MatchID=%s&from=' % mid))
    d = {}
    tens = RE_H10.findall(t)
    for team, w, dr, l, hw, hd, hl in tens:
        one = {'w': int(w), 'd': int(dr), 'l': int(l)}
        if hw:
            one['venue'] = {'w': int(hw), 'd': int(hd), 'l': int(hl)}
        if similar(team, h) and 'home' not in d:
            d['home'] = one
        elif similar(team, a) and 'away' not in d:
            d['away'] = one
        elif 'home' not in d:
            d['home'] = one
        elif 'away' not in d:
            d['away'] = one
    m2 = RE_H2H.search(t)
    if m2:
        d['h2h'] = {'w': int(m2.group(1)), 'd': int(m2.group(2)), 'l': int(m2.group(3))}
    return d


def parse_form(mid, h, a):
    t = piped(get('/match/form.php?MatchID=%s&from=' % mid))
    d = {'src': 'okooo-/match/form.php'}
    # 伤停：页头「伤停身价」前若有「无缺阵」就是没有；否则尽量把名字捞出来
    inj = []
    for seg in re.findall(r'([^|]{0,30})\|伤停身价', t):
        s = seg.strip()
        if s and '无缺阵' not in s:
            inj.append(s[-12:])
    d['inj'] = '无缺阵' if '无缺阵' in t else ('；'.join(inj) if inj else '未采集')
    # 身价：阵容实力对比里两个「万/亿」开头的数
    money = re.findall(r'\|([\d.]+)\|(亿|万)\|', t)
    if money:
        vals = ['%s%s' % (m[0], m[1]) for m in money[:2]]
        d['value'] = vals
    # 平均身高/年龄：形如 180cm/30岁
    ha = re.findall(r'(\d{3})cm/(\d{2})岁', t)
    if ha:
        d['body'] = ['%scm/%s岁' % x for x in ha[:2]]
    # 技术统计：页面把数字写在标签左边（主队/客队各一组，含全部与主/客场），
    # 所以按 token 位置取标签两侧最近的数字，而不是靠固定空格
    toks = [x.strip() for x in t.split('|')]
    toks = [x for x in toks if x]
    tech = {}
    for label, key in (('场均射门', 'shot'), ('场均进球', 'goal'),
                       ('场均失球', 'loss'), ('场均控球率', 'poss')):
        try:
            i = toks.index(label)
        except ValueError:
            continue
        nums = lambda seg: [float(x) for x in seg if re.fullmatch(r'[\d.]+', x)]
        before, after = nums(toks[max(0, i - 8):i]), nums(toks[i + 1:i + 9])
        if len(before) >= 2 and len(after) >= 2:
            tech[key] = {'home': {'all': before[-2], 'venue': before[-1]},
                         'away': {'all': after[0], 'venue': after[1]}}
    if tech:
        d['tech'] = tech
    return d


def parse_table(mid, h, a):
    t = piped(get('/match/game.php?MatchID=%s&from=' % mid))
    rows = re.findall(r'\|(\d{1,2})\| \|([^|]{2,12})\| \|(\d{1,2})\| \|(\d{1,2})\| \|(\d{1,2})\| \|(\d{1,2})\| \|(\d{1,3})\| \|(\d{1,3})\| \|(\d{1,3})\|', t)
    d = {}
    for r in rows:
        rank, team, pl, w, dr, l, gf, ga, pts = r
        one = {'rank': int(rank), 'played': int(pl), 'w': int(w), 'd': int(dr), 'l': int(l),
               'gf': int(gf), 'ga': int(ga), 'pts': int(pts), 'team': team.strip()}
        if similar(team, h) and 'home' not in d:
            d['home'] = one
        elif similar(team, a) and 'away' not in d:
            d['away'] = one
    return d


def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]
    targets = []
    if only in (None, 'jc') and os.path.exists(FULL):
        for m in (json.load(io.open(FULL, encoding='utf-8')).get('matches') or []):
            targets.append(('jc', m.get('no'), m.get('h'), m.get('a')))
    if only in (None, 'bj') and os.path.exists(BJ):
        for m in (json.load(io.open(BJ, encoding='utf-8')).get('matches') or []):
            if m.get('ft'):
                continue
            targets.append(('bj', m.get('no'), m.get('h'), m.get('a')))
    if not targets:
        print('[intel-okooo] 没有待抓场次')
        return 0
    idmap = {}
    try:
        for r in list_ids('bj') + list_ids('jc'):
            idmap[(norm(r['h']), norm(r['a']))] = r['mid']
    except Exception as e:
        print('[intel-okooo] 列表页抓取失败：%s' % str(e)[:60])
        return 0
    out, hit = {}, 0
    for kind, no, h, a in targets:
        mid = idmap.get((norm(h), norm(a)))
        if not mid:
            for k, v in idmap.items():
                if norm(h) and (norm(h) in k[0] or k[0] in norm(h)) and norm(a) and (norm(a) in k[1] or k[1] in norm(a)):
                    mid = v
                    break
        if not mid:
            continue
        one = {}
        try:
            one.update(parse_history(mid, h, a))
            one.update(parse_form(mid, h, a))
            one.update(parse_table(mid, h, a))
        except Exception as e:
            print('   %s %s vs %s 失败 %s' % (kind, h, a, type(e).__name__))
            continue
        one['match_id'] = mid
        one['fetched_at'] = time.strftime('%Y-%m-%d %H:%M')
        out['%s:%s' % (kind, no)] = one
        hit += 1
        print('   %s%s %s vs %s → 近况%s 伤停%s 技术%s 积分%s' % (
            kind, no, h, a,
            'OK' if one.get('home') else '缺', one.get('inj', '缺'),
            'OK' if one.get('tech') else '缺', 'OK' if one.get('home', {}).get('rank') else '缺'))
        time.sleep(0.6)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('[intel-okooo] 落盘 %s · %d 场' % (OUT, hit))
    return 0


if __name__ == '__main__':
    sys.exit(main())
