#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓任九（胜负彩）14 场欧赔 —— 澳客 m 站

为什么要这个脚本：
  500 的 trade.500.com/sfc/?expect=期号 在开售前只给对阵、赔率按钮没有 data-sp，
  fetch_sfc.py 因此只能写「未开售」。而澳客 m 站（手机 UA）在开售前就已经有
  14 场终盘欧赔，项目《每日更新全流程说明》§2.2 里写死的第一个口子就是它：
      m.okooo.com/zucai/?LotteryNo=期号
  注意：桌面 UA 访问 m.okooo.com 会直接 403「未获授权」，必须用手机 UA。

做法：
  1) 手机 UA 取页面（GBK 解码）
  2) 按 orderid 分 14 个块，逐块抽出：序号/联赛/日期/时间/名次/主客/胜平负赔率
  3) 赔率去水（比例法）→ 三项概率，按最大项定主推
  4) 与 data/sfc_pick.json 按主客队名对齐，把 o/p/rec 回填进去（仍缺的保持 null，不编）
  5) 落盘 data/sfc_okooo.json 留档

用法：
  python scripts/fetch_sfc_okooo.py                # 期号自动取 sfc_pick.json 里的 issue
  python scripts/fetch_sfc_okooo.py --expect 26166
  python scripts/fetch_sfc_okooo.py --no-merge     # 只抓不合并
"""
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
PICK = os.path.join(DATA, 'sfc_pick.json')
OUT = os.path.join(DATA, 'sfc_okooo.json')
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
LB = ['主胜', '平局', '客胜']

RE_ITEM = re.compile(r'<div class="clearfix center listItem" key="\d+">')
RE_ISSUE = re.compile(r'第\s*(\d{5})\s*期')
RE_DEAD = re.compile(r'停售\s*([\d\-]+\s*[\d:]+)')
RE_ROW = re.compile(
    r'(?P<lg>[^\s|]{2,8})[\s|]+(?P<d>\d\d-\d\d)[\s|]+(?P<t>\d\d:\d\d)[\s\S]*?'
    r'\[(?P<hr>\d+)\][\s|]*(?P<h>[^|]{2,12}?)[\s|]*VS[\s|]*(?P<a>[^|]{2,12}?)[\s|]*\[(?P<ar>\d+)\]'
    r'[\s\S]*?胜[\s|]*(?P<o1>[\d.]+)[\s|]*平[\s|]*(?P<o2>[\d.]+)[\s|]*负[\s|]*(?P<o3>[\d.]+)', re.S)


def fetch(expect):
    url = 'https://m.okooo.com/zucai/?LotteryNo=%s' % expect
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Referer': 'https://m.okooo.com/',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        return r.status, r.read().decode('gbk', 'ignore')


def devig(o):
    inv = [1.0 / x for x in o]
    s = sum(inv)
    return [round(x / s * 100, 1) for x in inv]


def parse(html):
    """按 <div class="clearfix center listItem" key="N"> 切场次，逐段取字段。

    注意：联赛名/日期/时间是上一个兄弟 div 里的内容，不在 orderid 块内，
    所以不能用 orderid 切，必须用 listItem 这一层。
    """
    segs = [m.start() for m in RE_ITEM.finditer(html)]
    rows = []
    for k, p in enumerate(segs):
        end = segs[k + 1] if k + 1 < len(segs) else p + 4000
        b = html[p:end]
        mh = re.search(r'ctrl_homename">([^<]{1,14})<', b)
        ma = re.search(r'ctrl_awayname">([^<]{1,14})<', b)
        mo1 = re.search(r'胜\s*([\d.]+)', b)
        mo2 = re.search(r'平\s*([\d.]+)', b)
        mo3 = re.search(r'负\s*([\d.]+)', b)
        if not (mh and ma and mo1 and mo2 and mo3):
            continue
        try:
            o = [float(mo1.group(1)), float(mo2.group(1)), float(mo3.group(1))]
        except ValueError:
            continue
        if not all(x > 1.0 for x in o):
            continue
        mlg = re.search(r'class="liansai"[^>]*>([^<]{1,10})<', b)
        mdate = re.search(r'xuhao">(\d\d-\d\d)<', b)
        mtm = re.search(r'timetxt">(\d\d:\d\d)<', b)
        hr = re.search(r'pm">\[(\d+)\]</cite><em class="ctrl_homename', b)
        ar = re.search(r'ctrl_awayname[^>]*>([^<]*)</em><cite class="pm">\[(\d+)\]', b)
        p = devig(o)
        best = max(range(3), key=lambda i: p[i])
        rows.append({
            'no': '%02d' % (len(rows) + 1),
            'lg': mlg.group(1).strip() if mlg else '',
            'date': mdate.group(1) if mdate else '',
            'tm': mtm.group(1) if mtm else '',
            'h': mh.group(1).strip(),
            'a': ma.group(1).strip(),
            'hrank': int(hr.group(1)) if hr else None,
            'arank': int(ar.group(2)) if ar else None,
            'o': o, 'p': p,
            'rec': LB[best],
            'draw_p': p[1],
            'src': 'okooo-m',
        })
    return rows


def norm(s):
    s = (s or '').strip()
    s = re.sub(r'[（(].*?[)）]', '', s)
    return re.sub(r'[\s·]', '', s)


def merge(pick, rows):
    idx = {}
    for r in rows:
        idx[(norm(r['h']), norm(r['a']))] = r
    hit, miss = 0, []
    for t in pick:
        r = idx.get((norm(t.get('h')), norm(t.get('a'))))
        if not r:
            # 队名口径差异时退一步：主队名互相包含即视为同一场
            for k, v in idx.items():
                if norm(t.get('h')) and (norm(t.get('h')) in k[0] or k[0] in norm(t.get('h'))):
                    r = v
                    break
        if not r:
            miss.append('%s %s vs %s' % (t.get('no'), t.get('h'), t.get('a')))
            continue
        t['o'] = r['o']
        t['odds'] = r['o']
        t['p'] = r['p']
        # 页面读的是 fus/main/main_p（不是 p/rec），只写 p/rec 会导致
        # 卡片上「把握 undefined%」、推荐空 —— 这里把两套字段名都补齐
        t['fus'] = r['p']
        t['main'] = r['rec']
        t['main_p'] = max(r['p'])
        t['draw_p'] = r['draw_p']
        _i = r['p'].index(max(r['p']))
        _lb = ['主胜', '平局', '客胜']
        t['rec'] = _lb[_i]
        _alt = max([j for j in range(3) if j != _i], key=lambda j: r['p'][j])
        t['alt'] = _lb[_alt]
        t['alt_p'] = r['p'][_alt]
        t['gap'] = round(r['p'][_i] - r['p'][_alt], 1)
        t['two'] = False
        t['draw_cand'] = r['p'][1] >= 25.0
        t['no_odds'] = False
        t['src'] = 'okooo-m'
        hit += 1
    return hit, miss


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
    if not expect and pick:
        expect = str(pick[0].get('issue') or '')
    if not expect:
        print('[okooo] 没有期号，跳过')
        return 0
    try:
        st, html = fetch(expect)
    except urllib.error.HTTPError as e:
        print('[okooo] 期 %s 被拒 HTTP %s（桌面 UA 会 403，这里用的是手机 UA）' % (expect, e.code))
        return 0
    except Exception as e:
        print('[okooo] 期 %s 抓取失败：%s' % (expect, str(e)[:80]))
        return 0
    mi = RE_ISSUE.search(html)
    issue = mi.group(1) if mi else expect
    md = RE_DEAD.search(html)
    deadline = md.group(1).strip() if md else ''
    rows = parse(html)
    print('[okooo] 期 %s（页面标注 %s，停售 %s）解析到 %d 场有欧赔'
          % (expect, issue, deadline or '未标注', len(rows)))
    if not rows:
        return 0
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'issue': issue, 'expect': expect, 'deadline': deadline,
                   'src': 'https://m.okooo.com/zucai/?LotteryNo=%s' % expect,
                   'fetched_at': __import__('time').strftime('%Y-%m-%d %H:%M'),
                   'matches': rows}, f, ensure_ascii=False, indent=1)
    print('       落盘 %s' % OUT)
    if '--no-merge' in sys.argv or not pick:
        return 0
    hit, miss = merge(pick, rows)
    with io.open(PICK, 'w', encoding='utf-8') as f:
        json.dump(pick, f, ensure_ascii=False, indent=1)
    print('[okooo] 回填 sfc_pick.json：%d/14 场有赔率' % hit)
    if miss:
        print('[okooo] 未对上：%s' % '；'.join(miss[:5]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
