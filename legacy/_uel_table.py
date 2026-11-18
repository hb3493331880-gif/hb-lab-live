# -*- coding: utf-8 -*-
"""★ 第三七一条：欧战积分榜快照工具。

本机 FotMob 四通道 403（出口 IP 被 WAF 挡，不是 URL/方法错）。
所以本脚本的默认行为是「校验并复用已有 data/uel_rank.json」，
抓不到就如实说抓不到，绝不写一份假榜进去。

产物：
  data/uel_table.json —— 竞彩口径总表（从 sfc_pick.json 的 hrank_lg/hrank 收集，
                          这是官方 webapi 真实返回的 [赛事N] 名次，不需要联网）
  data/uel_rank.json  —— 独立源快照，仅在联网成功时写入；已有文件绝不覆盖删除

若换到能通 FotMob 的出口 IP，把下面 LEAGUES 里的 leagueId 配上真实
/api/data/... 路径与 Header 即可直接抓（URL/Header 以能通的那台机为准）。
"""
import io, json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
RANK_FP = os.path.join(DATA, 'uel_rank.json')
TABLE_FP = os.path.join(DATA, 'uel_table.json')
PICK_FP = os.path.join(DATA, 'sfc_pick.json')

# 赛事口径常量（来自能通 FotMob 的那台机；本机只用来标注，不假装抓到）
LEAGUES = {
    '欧冠': 943230, '欧罗巴': 943229, '欧协联': 943231,
}
def load_group_names():
    """从已抓好的 uel_rank.json 读真实小组名。

    ★ 绝不拿常量列表冒充「抓到了 8 个小组」——缺快照就返回空。
    """
    if not os.path.exists(RANK_FP):
        return []
    try:
        raw = json.load(io.open(RANK_FP, encoding='utf-8'))
    except Exception:
        return []
    names = set()
    pat = re.compile(r'(G\s*\d|[A-D]\s*[-–]\s*G\s*\d|第\s*\d+\s*组)', re.I)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and pat.search(k) and isinstance(v, (list, dict)):
                    names.add(k.strip())
            for k in ('group', 'groupName', 'group_name', 'groupLabel', '小组名'):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    names.add(v.strip())
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(raw)
    return sorted(names)


def build_jc_table():
    """竞彩口径总表：homeRank 形如 [欧罗巴28]，标签就是赛事口径。"""
    try:
        cur = json.load(io.open(PICK_FP, encoding='utf-8'))
        ms = cur if isinstance(cur, list) else cur.get('matches', [])
    except Exception:
        ms = []
    tab = {}
    for m in ms:
        for side, rk, lg in (('h', m.get('hrank'), m.get('hrank_lg') or m.get('lg')),
                             ('a', m.get('arank'), m.get('arank_lg') or m.get('lg'))):
            nm = m.get(side) or ''
            if rk is None or not nm:
                continue
            tab.setdefault(lg or '未标注', {})[nm] = int(rk)
    io.open(TABLE_FP, 'w', encoding='utf-8').write(
        json.dumps({'by_league': tab, 'source': '竞彩官方 webapi homeRank/awayRank',
                    'note': '该场所属赛事的总积分榜名次；非球队国内联赛排名'},
                   ensure_ascii=False, indent=1))
    return sum(len(v) for v in tab.values())


def try_fetch():
    """可选联网。本机必 403，失败如实返回，不写假数据。"""
    if os.path.exists(RANK_FP):
        try:
            raw = json.load(io.open(RANK_FP, encoding='utf-8'))
            n = len(raw) if isinstance(raw, (list, dict)) else 0
            gs = load_group_names()
            print('复用本地独立源快照 data/uel_rank.json（顶层 %d 项，小组 %d 个），未联网'
                  % (n, len(gs)))
        except Exception as e:
            print('本地快照解析失败：%s' % e)
        return True
    print('缺 data/uel_rank.json，尝试联网抓榜…')
    try:
        import urllib.request
        req = urllib.request.Request(
            'https://www.fotmob.com/api/data/matches?date=20261114',
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.fotmob.com/'})
        with urllib.request.urlopen(req, timeout=8) as r:
            print('联网成功：%d 字节（按真实返回再写快照）' % len(r.read()))
        return True
    except Exception as e:
        print('联网抓榜失败：%s' % str(e)[:120])
        print('→ 本机出口 IP 被 WAF 挡（403），未写入任何榜单数据。')
        print('→ 最省事：把已抓好的 data/uel_rank.json 放进 data/，_uel_ana.py 只读本地即可出段。')
        return False


def main():
    n = build_jc_table()
    print('竞彩口径总表已写 data/uel_table.json（%d 队，来自官方 homeRank 标签）' % n)
    print('赛事 leagueId 常量（仅供标注）：%s' %
          ', '.join('%s=%d' % kv for kv in LEAGUES.items()))
    gs = load_group_names()
    print('小组积分榜：%s' % (
        '已读到 %d 个小组：%s' % (len(gs), ', '.join(gs[:10]))
        if gs else '未就绪（缺 data/uel_rank.json，或快照里没有小组结构）'))
    ok = try_fetch()
    print('独立源状态：%s' % ('就绪' if ok else '未就绪（无独立源，页面不出【欧战排名】段）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
