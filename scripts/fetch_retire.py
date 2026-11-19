# -*- coding: utf-8 -*-
"""退役/告别公告抓取（直播吧足球新闻页）。

为什么用这个源：退役是新闻事件，不是结构化数据。澳客、500 都没有「退役」字段；
懂球帝返回 567 反爬、transfermarkt 返回 202 挑战页；直播吧 `news.zhibo8.com/zuqiu/`
用普通 UA 直连 200，列表里直接能看到「XX 宣布退役」这种标题，日期就在 URL 里。

产出两份：
  engine/data/retire_news.json  → 最近 10 天全部命中关键词的公告（含链接、日期）
  engine/data/retire_map.json   → {队名: ["标题（日期）", ...]}，供逐场分析按队名挂到对应比赛

口径：只搬运公开标题，不推断「他将在本场告别」。标题里没写球队/场次的，就不硬塞给某场比赛。
"""
import io, json, os, re, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
URL = 'https://news.zhibo8.com/zuqiu/'
KW = ('退役', '挂靴', '告别战', '赛季末离队', '最后一战', '宣布退休',
      '卸任', '退队', '告别赛', '挂帅生涯结束', '结束执教')
ITEM = re.compile(r'<a[^>]+href="(?:https?:)?//news\.zhibo8\.com/zuqiu/(\d{4}-\d{2}-\d{2})/([^"]+\.htm)"[^>]*>([^<]{4,80})</a>')


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://news.zhibo8.com/'})
    return urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')


def load(p, d=None):
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return d


def teams_from_engine():
    """把当前在售/在猜的队名收成集合，用来判断公告能不能挂到某场比赛"""
    names = set()
    for f in ('full.json', '_bj_latest_full.json', 'sfc_pick.json'):
        d = load(os.path.join(DATA, f)) or {}
        ms = d.get('matches') if isinstance(d, dict) else d
        for m in (ms or []):
            for k in ('h', 'a'):
                v = (m.get(k) or '').strip()
                if len(v) >= 2:
                    names.add(v)
    return names


def main():
    days = 10
    html = get(URL)
    rows = []
    for d, fn, t in ITEM.findall(html):
        title = t.strip()
        if not any(k in title for k in KW):
            continue
        try:
            ts = time.mktime(time.strptime(d, '%Y-%m-%d'))
        except Exception:
            continue
        if (time.time() - ts) / 86400 > days:
            continue
        rows.append({'date': d, 'title': title,
                     'url': 'https:' + fn if False else 'https://news.zhibo8.com/zuqiu/%s/%s' % (d, fn)})
    seen, uniq = set(), []
    for r in rows:
        if r['title'] in seen:
            continue
        seen.add(r['title'])
        uniq.append(r)

    # 按队名挂靠：标题里出现队名（≥2 字）就归到那条队，短名（拜仁/科隆）也能命中
    tset = teams_from_engine()
    tmap = {}
    for r in uniq:
        for name in list(tset):
            if name and name in r['title']:
                tmap.setdefault(name, []).append('%s（%s）' % (r['title'], r['date']))

    with io.open(os.path.join(DATA, 'retire_news.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M:%S'), 'count': len(uniq),
                   'days': days, 'items': uniq}, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(DATA, 'retire_map.json'), 'w', encoding='utf-8') as f:
        json.dump(tmap, f, ensure_ascii=False, indent=1)
    print('  [retire] 近 %d 天退役/告别公告 %d 条，可挂到本期待猜场次 %d 队'
          % (days, len(uniq), len(tmap)))


if __name__ == '__main__':
    main()
