# -*- coding: utf-8 -*-
"""北单（北京单场）在售抓取 → engine/data/_bj_latest_full.json

源：https://trade.500.com/bjdc/  （GBK 页面）
表格字段：场次 | 赛事 | 时间 | [排名]主队 | 让球 | 客队[排名] | 欧赔(3个拼在一起)+盘口 | 比分 | ...
"""
import datetime, json, os, re, ssl, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
URL = 'https://trade.500.com/bjdc/'


def get(url, ref='https://trade.500.com/'):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': ref})
    with urllib.request.urlopen(req, timeout=30,
                                context=ssl.create_default_context()) as r:
        b = r.read()
        for enc in ('gbk', 'utf-8'):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode('gbk', 'ignore')


def cells(tr):
    out = []
    for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S):
        t = re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip()
        out.append(re.sub(r'\s+', ' ', t))
    return out


def team(s):
    """'[世161] 新加坡' / '巴西 [世5]' → (名称, 排名)"""
    m = re.match(r'\[([^\]]*)\]\s*(.+)$', s)
    if m:
        rk = re.sub(r'[^\d]', '', m.group(1))
        return m.group(2).strip(), (int(rk) if rk else None)
    m = re.match(r'(.+?)\s*\[([^\]]*)\]$', s)
    if m:
        rk = re.sub(r'[^\d]', '', m.group(2))
        return m.group(1).strip(), (int(rk) if rk else None)
    return s.strip(), None


def hcap(s):
    s = (s or '').strip()
    if not s:
        return 0
    try:
        return int(re.sub(r'[^\d\-+]', '', s))
    except Exception:
        return 0


def fund_of(o):
    """欧赔 → 去水后的百分比（页面 fund 字段）"""
    if not o:
        return None
    inv = [1.0 / x for x in o]
    s = sum(inv)
    return [round(x / s * 100, 1) for x in inv]


def main():
    try:
        html = get(URL)
    except Exception as e:
        print('[bjdc] 抓取失败 %s: %s' % (type(e).__name__, e))
        return 1

    dm = re.search(r'(\d{4})-(\d{2})-(\d{2})', html)
    base_day = datetime.date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3))) \
        if dm else datetime.date.today()

    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.S)
    out, seen = [], set()
    for r in rows:
        cs = cells(r)
        if len(cs) < 7 or not cs[0].isdigit():
            continue
        no = int(cs[0])
        if no in seen:
            continue
        tm = re.search(r'(\d{2}):(\d{2})', cs[2])
        if not tm:
            continue
        h, hrank = team(cs[3])
        hc = hcap(cs[4])
        a, arank = team(cs[5])
        if not h or not a or h == a:
            continue
        o = [float(x) for x in re.findall(r'[0-9]+\.[0-9]{2}', cs[6])[:3]]
        if len(o) < 3:
            continue
        hh, mm = int(tm.group(1)), tm.group(2)
        d = base_day + datetime.timedelta(days=1 if hh < 10 else 0)
        ft = cs[7] if len(cs) > 7 and re.match(r'\d+:\d+', cs[7] or '') else ''
        hhcap_txt = cs[6].replace(''.join(re.findall(r'[0-9]+\.[0-9]{2}', cs[6])), '').strip()

        seen.add(no)
        out.append({'no': str(no), 'lg': re.sub(r'第\d+轮.*', '', cs[1]) or cs[1],
                    'tm': '%d/%d %s' % (d.month, d.day, tm.group(0)),
                    'h': h, 'a': a, 'hrank': hrank, 'arank': arank,
                    'sp': o, 'o': o, 'hcap': hc, 'fund': fund_of(o),
                    'ft': ft, 'hcap_txt': hhcap_txt})

    if not out:
        print('[bjdc] 没解析到场次（页面结构可能变了）')
        return 1

    payload = {'updated': base_day.isoformat(),
               'source': '500彩票网北单页面 trade.500.com/bjdc/ 抓取（欧赔为真实抓取）',
               'matches': sorted(out, key=lambda x: int(x['no']))}
    p = os.path.join(DATA, '_bj_latest_full.json')
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)
    # 同时存一份按期号命名的副本，方便回溯
    p2 = os.path.join(DATA, 'bj_%s.json' % base_day.strftime('%Y%m%d'))
    with open(p2, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    ended = sum(1 for x in out if x['ft'])
    print('[bjdc] %d 场写入（已完赛 %d 场，%s 起）' % (len(out), ended, base_day))
    return 0


if __name__ == '__main__':
    sys.exit(main())
