# -*- coding: utf-8 -*-
"""北单（北京单场）直抓 —— 手机版澳客 + 官方 SP 表

来源组合（都无需登录、家宽与 GitHub 机器均可访问）：
  1) https://m.okooo.com/live/?LotteryType=danchang
     给：期号、日期、场次号（024…）、联赛、让球、主客队、开赛时间、MatchID
  2) https://www.okooo.com/Upload/xml/danchang/WDL.xml
     给：按场次号（n=24…）的胜平负 SP（c1=主胜 c3=平 c5=客胜）

输出：engine/data/bj_mobile.json
  {issue, date, count, matches:[{no, order, lg, hcap, h, a, tm, mid, sp:[胜,平,负]}]}
"""
import io
import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'engine', 'data', 'bj_mobile.json')
UA_M = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
UA_PC = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


def get(url, ua, ref=None):
    h = {'User-Agent': ua}
    if ref:
        h['Referer'] = ref
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25).read()


def parse_mobile():
    raw = get('https://m.okooo.com/live/?LotteryType=danchang', UA_M)
    html = raw.decode('gbk', 'ignore')
    m_iss = re.search(r'([\d]{5})期\s*([^<]{0,30})', html)
    issue = m_iss.group(1) if m_iss else ''
    date = (m_iss.group(2) or '').replace('&nbsp;', ' ').strip() if m_iss else ''
    items = re.split(r'<div class="liveItem jsLiveItem"', html)[1:]
    out = []
    for b in items:
        no = (re.search(r'>([\d]{3}) <font', b) or [None, ''])[1]
        lg = (re.search(r'<font color="#[0-9A-Fa-f]+">([^<]{1,10})</font>', b) or [None, ''])[1]
        cap = (re.search(r'live-rf-tip[^>]*>([+-]?\d+)<', b) or [None, ''])[1]
        h, a = '', ''
        names = re.findall(r'class="name[^"]*"[^>]*>([^<]{1,14})', b)
        if len(names) >= 2:
            h, a = names[0], names[1]
        elif names:
            h = names[0]
        tm = (re.search(r'\d\d:\d\d', b) or [None, ''])[0]
        mid = (re.search(r'id="status_(\d+)"', b) or [None, ''])[1]
        if not no or not h:
            continue
        out.append({'no': no, 'order': '北单' + no, 'lg': lg, 'hcap': cap, 'h': h, 'a': a,
                    'tm': tm or '', 'mid': mid or '', 'sp': None})
    return {'issue': issue, 'date': date, 'count': len(out), 'matches': out}


def parse_sp():
    raw = get('https://www.okooo.com/Upload/xml/danchang/WDL.xml', UA_PC,
              'https://www.okooo.com/danchang/').decode('gb18030', 'ignore')
    sp = {}
    for tag in re.findall(r'<w\s+[^>]*/>', raw):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag))
        try:
            n = int(attrs.get('n', ''))
            sp[n] = [float(attrs.get('c1')), float(attrs.get('c3')), float(attrs.get('c5'))]
        except (TypeError, ValueError):
            continue
    return sp


def main():
    d = parse_mobile()
    sp = parse_sp()
    hit = 0
    for m in d['matches']:
        try:
            k = int(m['no'])
        except ValueError:
            continue
        if k in sp:
            m['sp'] = sp[k]
            hit += 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print('[北单] %s期 %s 共 %d 场，其中 %d 场拿到 SP' % (d['issue'], d['date'], d['count'], hit))
    for m in d['matches']:
        print('  %s %s %s vs %s 让%s %s SP=%s' % (m['no'], m['lg'], m['h'], m['a'], m['hcap'], m['tm'], m['sp']))
    print('→', OUT)


if __name__ == '__main__':
    main()
