# -*- coding: utf-8 -*-
"""★ 第三七二条：由「排名 + 积分」推导战意（只读本地快照，不联网、不编数）。

输入  data/uel_rank.json   —— FotMob 联赛阶段榜 / 小组积分榜快照
输入  data/sfc_pick.json   —— 本期场次（取 no / h / a / main / hrank_lg）
输出  data/uel_motiv.json  —— {场次编号 / "主|客": 【战意】段}

推导口径（写进文案，不藏规则）：
  小组榜  —— 组内名次 + 积分 + 胜平负推定已赛轮次；按常规双循环推定总轮次
             （4队→6轮 / 3队→4轮）；剩余可得分 = 3 × 剩余轮次。
             比较「与第2名 / 第3名 / 末位」的分差是否已被剩余分数追不上。
             ★ 不绑定具体晋级名额（各赛季规则不同），只判断「还能不能追」。
  联赛阶段 —— 36 队单榜，按通用口径 1-8 直通 / 9-24 附加 / 25+ 出局，
             取第8、第24名积分作分界线；同样用剩余分数判断锁定/出局。

硬规矩：
  1. 缺积分、缺名次、缺剩余轮次 → 相应判定一律不做，只陈述已知分差，不猜。
  2. 模板文件（带 _template 标记）跳过，绝不把示例数据当真榜。
  3. 只有官方 hrank_lg / lg 指向欧战才出段（复用 _uel_ana.is_uel 门控）。
  4. 幂等，可安全挂在 refresh.py build 里。
"""
import io, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
RANK_FP = os.path.join(DATA, 'uel_rank.json')
MOTIV_FP = os.path.join(DATA, 'uel_motiv.json')
PICK_FP = os.path.join(DATA, 'sfc_pick.json')

import _uel_ana as UA

_COMP_KEYS = ('champions', 'europa', 'conference', 'nations', 'uefa',
              'leaguephase', 'league_phase', 'leaguetable', '总榜', '联赛阶段', '积分榜')
_EURO_WORDS = ('欧冠', '欧罗巴', '欧协', '欧国联', '欧联')


def _is_template(raw):
    if isinstance(raw, dict):
        return bool(raw.get('_template') or raw.get('__TEMPLATE__')
                    or raw.get('template') is True)
    return False


def _is_item(d):
    """战意条目必须同时有 名次 / 队名 / 积分"""
    if not isinstance(d, dict):
        return False
    has_rank = any(k in d for k in ('ranking', 'rank', 'position', 'pos'))
    has_pts = any(k in d for k in ('points', 'pts', 'score'))
    has_name = any(k in d for k in UA._NAME_KEYS)
    return has_rank and has_pts and has_name


def _is_comp_key(k):
    s = str(k or '').strip().lower().replace(' ', '')
    return any(w in s for w in _COMP_KEYS) or any(w in str(k) for w in _EURO_WORDS)


def collect(raw):
    """→ (tables:{赛事:[条目]}, groups:{组名:[条目]})"""
    tables, groups = {}, {}

    def walk(o, cg=None, cc=None):
        if isinstance(o, dict):
            if _is_item(o):
                if cg:
                    groups.setdefault(cg, []).append(o)
                else:
                    tables.setdefault(cc or '总榜', []).append(o)
                return
            for k, v in o.items():
                if not isinstance(v, (dict, list)):
                    continue
                ks = str(k).strip()
                if UA._is_group_key(ks):
                    walk(v, ks, cc)
                elif _is_comp_key(ks):
                    walk(v, cg, ks)
                else:
                    walk(v, cg, cc)
        elif isinstance(o, list):
            for v in o:
                walk(v, cg, cc)

    walk(raw)
    # 兜底：结构完全没标签 → 所有条目按总榜处理
    if not tables and not groups:
        items = []
        UA._flatten(raw, items)
        items = [d for d in items if _is_item(d)]
        if items:
            tables['总榜'] = items
    # 去重（同一队可能被多条路径收进同一个容器）
    for cont in (tables, groups):
        for k, arr in cont.items():
            seen, uniq = set(), []
            for d in arr:
                key = (UA._num(d, 'ranking', 'rank', 'position', 'pos'),
                       tuple(UA._names(d))[:1])
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(d)
            cont[k] = uniq
    return tables, groups


def _pts(d):
    return UA._num(d, 'points', 'pts', 'score')


def _rank(d):
    return UA._num(d, 'ranking', 'rank', 'position', 'pos')


def _played(d):
    w = UA._num(d, 'winGoalMatchCnt', 'w', 'wins', 'win')
    dr = UA._num(d, 'drawMatchCnt', 'd', 'draws', 'draw')
    l = UA._num(d, 'lossGoalMatchCnt', 'l', 'losses', 'loss')
    if None in (w, dr, l):
        return None
    return w + dr + l


def _rounds(n_teams, item=None):
    """总轮次：字段优先；否则按常规双循环推定，并明确标注是推定"""
    if isinstance(item, dict):
        v = UA._num(item, 'totalRounds', 'total_rounds', 'rounds', 'matchdayTotal')
        if v:
            return v, False
    if n_teams >= 4:
        return 6, True
    if n_teams == 3:
        return 4, True
    return None, True


def _sort(arr):
    def key(d):
        p = _pts(d) or 0
        gf = UA._num(d, 'goalCnt', 'gf', 'goalsFor') or 0
        ga = UA._num(d, 'lossGoalCnt', 'ga', 'goalsAgainst') or 0
        return (-p, -(gf - ga), _rank(d) or 999)
    return sorted(arr, key=key)


def group_motiv(item, peers):
    """小组口径 → (等级, 理由)"""
    p, r = _pts(item), _rank(item)
    if p is None or r is None:
        return None, None
    s = _sort(peers)
    n = len(s)
    played = _played(item)
    total, guessed = _rounds(n, item)
    rem = (total - played) if (total is not None and played is not None
                               and total >= played) else None
    maxp = 3 * rem if rem is not None else None
    tail = ''
    if rem is not None:
        tail = '，剩%d轮最多%d分%s' % (
            rem, maxp, '（总轮次按常规双循环推定）' if guessed else '')
    else:
        tail = '，剩余轮次未知（仅有分差，不做锁定/出局判定）'

    p2 = _pts(s[1]) if n >= 2 else None
    p3 = _pts(s[2]) if n >= 3 else None
    plast = _pts(s[-1]) if n >= 1 else None

    # ① 已锁定前二
    if r is not None and r <= 2 and p3 is not None:
        gap = p - p3
        if maxp is not None and gap > maxp:
            return '偏低', ('第%d名%d分，领先第3名%d分 > 可追%d分，已锁定前二，'
                           '存在轮换/练兵风险%s' % (r, p, gap, maxp, tail))
        if gap <= 3:
            return '高', ('第%d名%d分，仅领先第3名%d分，前二席位未稳，卡位战%s'
                         % (r, p, gap, tail))
        return '中', ('第%d名%d分，领先第3名%d分，位置相对稳但尚未锁定%s'
                     % (r, p, gap, tail))
    # ② 追赶前二 / 保级
    if r is not None and r >= 3:
        if p2 is not None:
            gap = p2 - p
            if gap <= 0:
                return '高', ('第%d名%d分与第2名同分/反超，直接卡位%s' % (r, p, tail))
            if maxp is not None and gap > maxp:
                if plast is not None and p - plast <= 3 and r == n:
                    return '低', ('第%d名%d分，落后第2名%d分已追不上，且末位仅差%d分，'
                                 '重心转为避免垫底/荣誉战%s' % (r, p, gap, p - plast, tail))
                return '低', ('第%d名%d分，落后第2名%d分 > 可追%d分，争夺前二仅剩理论可能，'
                             '荣誉战倾向%s' % (r, p, gap, maxp, tail))
            if gap <= 3:
                return '极高', ('第%d名%d分，距第2名仅%d分，直接争位/生死战%s'
                               % (r, p, gap, tail))
            return '高', ('第%d名%d分，落后第2名%d分仍在可追范围%s'
                         % (r, p, gap, tail))
    return '中', ('第%d名%d分，小组%d队，分差不足以判定倾向%s'
                 % (r, p, n, tail))


def phase_motiv(item, table):
    """36 队联赛阶段口径 → (等级, 理由)"""
    p, r = _pts(item), _rank(item)
    if p is None or r is None:
        return None, None
    s = sorted([d for d in table if _rank(d) is not None],
               key=lambda d: _rank(d))
    line8 = _pts(s[7]) if len(s) >= 8 else None
    line24 = _pts(s[23]) if len(s) >= 24 else None
    played = _played(item)
    total, guessed = _rounds(36, item)
    # 联赛阶段固定 8 轮；无字段时用 8，并标注为通用口径
    if total is None or total > 20:
        total, guessed = 8, True
    rem = (total - played) if (played is not None and total >= played) else None
    maxp = 3 * rem if rem is not None else None
    tail = ('，剩%d轮最多%d分' % (rem, maxp)) if rem is not None else '，剩余轮次未知'
    if line8 is None or line24 is None:
        return '中', ('联赛阶段第%d名%d分，样本不足%d队，无法取第8/第24分界线%s'
                     % (r, p, len(s), tail))
    if r <= 8:
        gap = p - (UA._num(s[8], 'points', 'pts', 'score') if len(s) > 8 else line24 or 0)
        if maxp is not None and gap > maxp:
            return '偏低', ('第%d名%d分，领先直通线外%d分 > 可追%d分，基本锁定前8，'
                           '轮换风险%s' % (r, p, gap, maxp, tail))
        if gap <= 3:
            return '高', ('第%d名%d分，直通席位仅领先%d分，需抢分%s' % (r, p, gap, tail))
        return '中', ('第%d名%d分，处直通区但未完全锁定%s' % (r, p, tail))
    if r >= 25:
        gap = line24 - p
        if maxp is not None and gap > maxp:
            return '低', ('第%d名%d分，落后附加线%d分 > 可追%d分，晋级仅剩理论可能%s'
                         % (r, p, gap, maxp, tail))
        if gap <= 3:
            return '极高', ('第%d名%d分，距附加线仅%d分，生死战%s' % (r, p, gap, tail))
        return '高', ('第%d名%d分，落后附加线%d分仍在可追范围%s' % (r, p, gap, tail))
    gap = p - line24
    if gap <= 3:
        return '极高', ('第%d名%d分，附加区边缘仅领先淘汰线%d分，输不起%s'
                       % (r, p, gap, tail))
    return '高', ('第%d名%d分，处9-24附加区，仍有抢分动机%s' % (r, p, tail))


_LEVEL_ORDER = {'低': 0, '偏低': 1, '中': 2, '高': 3, '极高': 4}


def match_tip(main, hl, al):
    if not hl or not al:
        return '⚑ 单侧缺战意判定，不据此加减分。'
    a, b = _LEVEL_ORDER.get(hl[0], 2), _LEVEL_ORDER.get(al[0], 2)
    if main == '主胜':
        fav, und, favn, undn = a, b, '主队', '客队'
    elif main == '客胜':
        fav, und, favn, undn = b, a, '客队', '主队'
    else:
        return '⚑ 主推平局，战意差不单独作为方向信号。'
    if fav <= 1 and und >= 3:
        return ('⚑ 市场主推%s战意%s、%s战意%s → 防轮换/放水冷门，'
                '建议降档或复式覆盖平局与反向。' % (favn, hl[0], undn, al[0]))
    if fav >= 3 and und <= 1:
        return '⚑ 主推%s战意%s、对手战意偏低 → 战意与定价同向，主线可维持。' % (favn, hl[0])
    if abs(fav - und) >= 2:
        return '⚑ 两侧战意差%d档（%s%s / %s%s），仅作提示，不自动改概率。' % (
            abs(fav - und), '主', hl[0], '客', al[0])
    return '⚑ 两侧战意接近（主%s / 客%s），不单独作为加减分。' % (hl[0], al[0])


def build():
    # 缺源 / 模板 → 清空旧段（换期后不残留上一期战意）
    if not os.path.exists(RANK_FP):
        io.open(MOTIV_FP, 'w', encoding='utf-8').write('{}')
        print('战意：缺 data/uel_rank.json → 不产生【战意】段（不编造积分/名次）')
        return 0
    try:
        raw = json.load(io.open(RANK_FP, encoding='utf-8'))
    except Exception as e:
        io.open(MOTIV_FP, 'w', encoding='utf-8').write('{}')
        print('战意：快照解析失败 %s → 不出段' % e)
        return 0
    if _is_template(raw):
        io.open(MOTIV_FP, 'w', encoding='utf-8').write('{}')
        print('战意：data/uel_rank.json 仍是模板（_template=true）→ 不出段，填入真实榜单后重跑')
        return 0

    tables, groups = collect(raw)
    snap = None
    if isinstance(raw, dict):
        for k in ('snapshot', 'date', 'source_date', 'asOf', 'updated'):
            if raw.get(k):
                snap = str(raw[k])
                break
    # 索引：norm队名 → (等级, 理由, 口径)
    idx = {}
    for g, arr in groups.items():
        for d in arr:
            lv, why = group_motiv(d, arr)
            if not lv:
                continue
            for n in UA._names(d):
                idx.setdefault(n, (lv, why, '%s小组积分榜' % g))
    for comp, arr in tables.items():
        for d in arr:
            # 小组条目已在 groups 里，不重复压成总榜
            if any(d is x for a in groups.values() for x in a):
                continue
            lv, why = phase_motiv(d, arr)
            if not lv:
                continue
            for n in UA._names(d):
                idx.setdefault(n, (lv, why, '%s联赛阶段榜' % comp))

    # ★ 第三七五条：把全榜可判定队的战意等级落盘（不只本期命中的两场）。
    #   换期后只要队名对上就能继续出段，避免「这期有、下期没了」。
    try:
        pool = {}
        for n, (lv, why, src) in idx.items():
            pool[n] = {'level': lv, 'why': why, 'source': src}
        io.open(os.path.join(DATA, 'uel_motiv_pool.json'), 'w', encoding='utf-8').write(
            json.dumps({'snapshot': snap or '', 'count': len(pool), 'teams': pool},
                       ensure_ascii=False, indent=1))
    except Exception:
        pass

    try:
        cur = json.load(io.open(PICK_FP, encoding='utf-8'))
        ms = cur if isinstance(cur, list) else cur.get('matches', [])
    except Exception:
        ms = []
    out, hit = {}, 0
    for m in ms:
        if not UA.is_uel(m):
            continue
        h, a = m.get('h') or '', m.get('a') or ''
        ih, ia = idx.get(UA._norm(h)), idx.get(UA._norm(a))
        if not ih and not ia:
            # ★ 第三七四条：缺小组积分快照也出段，把「有什么/缺什么」写清楚，
            #   而不是整段消失（用户看不到 = 以为没做）。等级判定仍按硬规矩不做。
            hr_, ar_ = m.get('hrank'), m.get('arank')

            def _rk(v):
                return ('第%s名' % v) if v is not None else '名次未获取'

            gap_txt = ''
            try:
                if hr_ is not None and ar_ is not None:
                    d = int(ar_) - int(hr_)
                    if abs(d) >= 10:
                        gap_txt = '；总榜位次%s领先%d位' % (
                            '客队' if d < 0 else '主队', abs(d))
            except Exception:
                gap_txt = ''
            seg = ['【战意】',
                   '本场为欧国联小组赛，但项目内无该组小组积分快照：'
                   '主 %s 竞彩总榜%s、客 %s %s%s。'
                   '（名次口径：竞彩官方总榜/FIFA 位次，非组内 1-4 名，不可据此判卡位或出线）'
                   % (h, _rk(hr_), a, _rk(ar_), gap_txt),
                   '战意等级判定需要「组内名次+积分+胜平负+剩余轮次」，本场四项皆缺，'
                   '按硬规矩不判、不编造；仅提示：位次差反映整体实力档，不反映本组出线形势。',
                   '（数据源：竞彩官方总榜名次；小组积分快照缺失）']
            txt = ''.join(seg)
            no = str(m.get('no') or '')
            if no:
                out[no] = txt
            out['%s|%s' % (h, a)] = txt
            hit += 1
            continue
        seg = ['【战意】']
        if ih:
            seg.append('主 %s 战意%s：%s。' % (h, ih[0], ih[1]))
        else:
            seg.append('主 %s 缺小组/联赛阶段积分快照，不出战意判定。' % h)
        if ia:
            seg.append('客 %s 战意%s：%s。' % (a, ia[0], ia[1]))
        else:
            seg.append('客 %s 缺小组/联赛阶段积分快照，不出战意判定。' % a)
        seg.append(match_tip(m.get('main'), ih, ia))
        srcs = sorted({x[2] for x in (ih, ia) if x})
        seg.append('（推导口径：组内/联赛阶段名次+积分+胜平负推定剩余轮次%s；'
                   '不绑定具体晋级名额，剩余轮次未知时只陈述分差）'
                   % ('，快照 %s' % snap if snap else ''))
        if srcs:
            seg.append('数据源：%s。' % '、'.join(srcs))
        txt = ''.join(seg)
        no = str(m.get('no') or '')
        if no:
            out[no] = txt
        out['%s|%s' % (h, a)] = txt
        hit += 1
    io.open(MOTIV_FP, 'w', encoding='utf-8').write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print('战意：联赛阶段榜 %d 个 / 小组 %d 个 → 可判定队 %d，命中 %d 场，快照 %s'
          % (len(tables), len(groups), len(idx), hit, snap or '未标注'))
    for k in list(out)[:2]:
        if '|' not in k:
            print('  %s → %s' % (k, out[k][:160]))
    return 0


if __name__ == '__main__':
    sys.exit(build())
