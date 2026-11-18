#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北单情报（澳客版）—— 抓比赛页的「近10场」和「两队交锋」

为什么走澳客：
  odds.500.com 全站被腾讯 EdgeOne 拦（脚本只能拿到 987 字节验证脚本），云端抓不了；
  澳客 m 站手机 UA 全通，且比赛页 /match/history.php?MatchID= 上就有：
    主队近10场X胜X平X负（主场...） / 客队近10场... / 两队交锋 主队X胜X平X负
  这正是北单分析里最缺的「近况 + 交锋」两块。

流程：
  1) /live/?LotteryType=danchang 拿当期北单场次（期号/序号/联赛/让球/主客/时间/MatchID）
  2) 与 engine/data/_bj_latest_full.json 按队名对齐
  3) 逐场取 /match/history.php?MatchID= 解析近况与交锋（限流 0.6s）
  4) 落盘 engine/data/bj_okooo.json：{北单序号: {...}}

用法：
  python scripts/fetch_bj_okooo.py            # 只抓未开赛（默认上限 20 场）
  python scripts/fetch_bj_okooo.py --limit 0  # 不限
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
BJ = os.path.join(DATA, '_bj_latest_full.json')
OUT = os.path.join(DATA, 'bj_okooo.json')
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')

RE_ITEM = re.compile(r'<a[^>]+href="(/match/note\.php\?MatchID=(\d+)[^"]*)"[^>]*>\s*(?:<[^>]+>\s*)*情报')
RE_ROW = re.compile(
    r'\|\s*(?P<no>\d{3})\s*\|\s*(?P<lg>[^|]{1,10})\|[\s\S]*?\|\s*(?P<hcap>[+-]?\d+)\s*\|\s*'
    r'(?P<h>[^|]{2,12})\|\s*\+\d\s*\|\s*\|?\s*(?P<state>[^|]{2,8})\s*\|\s*(?P<tm>\d\d:\d\d)\s*\|\s*'
    r'\|?\s*(?P<a>[^|]{2,12})\|')
RE_H10 = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,10})\|?\s*近10场(\d+)胜(\d+)平(\d+)负(?:，主场(\d+)胜(\d+)平(\d+)负)?')
RE_H2H = re.compile(r'两队交锋\|?主队(\d+)胜(\d+)平(\d+)负(?:，主场(\d+)胜(\d+)平(\d+)负)?')


def get(path, ref='https://m.okooo.com/live/'):
    req = urllib.request.Request('https://m.okooo.com' + path,
                                 headers={'User-Agent': UA, 'Referer': ref})
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


def list_matches():
    """按 <div class="liveItem jsLiveItem"> 逐场取字段。

    页面结构（每场一块）：
      <!--1317046 -->
      <div class="liveItemls">019 <font color=...>巴西甲</font>
      <p class="name fl txtright">科里蒂巴<cite>+1</cite>
      <div class="info-time">未开始</div>
      <span class="bifentxt">06:30</span>
      <p class="name fl txtleft">桑托斯</p>
      ... /match/note.php?MatchID=1317046（情报）
    """
    h = get('/live/?LotteryType=danchang')
    rows = []
    for b in re.split(r'<div class="liveItem jsLiveItem"', h)[1:]:
        mid = re.search(r'<!--\s*(\d{6,})\s*-->', b[:400])
        mno = re.search(r'liveItemls">\s*(\d{3})', b)
        mlg = re.search(r'<font[^>]*>([^<]{1,10})</font>', b)
        mh = re.search(r'name fl txtright">([^<]{2,14})', b)
        ma = re.search(r'name fl txtleft">([^<]{2,14})', b)
        mst = re.search(r'info-time"[^>]*>\s*([^<]{2,8})', b)
        mtm = re.search(r'bifentxt[^>]*>(\d\d:\d\d)', b)
        if not (mno and mh and ma):
            continue
        rows.append({
            'no': mno.group(1), 'lg': (mlg.group(1).strip() if mlg else ''),
            'h': mh.group(1).strip(), 'a': ma.group(1).strip(),
            'state': (mst.group(1).strip() if mst else ''),
            'tm': (mtm.group(1) if mtm else ''),
            'MatchID': (mid.group(1) if mid else ''),
        })
    issues = re.findall(r'(\d{5})期', h)
    for r in rows:
        r['issue'] = issues[0] if issues else ''
    return rows


def parse_match(mid, h, a):
    t = piped(get('/match/history.php?MatchID=%s&from=' % mid))
    d = {'src': 'm.okooo.com/match/history.php?MatchID=' + mid}
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
        if m2.group(4):
            d['h2h']['venue'] = {'w': int(m2.group(4)), 'd': int(m2.group(5)), 'l': int(m2.group(6))}
    return d


def main():
    limit = 20
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    if not os.path.exists(BJ):
        print('[bj-okooo] 没有 _bj_latest_full.json，跳过')
        return 0
    bj = json.load(io.open(BJ, encoding='utf-8'))
    ms = bj.get('matches') or []
    try:
        rows = list_matches()
    except Exception as e:
        print('[bj-okooo] 列表页抓取失败：%s' % str(e)[:80])
        return 0
    print('[bj-okooo] 澳客北单列表 %d 场（当期 %s）' % (len(rows), rows[0]['issue'] if rows else '-'))
    out, done = {}, 0
    for r in rows:
        if r['state'] not in ('未开始', '未', '待'):
            continue
        best, score = None, 0
        for m in ms:
            sc = (1 if similar(r['h'], m.get('h')) else 0) + (1 if similar(r['a'], m.get('a')) else 0)
            if sc > score:
                best, score = m, sc
        if not best or score < 2 or not r['MatchID']:
            continue
        if limit and done >= limit:
            break
        try:
            d = parse_match(r['MatchID'], best.get('h'), best.get('a'))
        except Exception as e:
            print('   %s vs %s 抓取失败 %s' % (r['h'], r['a'], type(e).__name__))
            continue
        d['pair_okooo'] = '%s vs %s' % (r['h'], r['a'])
        d['match_id'] = r['MatchID']
        d['fetched_at'] = time.strftime('%Y-%m-%d %H:%M')
        out[best['no']] = d
        done += 1
        print('   %s %s vs %s → 近况%s/交锋%s' % (best['no'], best.get('h'), best.get('a'),
                                            'OK' if d.get('home') else '缺',
                                            'OK' if d.get('h2h') else '缺'))
        time.sleep(0.6)
    if not out:
        print('[bj-okooo] 没抓到可用的场次（可能都在进行中/已完赛）')
        return 0
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('[bj-okooo] 落盘 %s · %d 场' % (OUT, len(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
