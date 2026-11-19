# -*- coding: utf-8 -*-
"""每日抓取：中国体彩官方竞彩（胜平负 had）→ data/full.json

数据源：https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry
        （官方公开接口，需 UA + Referer，失败即退出码 0 保留旧数据，绝不写空文件）

模型：欧赔去水 → 泊松反解 λ → 比分分布 → 主推/备选/双选/格局
      （与 refrefresh.py 里的 devig / poisson3 / fit_lam / model 完全同一套口径）
"""
import json, math, os, sys, time, datetime
import urllib.request, ssl

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
API = ('https://webapi.sporttery.cn/gateway/uniform/football/'
       'getMatchCalculatorV1.qry?poolCode=had&channel=c')
LB = ['主胜', '平局', '客胜']


# ---------------- 模型 ----------------
def devig(o):
    s = 1 / o[0] + 1 / o[1] + 1 / o[2]
    return [1 / o[0] / s, 1 / o[1] / s, 1 / o[2] / s]


def pk(l, k):
    return math.exp(-l) * l ** k / math.factorial(k)


def poisson3(lh, la):
    h = d = a = 0.0
    for i in range(9):
        for j in range(9):
            p = pk(lh, i) * pk(la, j)
            if i > j:
                h += p
            elif i == j:
                d += p
            else:
                a += p
    return h, d, a


def fit_lam(ph, pd_, pa):
    best, bd = (1.2, 1.0), 9e9
    for lh in [x * 0.1 for x in range(3, 45)]:
        for la in [x * 0.1 for x in range(3, 45)]:
            h, d, a = poisson3(lh, la)
            e = (h - ph) ** 2 + (d - pd_) ** 2 + (a - pa) ** 2
            if e < bd:
                bd, best = e, (lh, la)
    lh0, la0 = best
    bd2, best2 = bd, best
    for i in range(-10, 11):
        for j in range(-10, 11):
            lh, la = lh0 + i * 0.01, la0 + j * 0.01
            if lh <= 0 or la <= 0:
                continue
            h, d, a = poisson3(lh, la)
            e = (h - ph) ** 2 + (d - pd_) ** 2 + (a - pa) ** 2
            if e < bd2:
                bd2, best2 = e, (lh, la)
    return best2[0], best2[1]


def top_scores(lh, la, n=8):
    out = []
    for i in range(7):
        for j in range(7):
            out.append(('%d-%d' % (i, j), pk(lh, i) * pk(la, j)))
    out.sort(key=lambda x: -x[1])
    return out[:n]


def model(o):
    p = devig(o)
    lh, la = fit_lam(p[0], p[1], p[2])
    ts = top_scores(lh, la, 8)
    return {
        'p': [round(x * 100, 1) for x in p],
        'lh': round(lh, 2), 'la': round(la, 2),
        'tot': round(lh + la, 1),
        'top': [{'s': s, 'p': round(v * 100, 1)} for s, v in ts],
        'margin': round(sum(1 / x for x in o) - 1, 4),
    }


def gen_ana(t):
    """一句话解读：概率 → 把握度 → 风险点 → 进球预期 → 比分主推"""
    p, order = t['p'], sorted(range(3), key=lambda i: -t['p'][i])
    main, mp = LB[order[0]], p[order[0]]
    grip = '把握较大' if mp >= 55 else ('把握一般' if mp >= 45 else '把握有限，倾向谨慎')
    draw_note = ''
    if order[0] != 1 and p[1] >= 30:
        draw_note = '平局 %.1f%%，是本场最大风险。' % p[1]
    return ('%s主场迎战%s。%s%s、%.1f%%，%s。%s进球预期%.1f球。比分主推 %s。'
            % (t['h'], t['a'], main, ('%.2f' % t['o'][order[0]]), mp, grip,
               draw_note, t['tot'], '、'.join(t['top3'])))


def enrich(t):
    """补齐渲染层字段（缺一个就整块静默崩，见 refresh.py 第二九八条）"""
    p = t['p']
    order = sorted(range(3), key=lambda i: -p[i])
    t['lbl'] = LB
    t['sp'] = t['odds']
    t['num'] = t['no']
    t['kt'] = ('%s %s:00' % (t['date'], t['tm'])) if (t['date'] and t['tm']) else t['date']
    t['main'] = LB[order[0]]
    t['main_p'] = p[order[0]]
    t['alt'] = LB[order[1]]
    t['alt_p'] = p[order[1]]
    t['gap'] = round(p[order[0]] - p[order[1]], 1)
    t['two'] = t['gap'] < 8
    t['feat'] = ('小球格局' if t['tot'] < 2.3 else
                 ('中等进球量' if t['tot'] < 2.9 else '对攻格局'))
    t['draw_p'] = p[1]
    t['top3'] = [x['s'] for x in t['top'][:3]]
    t['ana'] = gen_ana(t)
    return t


# ---------------- 抓取 ----------------
def http_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': 'https://www.sporttery.cn/',
        'Accept': 'application/json, text/plain, */*'})
    with urllib.request.urlopen(req, timeout=25,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def fetch_jc():
    j = http_json(API)
    if not j.get('success'):
        raise RuntimeError('接口 success=false')
    out = []
    for grp in (j.get('value') or {}).get('matchInfoList', []):
        for m in grp.get('subMatchList', []):
            had = m.get('had') or {}
            o = []
            for k in ('h', 'd', 'a'):
                v = had.get(k)
                o.append(0.0 if v in (None, '', '-') else float(v))
            if min(o) <= 1.01:
                continue                      # 未开售，不编造
            import re
            hr = re.search(r'\[(\w+?)(\d+)\]', m.get('homeRank') or '')
            ar = re.search(r'\[(\w+?)(\d+)\]', m.get('awayRank') or '')
            t = {
                'no': str(m.get('matchNumStr') or m.get('matchNum') or ''),
                'lg': m.get('leagueAbbName') or m.get('matchName') or '',
                'date': m.get('matchDate') or '',
                'tm': (m.get('matchTime') or '')[:5],
                'h': m.get('homeTeamAbbName') or m.get('homeTeamAllName') or '',
                'a': m.get('awayTeamAbbName') or m.get('awayTeamAllName') or '',
                'hrank': int(hr.group(2)) if hr else None,
                'arank': int(ar.group(2)) if ar else None,
                'hrank_lg': hr.group(1) if hr else None,
                'arank_lg': ar.group(1) if ar else None,
                'o': o, 'odds': list(o), 'src': '官方webapi',
            }
            t.update(model(o))
            out.append(enrich(t))
    return out


def main():
    t0 = time.time()
    try:
        ms = fetch_jc()
    except Exception as e:
        print('[fetch] 失败：%s: %s' % (type(e).__name__, e))
        print('[fetch] 保留上一版数据，本次不写文件')
        return 0                    # 退出码 0：不打断 workflow，不产生空提交
    if not ms:
        print('[fetch] 0 场（可能全部未开售），保留旧数据')
        return 0

    p = os.path.join(DATA, 'full.json')
    old = {}
    if os.path.exists(p):
        try:
            old = json.load(open(p, encoding='utf-8'))
        except Exception:
            old = {}
    full = dict(old)
    full['matches'] = ms
    full['generated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    full['source'] = '官方 webapi.sporttery.cn getMatchCalculatorV1（竞彩 had，%d 场）' % len(ms)
    full['official_update'] = full['generated']
    full['official_source'] = 'sporttery.cn'
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(full, f, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)
    print('[fetch] %d 场 · %.1fs · 期号/队名示例：%s %s vs %s'
          % (len(ms), time.time() - t0, ms[0]['no'], ms[0]['h'], ms[0]['a']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
