# -*- coding: utf-8 -*-
"""★ 第三七一条 / 第三七二条：欧战排名独立源交叉校验（只读本地，不联网）。

输入  data/uel_rank.json   —— 已抓好的 FotMob 榜单快照（缺了就是没有独立源）
                              支持两种结构，互不混淆：
                              ① 联赛阶段总榜（欧冠/欧罗巴/欧协联 36 队单榜）
                              ② 小组积分榜（欧国联 A-G1 ~ C-G4 等）
输出  data/uel_ana.json    —— {场次编号 / "主|客": 【欧战排名】段}

原则：
  1. 不联网（本机 FotMob / 竞彩积分榜接口实测 403，抓榜交给能通的出口 IP）。
  2. 缺快照、队名对不上、名次缺失 —— 一律不产生该段，绝不编一个名字或名次。
  3. 联赛阶段榜与竞彩 hrank/arank 对账，不一致只打 ⚠ 告警，不改竞彩口径。
  4. 小组榜名次（组内 1~4）与竞彩名次（总榜/FIFA 口径，常见 1~74）不同源，
     ★ 不做一致性比对，避免把口径差异误报成数据错误。
  5. 幂等：重复跑结果一致，可安全挂在 refresh.py build 里。
"""
import io, json, os, re, sys, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
RANK_FP = os.path.join(DATA, 'uel_rank.json')
ANA_FP = os.path.join(DATA, 'uel_ana.json')
PICK_FP = os.path.join(DATA, 'sfc_pick.json')

_NAME_KEYS = ('name', 'name_cn', 'cn', 'cnName', 'team', 'teamName',
              'teamShortName', 'chinese', 'zh', 'en', 'english', 'shortName',
              'homeTeamAbbName', 'homeTeamAllName')
_GROUP_KEYS = ('groups', 'by_group', '小组', 'groupList', 'tables', 'standings')
_GROUP_NAME_RE = re.compile(
    r'(G\s*\d|第\s*\d+\s*组|小组|group[\s_\-]?[a-z0-9]{1,3}|[A-D]\s*[-–]\s*G\s*\d)', re.I)


def _norm(s):
    s = unicodedata.normalize('NFKC', str(s or '')).strip().lower()
    s = re.sub(r'[（(【\[].*?[)）】\]]', '', s)
    s = re.sub(r'[\s\-_·、,，.。\'"“”‘’]', '', s)
    return s


def _is_group_key(k):
    """键名看起来像小组标签（A-G1 / G2 / Group A / 第3组 / 欧国联B-G2）"""
    k = str(k or '').strip()
    if not k or k.lower() in ('group', 'groups', 'groupname', 'group_name'):
        return False
    return bool(_GROUP_NAME_RE.search(k))


def _flatten(obj, bucket):
    """把任意层级的联赛阶段总榜球队条目收进 bucket"""
    if isinstance(obj, dict):
        if any(k in obj for k in ('ranking', 'rank', 'position', 'pts', 'points')) \
                and any(k in obj for k in _NAME_KEYS):
            bucket.append(obj)
            return
        for v in obj.values():
            _flatten(v, bucket)
    elif isinstance(obj, list):
        for v in obj:
            _flatten(v, bucket)


def _flatten_groups(obj, gname=None, out=None):
    """识别小组积分榜，返回 {norm队名: (组名, 条目)}。

    兼容三种常见写法：
      {"欧国联A-G1": [ {...}, ... ], ...}
      {"groups": {"A-G1": {"table": [...]}, ...}}
      [ {"group":"A-G1", "standings":[ {...} ]}, ... ]
    """
    if out is None:
        out = {}
    if isinstance(obj, dict):
        g = gname
        for k in ('group', 'groupName', 'group_name', 'groupLabel', '小组名'):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                g = v.strip()
                break
        # 容器键本身是组名
        for k, v in obj.items():
            if isinstance(k, str) and _is_group_key(k) and isinstance(v, (list, dict)):
                _flatten_groups(v, k.strip(), out)
        # 显式 groups 容器
        for k in _GROUP_KEYS:
            v = obj.get(k)
            if isinstance(v, (list, dict)):
                _flatten_groups(v, g, out)
        # 球队条目
        if any(k in obj for k in ('ranking', 'rank', 'position', 'pts', 'points')) \
                and any(k in obj for k in _NAME_KEYS):
            if g:
                for n in _names(obj):
                    out.setdefault(n, (g, obj))
            return out
        for v in obj.values():
            if isinstance(v, (dict, list)) and v is not obj.get('groups'):
                _flatten_groups(v, g, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_groups(v, gname, out)
    return out


def _names(d):
    out = []
    for k in _NAME_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            out.append(_norm(v))
    return [x for x in out if x]


def _num(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, '', '?', '-'):
            try:
                return int(float(v))
            except Exception:
                pass
    return None


def load_rank():
    """返回 (联赛阶段索引, 快照日期, 小组索引, 来源元信息)。

    ★ 第三七四条：快照可能是项目内「竞彩官方积分榜」而非 FotMob 独立源，
      段文案必须按真实来源写，同源时不做交叉校验，避免假 ⚠。
    """
    if not os.path.exists(RANK_FP):
        return {}, None, {}, {}
    try:
        raw = json.load(io.open(RANK_FP, encoding='utf-8'))
    except Exception as e:
        print('  uel_rank.json 解析失败：%s（按无榜单处理）' % e)
        return {}, None, {}, {}
    # ★ 第三七二条：带 _template 标记的是结构样例，不是真榜单 —— 绝不产出假名次
    if isinstance(raw, dict) and (raw.get('_template') or raw.get('__TEMPLATE__')
                                  or raw.get('template') is True):
        print('  uel_rank.json 仍是模板（_template=true）→ 按无榜单处理')
        return {}, None, {}, {}
    items = []
    _flatten(raw, items)
    idx = {}
    for d in items:
        for n in _names(d):
            idx.setdefault(n, d)
    gidx = _flatten_groups(raw)
    snap = None
    meta = {}
    if isinstance(raw, dict):
        for k in ('snapshot', 'date', 'source_date', 'asOf', 'updated'):
            if raw.get(k):
                snap = str(raw[k])
                break
        meta = {'source': str(raw.get('source') or ''),
                'same_source': bool(raw.get('same_source')),
                'note': str(raw.get('note') or '')}
    return idx, snap, gidx, meta


def _stats(d):
    rank = _num(d, 'ranking', 'rank', 'position', 'pos')
    pts = _num(d, 'points', 'pts', 'score')
    w = _num(d, 'winGoalMatchCnt', 'w', 'wins', 'win')
    dr = _num(d, 'drawMatchCnt', 'd', 'draws', 'draw')
    l = _num(d, 'lossGoalMatchCnt', 'l', 'losses', 'loss')
    gf = _num(d, 'goalCnt', 'gf', 'goalsFor')
    ga = _num(d, 'lossGoalCnt', 'ga', 'goalsAgainst')
    fmt = lambda v: '?' if v is None else v
    return rank, ('%s分（%s胜%s平%s负，进%s失%s）' % (
        fmt(pts), fmt(w), fmt(dr), fmt(l), fmt(gf), fmt(ga)))


def _team_line(side_label, team, d, snap):
    """联赛阶段总榜口径"""
    if not d:
        return None
    comp = d.get('competition') or d.get('comp') or d.get('league') or d.get('lg') or ''
    comp = ('%s联赛阶段' % comp) if comp and '联赛阶段' not in str(comp) else (comp or '联赛阶段')
    rank, st = _stats(d)
    if rank is None:
        return None
    return '%s %s %s第%s名 %s' % (side_label, team, comp, rank, st)


def _group_line(side_label, team, gname, d, snap):
    """小组积分榜口径（组内名次，不与总榜混用）"""
    if not d:
        return None
    rank, st = _stats(d)
    if rank is None:
        return None
    g = str(gname).strip()
    if '小组' not in g and '组' not in g:
        g += '组'
    return '%s %s %s第%s名 %s' % (side_label, team, g, rank, st)


_UEL_KEYS = ('欧冠', '欧罗巴', '欧协', '欧国联', '欧联', 'uefa',
             'champions', 'europa', 'conference', 'nations')


def is_uel(m):
    """★ 门控：只有官方 homeRank 标签指向欧战赛事才挂【欧战排名】。
    国际赛场次的 [国际赛96] 实为 FIFA 世界排名，不许串上来。"""
    s = ' '.join(str(m.get(k) or '') for k in
                 ('hrank_lg', 'arank_lg', 'lg', 'league', 'matchName')).lower()
    return any(k in s for k in _UEL_KEYS)


def build():
    idx, snap, gidx, meta = load_rank()
    src_name = meta.get('source') or '本地快照'
    same = bool(meta.get('same_source'))
    if not idx and not gidx:
        # 没有榜单：清空旧段，避免换期后残留上一期的排名
        io.open(ANA_FP, 'w', encoding='utf-8').write('{}')
        print('欧战排名：缺 data/uel_rank.json 榜单 → 不产生【欧战排名】段，不编造')
        return 0
    try:
        cur = json.load(io.open(PICK_FP, encoding='utf-8'))
        ms = cur if isinstance(cur, list) else cur.get('matches', [])
    except Exception:
        ms = []
    out, hit, warn, grp_hit = {}, 0, 0, 0
    for m in ms:
        if not is_uel(m):
            continue
        h, a = m.get('h') or '', m.get('a') or ''
        # 小组榜优先：命中即走小组口径，且不做总榜对账
        gh = gidx.get(_norm(h))
        ga = gidx.get(_norm(a))
        if gh or ga:
            grp_hit += 1
            hl = _group_line('主', h, gh[0] if gh else '', gh[1] if gh else None, snap)
            al = _group_line('客', a, ga[0] if ga else '', ga[1] if ga else None, snap)
            src = ('（名次/积分源：%s 小组积分榜（快照 %s）%s；竞彩名次为总榜口径，与组内名次不同源，不做一致性比对）'
                   % (src_name, snap, '，可能滞后一场' if same else '')) if snap else (
                   '（名次/积分源：%s 小组积分榜；竞彩名次为总榜口径，不做一致性比对）' % src_name)
            diffs = []
        else:
            dh = idx.get(_norm(h))
            da = idx.get(_norm(a))
            hl = _team_line('主', h, dh, snap)
            al = _team_line('客', a, da, snap)
            _qual = '，与竞彩同源，不做交叉校验' if same else '，独立于竞彩口径，用于交叉校验'
            src = ('（名次/积分源：%s 联赛阶段积分榜（快照 %s）%s）'
                   % (src_name, snap, _qual)) if snap else (
                   '（名次/积分源：%s 联赛阶段积分榜%s）' % (src_name, _qual))
            diffs = []
            # ★ 第三七四条：快照若来自竞彩官方自身，就不做「独立源对账」，
            #   否则会把同一口径的不同榜单误报成 ⚠ 数据冲突。
            for label, off, cr in (() if same else (
                    ('主', dh, m.get('hrank')), ('客', da, m.get('arank')))):
                ir = _num(off or {}, 'ranking', 'rank', 'position', 'pos')
                if ir is None or cr is None:
                    continue
                try:
                    cr = int(cr)
                except Exception:
                    continue
                if ir != cr:
                    diffs.append('%s队竞彩第%d名 / 独立源第%d名' % (label, cr, ir))
            if diffs:
                warn += 1
        if not hl and not al:
            continue
        seg = ['【欧战排名】']
        if hl: seg.append(hl + '。')
        if al: seg.append(al + '。')
        seg.append(src)
        if diffs:
            seg.append('⚠ 名次口径不一致：%s；两者可能为不同榜单，请核对，不自动采信任一方。' % '；'.join(diffs))
        txt = ''.join(seg)
        no = str(m.get('no') or '')
        if no: out[no] = txt
        out['%s|%s' % (h, a)] = txt
        hit += 1
    io.open(ANA_FP, 'w', encoding='utf-8').write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print('欧战排名：联赛阶段 %d 队 / 小组 %d 队 → 命中 %d 场（其中小组口径 %d 场），⚠ 口径不一致 %d 场，快照 %s'
          % (len(idx), len(gidx), hit, grp_hit, warn, snap or '未标注'))
    for k in list(out)[:3]:
        if '|' not in k:
            print('  %s → %s' % (k, out[k][:130]))
    return 0


if __name__ == '__main__':
    sys.exit(build())
