# -*- coding: utf-8 -*-
"""澳客赛果抓取（给复盘用）：m.okooo.com/live/ 页面里每场都带终场比分。

为什么不用 500：odds.500.com 全站是 EdgeOne 人机验证，抓一次要过一次验证；
澳客用 iPhone UA 直连 200，不需要验证，所以赛果也只认澳客。

用法：python3 scripts/fetch_results_okooo.py [days]
  默认回看 7 天，写成 data/results_index.json：{"(主队,客队)": "2-1"} 形式不行（JSON 键只能字符串），
  所以落成 {"rows": [{"date":..,"h":..,"a":..,"ft":"2-1"}]}，由 fix_today 建索引。
"""
import io, json, os, re, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
if not os.path.isdir(DATA):
    DATA = os.path.join(BASE, 'data')
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')

ITEM = re.compile(r'<div class="live-list-item[^"]*"\s*matchid="(\d+)">([\s\S]*?)(?=<div class="live-list-item|<div class="live-list-box|</body>)')
DAYTIT = re.compile(r'<span class="fr">(\d+)月(\d+)日')
TEAM = re.compile(r'<div class="match-team">([^<]*)</div>')
SCORE = re.compile(r'<div class="info-score"[^>]*>([^<]*)</div>')
LEG = re.compile(r'<div class="liveItemls">([^<]*)</div>')
TIME = re.compile(r'<div class="info-time"[^>]*>([^<]*)</div>')


def fetch(url, _retry=3):
    for i in range(_retry):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Referer': 'https://m.okooo.com/live/',
                'Accept-Language': 'zh-CN,zh;q=0.9'})
            raw = urllib.request.urlopen(req, timeout=25).read()
            for enc in ('gb18030', 'utf-8'):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
            return raw.decode('gb18030', 'ignore')
        except Exception as e:
            if i == _retry - 1:
                print('  抓取失败 %s %s' % (url, e))
                return ''
            time.sleep(2)


def parse(html, date):
    rows = []
    days = [(int(a), int(b)) for a, b in DAYTIT.findall(html)]
    # 每个 live-list-box 前有一个日期标题，按出现位置把区块对到日期
    box_dates, marks = [], [m.start() for m in DAYTIT.finditer(html)]
    for d in days:
        box_dates.append(d)
    for m in ITEM.finditer(html):
        body = m.group(2)
        teams = [t.strip() for t in TEAM.findall(body)]
        sc = SCORE.findall(body)
        if len(teams) < 2:
            continue
        ft = (sc[0] or '').strip() if sc else ''
        if not re.match(r'^\d+-\d+$', ft):
            continue
        # 该条目前面最近的一个日期标题，就是它的比赛日
        k = max([i for i, pos in enumerate(marks) if pos <= m.start()] or [0])
        mm, dd = days[k] if days else (0, 0)
        y = date[:4]
        if mm and date[5:7] and int(date[5:7]) >= 11 and mm <= 2:   # 跨年
            y = str(int(y) + 1)
        dt = '%s-%02d-%02d' % (y, mm, dd) if mm else date
        rows.append({'date': dt, 'h': teams[0], 'a': teams[1], 'ft': ft})
    return rows


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    today = time.strftime('%Y-%m-%d')
    all_rows = []
    # 首页覆盖当前在售窗口（可能跨 4 天）
    all_rows += parse(fetch('https://m.okooo.com/live/'), today)
    for k in range(1, days + 1):
        d = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400 * k))
        html = fetch('https://m.okooo.com/live/?date=' + d)
        if html:
            all_rows += parse(html, d)
    seen, uniq = set(), []
    for r in all_rows:
        key = (r['h'], r['a'], r['ft'])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    with io.open(os.path.join(DATA, 'results_index.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M:%S'), 'rows': uniq},
                  f, ensure_ascii=False, indent=1)
    print('  [results] 澳客赛果 %d 条（回看 %d 天）' % (len(uniq), days))


if __name__ == '__main__':
    main()
