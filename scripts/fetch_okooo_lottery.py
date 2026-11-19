# -*- coding: utf-8 -*-
"""竞彩/北单 官方 SP 备用源：澳客 PC 页（www.okooo.com）。

为什么需要：体彩官方 webapi 对机房 IP 返回 567（GitHub Actions 抓不到），
而澳客的竞彩页、北单页直连 200，页面里就有「周一001 / 联赛 / 队名 / 主平客 SP / 让球盘」。

只做一件事：把页面里的场次解析成结构化 JSON，供 build 在没有官方数据时兜底。
口径与官方一致：sp=[主胜, 平, 客胜]，hcap 为让球数（正=主队让球）。
"""
import io, json, os, re, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

JC_URL = 'https://www.okooo.com/jingcai/'
BJ_URL = 'https://www.okooo.com/danchang/'

BLOCK = re.compile(r'<div class="touzhu_1"[^>]*id="match_(\d+)"[^>]*data-ordercn="(周[^"]*)"[^>]*'
                   r'data-rq="(-?\d+)"[^>]*>', re.S)
SP = re.compile(r'data-sp="([\d.]+)"')


def get(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Referer': 'https://www.okooo.com/',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return raw.decode('gbk', 'ignore')


def parse(html):
    """按 touzhu_1 切块：块内含常规三向 SP 与让球三向 SP。"""
    out = []
    starts = [m.start() for m in BLOCK.finditer(html)]
    if not starts:
        return out
    starts.append(len(html))
    for i in range(len(starts) - 1):
        seg = html[starts[i]:starts[i + 1]]
        head = BLOCK.search(seg)
        if not head:
            continue
        mid, order, rq = head.group(1), head.group(2), int(head.group(3))

        # 队名：主队 title 在 zhud 里，客队 title 在 ked 里
        zh = re.search(r'class="zhum[^"]*" title="([^"]+)"', seg)
        ke = re.search(r'(?:ked|kedd)[^>]*>.*?class="zhum[^"]*" title="([^"]+)"', seg, re.S)
        h = zh.group(1).strip() if zh else ''
        a = ke.group(1).strip() if ke else ''

        # 联赛：第 3 个 a 的 title（saiming）
        lg = ''
        m = re.search(r'class="saiming[^"]*"[^>]*title="([^"]+)"', seg)
        if m:
            lg = m.group(1).strip()

        # 时间
        tm = ''
        m = re.search(r'class="shijian"[^>]*title="比赛时间:([^"]+)"', seg)
        if m:
            tm = m.group(1).strip()

        # 常规 SP：rangqiuspf 之前
        idx = seg.find('rangqiuspf')
        normal = seg[:idx] if idx > 0 else seg
        handicap = seg[idx:] if idx > 0 else ''

        spn = [float(x) for x in SP.findall(normal)][:3]
        sph = [float(x) for x in SP.findall(handicap)][:3]
        if len(spn) < 3:
            continue
        out.append({'mid': mid, 'order': order, 'lg': lg, 'tm': tm,
                    'h': h, 'a': a, 'sp': spn, 'hcap': rq,
                    'sph': sph if len(sph) == 3 else None})
    return out


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'jc'
    url = BJ_URL if which == 'bj' else JC_URL
    try:
        html = get(url)
    except Exception as e:
        print('[okooo-%s] 抓取失败：%s' % (which, str(e)[:90]))
        return 1
    rows = parse(html)
    print('[okooo-%s] %s 解析到 %d 场（%s）' % (which, url, len(rows),
          '；'.join('%s %s vs %s' % (r['order'], r['h'], r['a']) for r in rows[:3])))
    fname = 'bj_okooo_page.json' if which == 'bj' else 'jc_okooo_page.json'
    with io.open(os.path.join(DATA, fname), 'w', encoding='utf-8') as f:
        json.dump({'src': url, 'count': len(rows), 'matches': rows}, f,
                  ensure_ascii=False, indent=1)
    print('       落盘 %s' % fname)
    return 0


if __name__ == '__main__':
    sys.exit(main())
