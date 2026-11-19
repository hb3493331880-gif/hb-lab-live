# -*- coding: utf-8 -*-
"""★ 第三七四条：把项目内已落盘的「竞彩官方积分榜」整理成 data/uel_rank.json。

本机 FotMob / 竞彩积分榜接口实测 403，用户给的 uel_rank.json 没到盘；
但 intel.json / _st_intel_by_team.json / _st_intel_batch.json 里存着官方
getMatchTables 响应的 tbl/tab —— 有 ranking + points + 胜平负 + groupName
+ phaseName，是真实排名与积分，不是编的。

只抽「欧国联 League A-D 小组榜」，按 (组, 队) 取已赛场次最多、且
3*胜+平 == 积分 自洽的一条；库里没有的队一律不写进快照。

硬规矩：
  1. 不联网、不编积分、不补队。
  2. 来源明确标注为竞彩官方（项目内快照），不冒充 FotMob 独立源。
  3. 已有真·独立源快照（same_source=false）时不覆盖它。
"""
import io, json, os, re, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
OUT = os.path.join(DATA, 'uel_rank.json')


def _norm(s):
    s = unicodedata.normalize('NFKC', str(s or '')).strip().lower()
    return re.sub(r'[\s\-_·、,，.。\'"“”‘’()]', '', s)


def _num(v):
    try:
        return int(float(v))
    except Exception:
        return None


def _flatten(o, out):
    if isinstance(o, dict):
        if 'ranking' in o and ('points' in o or 'pts' in o) \
                and any(k in o for k in ('teamShortName', 'teamName', 'name')):
            out.append(o)
            return
        for v in o.values():
            if isinstance(v, (dict, list)):
                _flatten(v, out)
    elif isinstance(o, list):
        for v in o:
            _flatten(v, out)


def _collect_items():
    items = []
    for fn in ('intel.json', '_st_intel_by_team.json'):
        p = os.path.join(DATA, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        for _k, v in (d.items() if isinstance(d, dict) else []):
            if isinstance(v, dict):
                for key in ('tbl', 'tab'):
                    if key in v:
                        _flatten(v[key], items)
    p = os.path.join(DATA, '_st_intel_batch.json')
    if os.path.exists(p):
        try:
            b = json.load(io.open(p, encoding='utf-8'))
        except Exception as e:
            b = {}
            print('  batch 文件解析失败：%s' % e)
        # ★ 第三七五条：逐条 try。此前一条 body 非 JSON 就抛到外层 except，
        #   整个 batch 被跳过（打印「读取跳过」但不报错），快照悄悄缩水。
        ok = bad = 0
        for k, v in b.items():
            if not k.endswith('::tab') or not isinstance(v, dict):
                continue
            try:
                _flatten(json.loads(v.get('body') or '{}'), items)
                ok += 1
            except Exception:
                bad += 1
        print('  batch tab：%d 条解析成功 / %d 条跳过（body 非 JSON）' % (ok, bad))
    return items


_GROUP_RE = re.compile(r'group\s*(\d+)', re.I)


def build():
    if os.path.exists(OUT):
        try:
            old = json.load(io.open(OUT, encoding='utf-8'))
            if isinstance(old, dict) and not old.get('_template') and not old.get('same_source'):
                print('已有独立源快照（%s），不覆盖' % (old.get('source') or '未标注'))
                return 0
        except Exception:
            pass

    items = _collect_items()
    cur = []
    try:
        s = json.load(io.open(os.path.join(DATA, 'sfc_pick.json'), encoding='utf-8'))
        for m in (s if isinstance(s, list) else []):
            for k in ('h', 'a'):
                t = str(m.get(k) or '')
                if t:
                    cur.append(t)
    except Exception:
        pass

    buckets = {}
    for x in items:
        ph = str(x.get('phaseName') or '')
        gn = str(x.get('groupName') or '')
        m = _GROUP_RE.search(gn)
        if not (ph.startswith('League ') and ph[-1:] in 'ABCD' and m):
            continue
        name = str(x.get('teamShortName') or x.get('teamName') or '')
        rk, pts = _num(x.get('ranking')), _num(x.get('points'))
        if not name or rk is None or pts is None:
            continue
        g = '欧国联%s-G%s' % (ph[-1], m.group(1))
        w = _num(x.get('winGoalMatchCnt')) or 0
        dr = _num(x.get('drawMatchCnt')) or 0
        l = _num(x.get('lossGoalMatchCnt')) or 0
        e = {
            'name': name, 'ranking': rk, 'points': pts,
            'winGoalMatchCnt': w, 'drawMatchCnt': dr, 'lossGoalMatchCnt': l,
            'goalCnt': _num(x.get('goalCnt')) or 0,
            'lossGoalCnt': _num(x.get('lossGoalCnt')) or 0,
            'totalLegCnt': _num(x.get('totalLegCnt')) or (w + dr + l),
            'group': g,
        }
        nf = _norm(name)
        for t in cur:
            if len(_norm(t)) >= 2 and nf.startswith(_norm(t)) and t != name:
                e['cn'] = t
                break
        key = (g, nf)
        old = buckets.get(key)
        score = (e['totalLegCnt'], 1 if 3 * w + dr == pts else 0, pts)
        if old is None or score > old[0]:
            buckets[key] = (score, e)
    groups = {}
    for (g, _n), (_s, e) in buckets.items():
        groups.setdefault(g, []).append(e)

    snap = '20261113'
    raw = {
        '_template': False,
        'same_source': True,
        'source': '竞彩官方积分榜（项目内已落盘快照，非 FotMob 独立源）',
        'snapshot': snap,
        'note': '从 intel/tab 响应整理；快照日 %s，可能滞后一场。库里没有的队不写进快照，缺积分者按硬规矩不出战意等级。' % snap,
        'groups': groups,
    }
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(raw, ensure_ascii=False, indent=1))
    print('已写 %s：%d 组 / %d 队（来源=竞彩官方项目内快照）' %
          (OUT, len(groups), sum(len(v) for v in groups.values())))
    for g in sorted(groups):
        print('  %s：%s' % (g, '、'.join('%s第%s名%s分' % (e['name'], e['ranking'], e['points'])
                                     for e in groups[g])))
    return 0


if __name__ == '__main__':
    build()
