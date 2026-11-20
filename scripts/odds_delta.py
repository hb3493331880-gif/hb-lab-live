# -*- coding: utf-8 -*-
"""竞彩赔率变动（变盘）追踪

- 每轮抓取后有价场次（sp 三项都 >1.01）写入 engine/data/odds_history.json
  · first = 当天第一次见到的盘口（初盘）
  · last  = 最新盘口（现盘）
  · snaps = 每次变动的快照（只留首次 + 最近 12 条）
- 输出 engine/data/odds_delta.json：初盘→现盘的变化幅度、资金方向标签
"""
import io
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
JC = os.path.join(DATA, 'jc_okooo_page.json')
HIS = os.path.join(DATA, 'odds_history.json')
OUT = os.path.join(DATA, 'odds_delta.json')
MIN_D = 1.5   # 视为「动了」的最小幅度（%）


def load(p):
    try:
        with io.open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def fmt(sp):
    return '/'.join('%.2f' % v for v in sp)


def pct(cur, first):
    out = []
    for c, f in zip(cur, first):
        out.append(round((c - f) / f * 100.0, 1) if f else 0.0)
    return out


def tag_of(p):
    """p = [主, 平, 客] 变化百分比"""
    hp, dp, ap = p
    if max(abs(hp), abs(dp), abs(ap)) < MIN_D:
        return '盘口稳定'
    if hp <= -MIN_D and ap >= MIN_D:
        return '资金压主'
    if ap <= -MIN_D and hp >= MIN_D:
        return '资金压客'
    if dp <= -MIN_D and abs(hp) < MIN_D and abs(ap) < MIN_D:
        return '资金博平'
    return '分歧调整'


def main():
    jc = load(JC) or {}
    ms = jc.get('matches') or []
    his = load(HIS) or {'matches': {}}
    hm = his.setdefault('matches', {})
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    out = []
    changed = 0
    for m in ms:
        sp = m.get('sp') or []
        if len(sp) != 3 or any((not v) or v <= 1.01 for v in sp):
            continue
        sp = [round(float(v), 2) for v in sp]
        key = m.get('order') or m.get('mid')
        rec = hm.get(key)
        if not rec:
            rec = {'h': m.get('h'), 'a': m.get('a'), 'first': sp, 'last': sp,
                   'snaps': [[now, sp]]}
            hm[key] = rec
        else:
            if rec.get('last') != sp:
                rec['snaps'].append([now, sp])
                changed += 1
            rec['last'] = sp
        snaps = rec['snaps']
        if len(snaps) > 13:
            rec['snaps'] = [snaps[0]] + snaps[-12:]
        p = pct(rec['last'], rec['first'])
        tag = tag_of(p)
        out.append({'no': key, 'h': m.get('h'), 'a': m.get('a'),
                    'first': rec['first'], 'last': rec['last'], 'pct': p,
                    'tag': tag, 'moves': len(rec['snaps']) - 1,
                    'tm': m.get('tm')})
    his['updated'] = now
    with io.open(HIS, 'w', encoding='utf-8') as f:
        json.dump(his, f, ensure_ascii=False, separators=(',', ':'))
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'updated': now, 'matches': out}, f, ensure_ascii=False, indent=1)
    print('[odds] 追踪 %d 场，本轮变动 %d 场' % (len(out), changed))
    for x in out:
        if x['tag'] != '盘口稳定':
            print('  %s %s vs %s %s → %s [%s]' % (x['no'], x['h'], x['a'],
                                                 fmt(x['first']), fmt(x['last']), x['tag']))


if __name__ == '__main__':
    main()
