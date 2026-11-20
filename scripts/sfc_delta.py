# -*- coding: utf-8 -*-
"""任九 14 场欧赔变盘追踪（与竞彩同一套口径）

输入 engine/data/sfc_okooo.json（澳客 m 站 14 场欧赔）
输出 engine/data/sfc_delta.json
"""
import io
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
SRC = os.path.join(DATA, 'sfc_okooo.json')
HIS = os.path.join(DATA, 'sfc_odds_history.json')
OUT = os.path.join(DATA, 'sfc_delta.json')
MIN_D = 1.5


def load(p):
    try:
        with io.open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def tag_of(p):
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
    s = load(SRC) or {}
    ms = s.get('matches') or []
    issue = s.get('issue') or ''
    his = load(HIS) or {'issues': {}}
    hi = his.setdefault('issues', {})
    cur = hi.setdefault(issue, {'no': {}})
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    out = []
    changed = 0
    for m in ms:
        o = m.get('o') or []
        if len(o) != 3 or any((not v) or v <= 1.01 for v in o):
            continue
        o = [round(float(v), 2) for v in o]
        rec = cur['no'].get(str(m.get('no')))
        if not rec:
            rec = {'first': o, 'last': o, 'snaps': [[now, o]]}
            cur['no'][str(m.get('no'))] = rec
        else:
            if rec.get('last') != o:
                rec['snaps'].append([now, o])
                changed += 1
            rec['last'] = o
        snaps = rec['snaps']
        if len(snaps) > 13:
            rec['snaps'] = [snaps[0]] + snaps[-12:]
        p = [round((b - a) / a * 100.0, 1) if a else 0.0 for a, b in zip(rec['first'], rec['last'])]
        out.append({'no': m.get('no'), 'h': m.get('h'), 'a': m.get('a'),
                    'first': rec['first'], 'last': rec['last'], 'pct': p,
                    'tag': tag_of(p), 'moves': len(rec['snaps']) - 1})
    his['updated'] = now
    with io.open(HIS, 'w', encoding='utf-8') as f:
        json.dump(his, f, ensure_ascii=False, separators=(',', ':'))
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'issue': issue, 'updated': now, 'matches': out}, f, ensure_ascii=False, indent=1)
    print('[sfc-delta] 第%s期 %d 场，本轮变动 %d 场' % (issue, len(out), changed))


if __name__ == '__main__':
    main()
