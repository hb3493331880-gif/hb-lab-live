# -*- coding: utf-8 -*-
"""大乐透：开奖数据抓取 + 冷热/遗漏分析 + 三注选号 → engine/dlt_pick.json

源：https://datachart.500.com/dlt/history/newinc/history.php?start=...&end=...
（官方 getHistoryPageListV1 接口返回 567，做不通，别再试）

评分沿用原项目的三因子权重：历史频率 40% + 近 60 期热度 35% + 遗漏 25%。
玄学层本版只推算年/日干支（节气、月相、卦象未接入），标签里写明，不冒充。
"""
import datetime, json, os, re, ssl, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
GAN = '甲乙丙丁戊己庚辛壬癸'
ZHI = '子丑寅卯辰巳午未申酉戌亥'
WX_OF_GAN = {'甲': '木', '乙': '木', '丙': '火', '丁': '火', '戊': '土',
             '己': '土', '庚': '金', '辛': '金', '壬': '水', '癸': '水'}
ANCHOR = datetime.date(2026, 11, 16)   # 该日甲午（原项目数据实测口径）


def gz(gz_index):
    return GAN[gz_index % 10] + ZHI[gz_index % 12]


def day_gz(d):
    return gz(30 + (d - ANCHOR).days)


def year_gz(d):
    return gz((d.year - 4) % 60)


def get(url, ref='https://datachart.500.com/'):
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


def fetch_draws(start='23001'):
    end = (datetime.date.today() + datetime.timedelta(days=3)).strftime('%y%m%d')
    url = ('https://datachart.500.com/dlt/history/newinc/history.php'
           '?start=%s&end=%s' % (start, end))
    html = get(url)
    draws, seen = [], set()
    for r in re.findall(r'<tr[^>]*>.*?</tr>', html, re.S):
        cs = cells(r)
        if len(cs) < 16 or not re.match(r'^\d{5}$', cs[1] or ''):
            continue
        iss = cs[1]
        if iss in seen:
            continue
        try:
            f = [int(cs[i]) for i in range(2, 7)]
            b = [int(cs[i]) for i in range(7, 9)]
            dt = cs[15]
        except Exception:
            continue
        if len(set(f)) != 5 or len(set(b)) != 2:
            continue
        seen.add(iss)
        draws.append({'iss': iss, 'date': dt, 'f': sorted(f), 'b': sorted(b)})
    draws.sort(key=lambda x: x['iss'])
    return draws


def analyse(draws, pool=95):
    """前区号码的 频率/近60期热度/遗漏 与综合分（0-100）"""
    win = draws[-pool:] if len(draws) > pool else draws
    n = len(win)
    freq = {i: 0 for i in range(1, 36)}
    for d in win:
        for x in d['f']:
            freq[x] += 1
    recent = draws[-60:] if len(draws) > 60 else draws
    hot = {i: 0 for i in range(1, 36)}
    for d in recent:
        for x in d['f']:
            hot[x] += 1
    miss = {}
    for i in range(1, 36):
        miss[i] = len(win)
        for k, d in enumerate(reversed(win)):
            if i in d['f']:
                miss[i] = k
                break
    fmax = max(freq.values()) or 1
    hmax = max(hot.values()) or 1
    mmax = max(miss.values()) or 1
    score = {i: round(0.40 * freq[i] / fmax * 100 + 0.35 * hot[i] / hmax * 100
                      + 0.25 * miss[i] / mmax * 100, 2) for i in range(1, 36)}
    # 后区
    bfreq = {i: 0 for i in range(1, 13)}
    for d in win:
        for x in d['b']:
            bfreq[x] += 1
    bmiss = {}
    for i in range(1, 13):
        bmiss[i] = len(win)
        for k, d in enumerate(reversed(win)):
            if i in d['b']:
                bmiss[i] = k
                break
    return {'n': n, 'freq': freq, 'hot': hot, 'miss': miss, 'score': score,
            'bfreq': bfreq, 'bmiss': bmiss,
            'avg_f': round(sum(freq.values()) / 35.0, 1),
            'avg_b': round(sum(bfreq.values()) / 12.0, 1)}


def tag_of(cnt, avg):
    if cnt >= avg * 1.3:
        return '热号'
    if cnt <= avg * 0.75:
        return '冷号'
    return '温号'


def combo_ok(f, last):
    s = sum(f)
    if not 65 <= s <= 125:
        return False
    if f[-1] - f[0] < 15:
        return False
    odd = sum(1 for x in f if x % 2)
    if not 2 <= odd <= 3:
        return False
    if last and len(set(f) & set(last['f'])) > 1:
        return False
    return True


def pick_plan(score, st, mode, last, used):
    """按综合分取 5 个前区 + 2 个后区，三种风格各取一段"""
    order = sorted(range(1, 36), key=lambda i: -score[i])
    if mode == 'A':          # 高分优先
        cand = order
    elif mode == 'B':        # 均衡：中段温号
        cand = order[5:26]
    else:                    # 冷补：遗漏主导
        cand = sorted(range(1, 36), key=lambda i: (-st['miss'][i], -score[i]))
    for _ in range(200):
        f = sorted(cand[:9][:5]) if False else None
        f = []
        for i in cand:
            if i in used:
                continue
            f.append(i)
            if len(f) == 5:
                break
        f = sorted(f)
        if len(f) == 5 and combo_ok(f, last if mode != 'C' else None):
            break
        cand = cand[1:] + cand[:1]
    if len(f) != 5:
        f = sorted(order[:5])
    border = sorted(range(1, 13), key=lambda i: -score_b(i, st))
    if mode == 'A':
        b = sorted(border[:2])
    elif mode == 'B':
        b = sorted(border[2:4])          # 换一组，避开 A 的后区
    else:
        b = sorted(range(1, 13), key=lambda i: (-st['bmiss'][i], -st['bfreq'][i]))
        b = sorted(b[:2])
    why_f = ['%s：近 %d 期开 %d 次（均 %.1f）' % (tag_of(st['freq'][x], st['avg_f']),
             st['n'], st['freq'][x], st['avg_f']) for x in f]
    why_b = ['%s：近 %d 期开 %d 次（均 %.1f）' % (tag_of(st['bfreq'][x], st['avg_b']),
             st['n'], st['bfreq'][x], st['avg_b']) for x in b]
    return {'f': f, 'b': b, 'sum': sum(f), 'span': f[-1] - f[0],
            'odd': sum(1 for x in f if x % 2),
            'repeat': len(set(f) & set(last['f'])) if last else 0,
            'avgFreq': round(sum(st['freq'][x] for x in f) / 5.0, 1),
            'score': round(sum(score[x] for x in f) / 5.0, 2),
            'why_f': why_f, 'why_b': why_b}


def score_b(i, st):
    """后区综合分，和值 scalar 用同一权重"""
    fmax = max(st['bfreq'].values()) or 1
    mmax = max(st['bmiss'].values()) or 1
    return 0.55 * st['bfreq'][i] / fmax * 100 + 0.45 * st['bmiss'][i] / mmax * 100


def next_draw(draws):
    """下一期期号 + 开奖日（大乐透每周一/三/六）"""
    last = draws[-1]
    try:
        ni = int(last['iss']) + 1
        iss = '%05d' % ni
    except Exception:
        iss = last['iss']
    try:
        d = datetime.date.fromisoformat(last['date'])
    except Exception:
        d = datetime.date.today()
    for k in range(1, 8):
        nd = d + datetime.timedelta(days=k)
        if nd.weekday() in (0, 2, 5):   # 一 三 六
            return iss, nd.isoformat()
    return iss, d.isoformat()


def main():
    try:
        draws = fetch_draws()
    except Exception as e:
        print('[dlt] 抓取失败 %s: %s，保留上一份' % (type(e).__name__, e))
        return 1
    if len(draws) < 30:
        print('[dlt] 只拿到 %d 期，太少，保留上一份' % len(draws))
        return 1

    st = analyse(draws)
    last = draws[-1]
    iss, ndate = next_draw(draws)
    yg, dg = year_gz(datetime.date.fromisoformat(ndate)), day_gz(datetime.date.fromisoformat(ndate))
    wx = WX_OF_GAN[dg[0]]
    label_wx = {'木': '木为根', '火': '火为尊', '土': '土为基',
                '金': '金为锋', '水': '水为源'}[wx]

    score = st['score']
    plans, used = [], set()
    for mode, lab in (('A', label_wx), ('B', '和为贵'), ('C', '补遗漏')):
        p = pick_plan(score, st, mode, last, used)
        used.update(p['f'])
        p['label'] = '%s %s' % (mode, lab)
        p['tag'] = p['label']
        p['wx'] = {wx: 4, '土': 1} if mode == 'A' else {wx: 3, '木': 2}
        p['src'] = '玄学（简版）：%s年 %s日 · 五行取%s' % (yg, dg, wx)
        plans.append(p)

    pick = {
        'issue': iss, 'date': ndate, 'n': st['n'], 'plans': plans,
        'src': ('玄学（简版）%s 期：%s年 %s日 干支推算 · 冷热基于本地 %d 期真实开奖'
                % (iss, yg, dg, st['n'])),
        'last': {'iss': last['iss'], 'f': last['f'], 'b': last['b']},
        'mystic': {'Y': yg, 'D': dg, 'W': {'top': wx},
                   'note': '本版仅推算年/日干支；节气、月相、建除、卦象未接入，不冒充'},
        'srcData': 'https://datachart.500.com/dlt/history/newinc/history.php',
    }
    p1 = os.path.join(BASE, 'engine', 'dlt_pick.json')
    with open(p1 + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(pick, f, ensure_ascii=False, indent=1)
    os.replace(p1 + '.tmp', p1)

    sync = [{'iss': d['iss'], 'date': d['date'], 'f': d['f'], 'b': d['b']}
            for d in sorted(draws, key=lambda x: -int(x['iss']))]
    p2 = os.path.join(DATA, 'dlt_sync.json')
    with open(p2 + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(sync, f, ensure_ascii=False)
    os.replace(p2 + '.tmp', p2)

    print('[dlt] 共 %d 期（最新 %s %s），下一期 %s %s，%d 注已写入'
          % (len(draws), last['iss'], last['date'], iss, ndate, len(plans)))
    for pl in plans:
        print('   ', pl['label'], pl['f'], pl['b'], '和%d 分%.1f' % (pl['sum'], pl['score']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
