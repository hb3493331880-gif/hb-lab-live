# -*- coding: utf-8 -*-
"""任九（胜负彩 14 场）抓取 → engine/data/sfc_pick.json

源：https://trade.500.com/sfc/  （GBK 页面，表格 14 行）
注：赔率要等开售后页面才给出（未开售时是 "-"）。有赔率就算模型，
    一场都没有就保留上一期、不写空文件。
"""
import datetime, json, os, re, ssl, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
URL = 'https://trade.500.com/sfc/'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import model, enrich, devig          # 同一套模型，不再复制一份


def get(url, ref='https://trade.500.com/'):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': ref})
    with urllib.request.urlopen(req, timeout=25,
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


def parse_teams(s):
    """'[1]拜仁 VS 科隆[15]' → (主队, 主rank, 客队, 客rank)"""
    s = s.replace('VS', ' VS ')
    left, _, right = s.partition(' VS ')
    left = left.strip()
    right = right.strip()
    mh = re.match(r'\[([^\]]*)\]\s*(.+)$', left)
    ma = re.match(r'(.+?)\s*\[([^\]]*)\]$', right)
    if mh:
        h, hlg, hrank = mh.group(2).strip(), mh.group(1), mh.group(1)
    else:
        h, hlg, hrank = left, '', None
    if ma:
        a, algl, arank = ma.group(1).strip(), ma.group(2), ma.group(2)
    else:
        a, algl, arank = right, '', None
    num = lambda x: int(re.sub(r'[^\d]', '', x)) if x and re.search(r'\d', x) else None
    return h, num(hrank), a, num(arank), hlg, algl


def odds_of(s):
    v = re.findall(r'[0-9]+\.[0-9]{2}', s or '')
    if len(v) >= 3:
        o = [float(x) for x in v[:3]]
        if min(o) > 1.01:
            return o
    return None


def main():
    try:
        html = get(URL)
    except Exception as e:
        print('[sfc] 抓取失败 %s: %s，保留上一期' % (type(e).__name__, e))
        return 0

    m = re.search(r'expect=(\d{5})', html)
    issue = m.group(1) if m else ''
    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.S)
    today = datetime.date.today()
    out, with_odds = [], 0

    for r in rows:
        cs = cells(r)
        if len(cs) < 5 or not cs[0].isdigit() or 'VS' not in cs[3]:
            continue
        no = '%02d' % int(cs[0])
        lg = cs[1]
        tm = re.search(r'(\d{2}-\d{2})\s*(\d{2}:\d{2})', cs[2])
        if not tm:
            continue
        md, hm = tm.group(1), tm.group(2)
        mm = int(md.split('-')[0])
        yy = today.year + (1 if mm < today.month - 6 else 0)
        date = '%d-%s' % (yy, md)
        h, hrank, a, arank, hlg, alag = parse_teams(cs[3])
        o = odds_of(cs[7] if len(cs) > 7 else '')

        t = {'no': no, 'issue': issue, 'lg': lg, 'date': date, 'tm': hm,
             'h': h, 'a': a, 'hrank': hrank, 'arank': arank,
             'hrank_lg': hlg or None, 'arank_lg': alag or None}
        if o:
            with_odds += 1
            t.update({'o': o, 'odds': list(o), 'src': '500sfc'})
            t.update(model(o))
            out.append(enrich(t))
        else:
            out.append({'no': no, 'issue': issue, 'lg': lg, 'date': date, 'tm': hm,
                        'h': h, 'a': a, 'hrank': hrank, 'arank': arank,
                        'hrank_lg': hlg or None, 'arank_lg': alag or None,
                        'no_odds': True, 'o': None, 'odds': None, 'p': None,
                        'src': '未开售'})

    if len(out) < 10:
        print('[sfc] 只解析出 %d 场（不足 14），保留上一期' % len(out))
        return 0
    if with_odds == 0:
        print('[sfc] 第 %s 期 %d 场已抓到，但赔率尚未开售 → 只更新对阵，不算模型' % (issue, len(out)))
        # 仍是真实数据：更新期号与对阵，概率留空（页面按 no_odds 处理）
    p = os.path.join(DATA, 'sfc_pick.json')
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)
    print('[sfc] 第 %s 期 %d 场写入 sfc_pick.json（有赔率 %d 场）' % (issue, len(out), with_odds))
    return 0


if __name__ == '__main__':
    sys.exit(main())
