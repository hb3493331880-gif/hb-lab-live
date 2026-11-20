# -*- coding: utf-8 -*-
"""任九 14 场逐场情报（近况/交锋/伤停/阵容/技术统计/积分榜），走澳客 m 站。

为什么单独写：
  任九期次页（m.okooo.com/zucai/?LotteryNo=期号）本身就带每场的
  `/match/history.php?MatchID=` 链接，所以不需要再猜 matchid；
  而 500 数据页全站被人机验证拦死，云端只能用澳客。

产物：engine/data/sfc_intel.json
  {"01": {h, a, mid, home, away, h2h, inj, value, body, tech, home_rank, away_rank, fetched_at}, ...}

用法：
  python scripts/fetch_sfc_intel.py            # 期号取 sfc_pick.json
  python scripts/fetch_sfc_intel.py --expect 26166
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
PICK = os.path.join(DATA, 'sfc_pick.json')
OUT = os.path.join(DATA, 'sfc_intel.json')
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')

sys.path.insert(0, os.path.join(BASE, 'scripts'))
import fetch_intel_okooo as intel  # noqa: E402  复用 history/form/table 解析

RE_ITEM = re.compile(r'<div class="clearfix center listItem" key="\d+">')


def get_page(expect):
    url = 'https://m.okooo.com/zucai/?LotteryNo=%s' % expect
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Referer': 'https://m.okooo.com/',
                                               'Accept-Language': 'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        return r.read().decode('gbk', 'ignore')


def parse_list(html):
    segs = [m.start() for m in RE_ITEM.finditer(html)]
    out = []
    for k, p in enumerate(segs):
        end = segs[k + 1] if k + 1 < len(segs) else p + 4000
        b = html[p:end]
        mh = re.search(r'ctrl_homename">([^<]{1,14})<', b)
        ma = re.search(r'ctrl_awayname">([^<]{1,14})<', b)
        mid = re.search(r'/match/history\.php\?MatchID=(\d{6,7})', b)
        if not (mh and ma and mid):
            continue
        out.append({'no': '%02d' % (len(out) + 1),
                    'h': mh.group(1).strip(), 'a': ma.group(1).strip(),
                    'mid': mid.group(1)})
    return out


def main():
    expect = None
    if '--expect' in sys.argv:
        expect = sys.argv[sys.argv.index('--expect') + 1]
    pick = []
    if os.path.exists(PICK):
        try:
            pick = json.load(io.open(PICK, encoding='utf-8'))
        except Exception:
            pick = []
    expect = expect or (str(pick[0].get('issue') or '') if pick else '')
    if not expect:
        print('[sfc-intel] 没有期号，跳过')
        return 0
    try:
        html = get_page(expect)
    except Exception as e:
        print('[sfc-intel] 期次页抓取失败：%s' % str(e)[:70])
        return 0
    rows = parse_list(html)
    print('[sfc-intel] 期 %s 解析到 %d 场（含 MatchID）' % (expect, len(rows)))
    if not rows:
        return 0
    coach = {}
    try:
        coach = json.load(io.open(os.path.join(DATA, 'coach_map.json'), encoding='utf-8'))
    except Exception:
        coach = {}
    out, hit = {}, 0
    for r in rows:
        one = {'h': r['h'], 'a': r['a'], 'mid': r['mid']}
        try:
            one.update(intel.parse_history(r['mid'], r['h'], r['a']))
            one.update(intel.parse_form(r['mid'], r['h'], r['a']))
            one.update(intel.parse_table(r['mid'], r['h'], r['a']))
        except Exception as e:
            print('   %s %s vs %s 失败 %s' % (r['no'], r['h'], r['a'], type(e).__name__))
            continue
        # 教练：coach_map 里按队名模糊匹配（有就写，没有不编）
        for side, team in (('home', r['h']), ('away', r['a'])):
            for k, v in coach.items():
                if intel.similar(k, team):
                    one[side + '_coach'] = v
                    break
        one['fetched_at'] = time.strftime('%Y-%m-%d %H:%M')
        out[r['no']] = one
        hit += 1
        print('   %s %s vs %s → 近况%s 伤停%s 榜%s'
              % (r['no'], r['h'], r['a'], 'OK' if one.get('home') else '缺',
                 one.get('inj', '缺'), 'OK' if one.get('home_rank') or (one.get('home') or {}).get('rank') else '缺'))
        time.sleep(0.5)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'issue': expect, 'fetched_at': time.strftime('%Y-%m-%d %H:%M'),
                   'matches': out}, f, ensure_ascii=False, indent=1)
    print('[sfc-intel] 落盘 %s · %d 场' % (OUT, hit))
    return 0


if __name__ == '__main__':
    sys.exit(main())
