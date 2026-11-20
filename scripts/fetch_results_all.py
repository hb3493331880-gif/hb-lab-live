# -*- coding: utf-8 -*-
"""全量赛果回填（竞彩/北单/任九 通用）

来源：澳客「竞彩赛果公告」页
  https://www.okooo.com/jingcai/kaijiang/?StartDate=YYYY-MM-DD&EndDate=YYYY-MM-DD
该页按日期返回表格：场次号 | 联赛 | 时间 | 主队 | 客队 | 半场 | 全场 | 胜平负赔率 …
任九 14 场、北单、竞彩都在同一张表里（按队名即可回填）。

输出：
  engine/data/results_all.json  [{order, lg, date, h, a, ht, ft, dir}]
"""
import io
import json
import os
import re
import urllib.request
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'engine', 'data', 'results_all.json')
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HDR = {"User-Agent": UA, "Referer": "https://www.okooo.com/jingcai/"}
ORDER = re.compile(r'^(周[一二三四五六日]\d{3})$')
DATE = re.compile(r'(\d{2}-\d{2})\s+(\d{2}:\d{2})')
SCORE = re.compile(r'^\d{1,2}-\d{1,2}$')


def fetch(d):
    u = ('https://www.okooo.com/jingcai/kaijiang/?StartDate=%s&EndDate=%s' % (d, d))
    raw = urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=30).read()
    return raw.decode('gb18030', 'ignore')


def dir_of(ft):
    if not ft or '-' not in ft:
        return None
    a, b = ft.split('-')[:2]
    try:
        a, b = int(a), int(b)
    except ValueError:
        return None
    return '主胜' if a > b else ('平局' if a == b else '客胜')


def parse(html, ymd):
    rows = re.findall(r'<tr[\s\S]*?</tr>', html)
    out = []
    for r in rows:
        cells = re.sub(r'<[^>]+>', '|', r)
        parts = [c.strip() for c in re.split(r'\|', cells)]
        parts = [c for c in parts if c and c != '指数']
        oi = next((i for i, c in enumerate(parts) if ORDER.match(c)), None)
        if oi is None:
            continue
        order = parts[oi]
        lg = parts[oi + 1] if oi + 1 < len(parts) else ''
        # 时间
        ti = next((i for i in range(oi + 1, min(oi + 5, len(parts)))), None)
        dt = ''
        for i in range(oi, min(oi + 6, len(parts))):
            m = DATE.search(parts[i])
            if m:
                dt = parts[i]
                ti = i
                break
        h = parts[ti + 1] if ti is not None and ti + 1 < len(parts) else ''
        a = parts[ti + 2] if ti is not None and ti + 2 < len(parts) else ''
        if not h or not a:
            continue
        scores = [c for c in parts[ti + 3: ti + 9] if SCORE.match(c)]
        if not scores:
            continue
        ft = scores[-1]
        ht = scores[0] if len(scores) > 1 else None
        md = DATE.search(dt) if dt else None
        d = ('%s-%s' % (ymd[:4], md.group(1))) if md else ymd
        out.append({'order': order, 'lg': lg, 'date': d, 'h': h, 'a': a,
                    'ht': ht, 'ft': ft, 'dir': dir_of(ft)})
    return out


def main():
    today = date.today()
    rows = []
    for k in range(0, 12):
        d = (today - timedelta(days=k)).isoformat()
        try:
            html = fetch(d)
        except Exception as e:
            print('  跳过 %s %s' % (d, e))
            continue
        got = parse(html, d)
        rows += got
        print('%s  %d 场' % (d, len(got)))
    # 去重（同场次+同队名）
    seen = {}
    for r in rows:
        seen[(r['order'], r['h'], r['a'])] = r
    rows = list(seen.values())
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print('[results] 共 %d 场 → %s' % (len(rows), OUT))


if __name__ == '__main__':
    main()
