# -*- coding: utf-8 -*-
"""第三七七条：每日 2串1「一次定稿、永不改动」快照。

解决两个真实问题：
  1) 推荐会随时间/开赛/换日消退或变动 —— 旧版 renderCombos() 每次都从实时 M
     里按 hbGroup===1 重算，比赛一开踢、赔率一刷新、跨到第二天，卡片就变或消失。
  2) 第二天想复盘看不见 —— 旧卡片是纯前端计算的，没有任何落盘。

做法：build 阶段按「销售日」把当天这一注算一次，冻结进 data/combo_history.json，
之后同一天无论重跑多少次都不覆盖；页面只读快照，并按往期列表回看 + 回填赛果。
"""
import io, os, re, json, itertools, datetime, sys

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, 'data', 'combo_history.json')
LIVE = os.path.join(BASE, 'index_live.html')
ARCH = os.path.join(BASE, 'data', '_archive_done.json')
HL = ['主胜', '平局', '客胜']
BEG = '<!--COMBOHIST:BEGIN-->'
END = '<!--COMBOHIST:END-->'


def bj_today():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d')


def sale_day(m):
    """复刻前端 hbSaleDay：凌晨场(tm<06:00)归前一天。"""
    d = m.get('date') or (m.get('kt') or '')[:10] or ''
    if len(d) < 10:
        return d
    tm = m.get('tm') or (m.get('kt') or '')[11:16] or ''
    if tm and tm < '06:00':
        try:
            dt = datetime.date(int(d[:4]), int(d[5:7]), int(d[8:10])) - datetime.timedelta(days=1)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return d
    return d


def read_live():
    s = io.open(LIVE, encoding='utf-8').read()
    m = re.search(r'window\.__LIVE__=(\{.*?\});</script>', s, re.S)
    if not m:
        return []
    try:
        return (json.loads(m.group(1)).get('matches') or [])
    except Exception as e:
        print('[combo_snap] __LIVE__ 解析失败:', e)
        return []


def build_pool(ms, today):
    pool = []
    for m in ms:
        if not isinstance(m, dict):
            continue
        if m.get('ft'):                       # 已开赛/已结束 → 不在候选池
            continue
        if sale_day(m) != today:              # 只取今日销售日
            continue
        ps = m.get('p') or []
        os_ = m.get('o') or m.get('sp') or []
        if not isinstance(ps, list) or len(ps) < 3 or not isinstance(os_, list) or len(os_) < 3:
            continue
        try:
            ps = [float(x) for x in ps[:3]]
            os_ = [float(x) for x in os_[:3]]
        except Exception:
            continue
        best = max(range(3), key=lambda i: ps[i])
        p = ps[best] / 100.0                  # 与前端 m.r.p 同口径（去水概率 0~1）
        o = os_[best]
        if o <= 1.05 or p <= 0:
            continue
        c = max(20, min(95, round(0.75 * ps[best])))
        pool.append({'no': m.get('no') or m.get('num') or '',
                     'h': m.get('h') or '', 'a': m.get('a') or '',
                     'best': best, 'p': p, 'o': o, 'conf': c})
    pool.sort(key=lambda x: -x['p'])
    return pool[:18]


def search(pool, n, lo, hi):
    best = None
    for idx in itertools.combinations(range(len(pool)), n):
        odd, pr = 1.0, 1.0
        for i in idx:
            odd *= pool[i]['o']
            pr *= pool[i]['p']
        if odd < lo or odd > hi:
            continue
        if best is None or pr > best['pr']:
            best = {'pr': pr, 'odd': odd, 'sel': list(idx)}
    return best


def compute(ms, today):
    pool = build_pool(ms, today)
    if len(pool) < 2:
        return None
    cands = []
    for n, name in ((2, '2串1'), (3, '3串1')):
        if len(pool) < n:
            continue
        b, widened = search(pool, n, 2.6, 3.6), False
        if not b:
            b, widened = search(pool, n, 2.2, 4.5), True
        if b:
            cands.append({'n': n, 'name': name, 'best': b, 'widened': widened})
    if not cands:
        return None
    cands.sort(key=lambda x: -x['best']['pr'])
    w = cands[0]
    legs = []
    for i in w['best']['sel']:
        x = pool[i]
        legs.append({'no': x['no'], 'h': x['h'], 'a': x['a'],
                     'pick': HL[x['best']], 'pick_i': x['best'],
                     'odd': round(x['o'], 2), 'p': round(x['p'] * 100, 1),
                     'conf': x['conf'], 'actual': None, 'hit': None})
    return {'date': today, 'name': w['name'],
            'generated': datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),
            'odd': round(w['best']['odd'], 2), 'pr': round(w['best']['pr'], 4),
            'widened': w['widened'], 'legs': legs,
            'result': 'pending', 'frozen': True}


def result_index(ft):
    """'2-1' → 0/1/2；无法解析返回 None。"""
    if not ft:
        return None
    m = re.search(r'(\d+)\s*[-:]\s*(\d+)', str(ft))
    if not m:
        d = {'主胜': 0, '平局': 1, '客胜': 2}
        return d.get(str(ft).strip())
    a, b = int(m.group(1)), int(m.group(2))
    return 0 if a > b else (1 if a == b else 2)


def build_result_index(ms):
    idx = {}
    def put(h, a, ft, real=None):
        if not h or not a:
            return
        ri = result_index(ft)
        if ri is None and real:
            ri = result_index(real)
        if ri is not None:
            idx.setdefault((str(h).strip(), str(a).strip()), (ri, str(ft or real)))
    for m in ms:
        if isinstance(m, dict):
            put(m.get('h'), m.get('a'), m.get('ft'), m.get('real'))
    try:
        ar = json.load(io.open(ARCH, encoding='utf-8'))
        if isinstance(ar, list):
            for m in ar:
                if isinstance(m, dict):
                    put(m.get('h'), m.get('a'), m.get('ft'), m.get('real') or m.get('actual'))
    except Exception:
        pass
    return idx


def refresh_results(hist, ms):
    idx = build_result_index(ms)
    for d, rec in hist.items():
        legs = rec.get('legs') or []
        any_real = False
        all_hit = True
        for lg in legs:
            k = (str(lg.get('h') or '').strip(), str(lg.get('a') or '').strip())
            if k in idx:
                ri, ft = idx[k]
                lg['actual'] = HL[ri] + ('（' + ft + '）' if ft else '')
                lg['hit'] = (lg.get('pick_i') == ri)
                any_real = True
                if not lg['hit']:
                    all_hit = False
            else:
                lg['actual'] = None
                lg['hit'] = None
                all_hit = False
        if not legs:
            rec['result'] = 'pending'
        elif not any_real:
            rec['result'] = 'pending'
        else:
            rec['result'] = 'hit' if all_hit else ('miss' if all(
                lg.get('hit') is not None for lg in legs) else 'partial')
    return hist


def inject(hist, targets):
    payload = json.dumps(hist, ensure_ascii=False, separators=(',', ':'))
    blk = BEG + '\n<script>window.__COMBO_HISTORY__=' + payload + ';</script>\n' + END
    pat = re.compile(re.escape(BEG) + r'.*?' + re.escape(END), re.S)
    for path in targets:
        if not os.path.exists(path):
            continue
        s = io.open(path, encoding='utf-8').read()
        # ★ 先摘掉旧块再重新插到「最早」的位置：块若留在 </body> 附近，
        #   页面里立即执行的 renderCombos() 会先于它跑，读到 0 天 → 走临时计算。
        s = pat.sub('', s)
        anchor = re.search(r'window\.__LIVE__=\{.*?\};</script>', s, re.S)
        if anchor:
            s2 = s[:anchor.end()] + '\n' + blk + s[anchor.end():]
        elif '</head>' in s:
            # index.html 是模板，不含内联 __LIVE__；放 head 里，
            # make_live 下次生成 index_live.html 时会原样带过去再被上移。
            s2 = s.replace('</head>', blk + '\n</head>', 1)
        elif '</body>' in s:
            s2 = s.replace('</body>', blk + '\n</body>', 1)
        else:
            print('[combo_snap] 找不到注入锚点，跳过:', path)
            continue
        io.open(path, 'w', encoding='utf-8').write(s2)
        print('[combo_snap] 注入历史快照:', os.path.basename(path), '天数', len(hist))


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def kick_dt(m):
    kt = m.get('kt') or ((m.get('date') or '') + ' ' + (m.get('tm') or ''))
    try:
        return datetime.datetime.strptime(kt[:19], '%Y-%m-%d %H:%M:%S').replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    except Exception:
        try:
            return datetime.datetime.strptime(kt[:16], '%Y-%m-%d %H:%M').replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        except Exception:
            return None


def choose_day(ms, bootstrap=False):
    """推荐日 = 当前这批在售比赛的销售日，不是死板的自然日。

    凌晨场归前一天（hbSaleDay 口径）；跨过午夜后旧批次仍属于原销售日，
    这正是旧版「卡片随时间消退」的根因 —— hbGroup 用自然日把它们全判成已结束。
    bootstrap=True 时（历史为空）放宽到全部未回填赛果的场次，保证首次也有一注定稿。
    """
    now = now_bj()
    cand = []
    for m in ms:
        if not isinstance(m, dict) or m.get('ft'):
            continue
        k = kick_dt(m)
        if not bootstrap:
            if k is None or k < now - datetime.timedelta(hours=2):
                continue     # 已开赛且早已结束（但赛果未回填）→ 不算今日候选
        cand.append(sale_day(m))
    return max(cand) if cand else bj_today()


def main():
    ms = read_live()
    hist = {}
    if os.path.exists(HIST):
        try:
            hist = json.load(io.open(HIST, encoding='utf-8')) or {}
        except Exception:
            hist = {}
    day = choose_day(ms, bootstrap=not hist)
    if day not in hist:
        rec = compute(ms, day)
        if rec:
            hist[day] = rec
            print('[combo_snap] 新快照 %s: %s %.2f倍 全中%.1f%% (%d腿)' % (
                day, rec['name'], rec['odd'], rec['pr'] * 100, len(rec['legs'])))
        else:
            print('[combo_snap] %s 候选池不足，不写新快照（页面回显最近一次）' % day)
    else:
        print('[combo_snap] %s 已有快照，保持冻结不重算: %s %.2f倍' % (
            day, hist[day].get('name'), hist[day].get('odd', 0)))
    hist = dict(sorted(hist.items()))
    hist = refresh_results(hist, ms)
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    io.open(HIST, 'w', encoding='utf-8').write(
        json.dumps(hist, ensure_ascii=False, indent=1))
    inject(hist, [os.path.join(BASE, 'index.html'), os.path.join(BASE, 'index_live.html')])
    for d in sorted(hist.keys(), reverse=True)[:6]:
        r = hist[d]
        print('  %s  %s %.2f倍  %s' % (d, r['name'], r['odd'], r.get('result')))
    newest = sorted(hist.keys())[-1] if hist else '-'
    if hist:
        nr = hist[newest]
        print('[combo_snap] 定稿 %d 天 · 最新 %s %s %.2f倍（%d腿）· 同日重跑不改写' % (
            len(hist), newest, nr['name'], nr['odd'], len(nr.get('legs') or [])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
