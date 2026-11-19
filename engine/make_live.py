#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/full.json 内联进 index.html，产出 index_live.html（单文件、自包含）"""
import json, os, re, sys

# ★ 借鉴第三〇四条 A：JSON 注入 <script> 前必须转义 </ ，
#   否则数据里任何 "</" 都会提前闭合 script 标签 → 整页静默崩。
def jd(o, **kw):
    return json.dumps(o, **kw).replace('</', '<\\/')

BASE = os.path.dirname(os.path.abspath(__file__))

# ★★ 第二〇八条：复盘数据守卫 —— 每次生成前先回灌，保证复盘永不丢失 ★★
# data/jc_review.json / bj_review.json / score_review.json 若被覆盖成空或变少，
# 会从 data/review_archive.json（只增不减的归档）自动补回。
try:
    import subprocess as _sp
    _g = os.path.join(BASE, '_review_guard.py')
    if os.path.exists(_g):
        _sp.run([sys.executable, _g, 'restore'], cwd=BASE,
                stdout=open(os.devnull, 'w'), stderr=_sp.STDOUT)
        _sp.run([sys.executable, _g, 'sync'], cwd=BASE,
                stdout=open(os.devnull, 'w'), stderr=_sp.STDOUT)
except Exception as _e:
    print('[警告] 复盘守卫未执行：%s' % _e)
# ★ 第二二九条：平局单列命中统计（k=0 后平局独立评估，必须每次重算）
try:
    import subprocess as _sp2
    _ds = os.path.join(BASE, '_draw_stat.py')
    if os.path.exists(_ds):
        _r = _sp2.run([sys.executable, _ds], cwd=BASE, capture_output=True, text=True)
        for _ln in (_r.stdout or '').strip().split('\n'):
            if _ln: print('  ' + _ln)
except Exception as _e:
    print('[警告] 平局统计未执行：%s' % _e)

full = json.load(open(os.path.join(BASE, 'data', 'full.json'), encoding='utf-8'))
html = open(os.path.join(BASE, 'template.html'), encoding='utf-8').read()

# ★ 竞彩四档补齐（第一五二条）
# full.json['matches'] 走的是 sync_sporttery 链路，r 里只有 lh/la/p/scores/pre_top3，
# 缺 big / upset / tot / feat —— 竞彩页因此「大的」「爆冷」「局型」全空白。
# score_fuse.json（_recalc.py 产出）四档齐全，按编号合并进去。
_fuse_p = os.path.join(BASE, 'data', 'score_fuse.json')
if os.path.exists(_fuse_p):
    try:
        _fuse = json.load(open(_fuse_p, encoding='utf-8'))
        _fm = {}
        for _r in _fuse:
            if _r.get('num'): _fm[str(_r['num']).strip()] = _r
        _n = 0
        _n2 = 0
        for _m in (full.get('matches') or []):
            _f = _fm.get(str(_m.get('num') or '').strip())
            if not _f: continue
            # ★ 第一八二条：四档已在 _jc_official_merge/_jc_fill_model 里算好，
            #   旧 score_fuse 会覆盖成过期值 → 只在四档为空时才回退
            if (_m.get('r') or {}).get('top3') or _m.get('top3'):
                # ★ 第一九三条：四档已有 → 只同步「策略层」字段
                #   top3/大的/爆冷/局型保持原值（避免被旧值覆盖，第一八二条）；
                #   但 two/alt/平局候选是本次新算的策略，必须同步，否则修复不生效。
                _r0 = _m.get('r') or {}
                for _k in ('two', 'two_why', 'draw_cand', 'alt', 'alt_p',
                           'main', 'main_p', 'gap'):
                    if _f.get(_k) is not None:
                        _r0[_k] = _f[_k]
                        _m[_k] = _f[_k]
                _n2 += 1
                continue
            # ★ 第一六八条：setdefault 在 r 已存在但为 None 时会返回 None
            #   → 下一行赋值直接抛 'NoneType' object does not support item assignment
            #   → 整场四档合并失败，竞彩「大的/爆冷/局型」全空（表现为"被删了"）
            _r = _m.get('r') or {}
            _m['r'] = _r
            for _k in ('top3', 'big', 'upset', 'alt_sc', 'tot', 'feat',
                       'main', 'main_p', 'alt', 'alt_p', 'gap', 'two'):
                if _f.get(_k) is not None:
                    _r[_k] = _f[_k]
                    _m[_k] = _f[_k]      # 顶层也放一份，兼容两种读取方式
            _n += 1
        print('[make_live] 竞彩四档合并：%d/%d 场（策略层同步 %d 场）'
              % (_n, len(full.get('matches') or []), _n2))
    except Exception as _e:
        print('[make_live] 竞彩四档合并失败：%s' % _e)

# ★ 第一七七条：把复盘里已核实的赛果回填到竞彩卡片，
#   这样「刚踢完 24 小时内」保留的卡片能直接显示实际比分，不用翻到复盘区看。
try:
    _jrp = os.path.join(BASE, 'data', 'jc_review.json')
    if os.path.exists(_jrp):
        _jr2 = json.load(open(_jrp, encoding='utf-8'))
        # ★ 第二六九条：jc_review.json 是 list（不是 dict），不兼容会静默跳过全部赛果回填
        if isinstance(_jr2, dict):
            _jr2 = _jr2.get('rows') or []
        # ★ 第二五九条：编号每期复用（周四001 上周是日本vs乌拉圭，本周是赫尔辛基vs瓦萨），
        #   按【编号】回填会把上周赛果贴到本周未开赛场次上 → 编造赛果。
        #   必须按【队名】匹配，队名对不上就绝不回填。
        def _norm_t(s):
            import re as _re
            return _re.sub(r'[\s·\-\u3000]', '', str(s or '')).upper()
        _ftm = {}
        for _r in _jr2:
            if _r.get('ft') and _r.get('h'):
                _ftm[(_norm_t(_r.get('h')), _norm_t(_r.get('a')))] = (
                    _r['ft'], _r.get('note', ''))
        _nb = 0
        _nskip = 0
        for _m in (full.get('matches') or []):
            if _m.get('ft'):
                continue
            _k = (_norm_t(_m.get('h')), _norm_t(_m.get('a')))
            if _k in _ftm:
                _m['ft'], _m['ft_note'] = _ftm[_k][0], _ftm[_k][1]
                _nb += 1
            elif str(_m.get('no')) in set(str(_r.get('no')) for _r in _jr2):
                _nskip += 1      # 编号撞车但队名不符 → 拒绝回填
        if _nskip:
            print('[make_live] ★第二五九条：%d 场编号撞车但队名不符，已拒绝回填赛果' % _nskip)
        if _nb:
            print('[make_live] 竞彩赛果回填：%d 场' % _nb)
except Exception as _e:
    print('[make_live] 竞彩赛果回填失败：%s' % _e)

inline = '<script>window.__LIVE__=%s;</script>\n' % jd(
    full, ensure_ascii=False, separators=(',', ':'))
# 同时注入胜负彩 14 场（任选9场页用）
# 竞彩 3 场「为什么是这些比分」静态分析（人工调研，非抓取）
jcwhy_path = os.path.join(BASE, 'data', 'jc_why.json')
jw = {}
if os.path.exists(jcwhy_path):
    jw = json.load(open(jcwhy_path, encoding='utf-8'))
# ★ 按【队名】匹配到当前编号的人工调研（编号每期会变，按编号存会张冠李戴）
_rn = os.path.join(BASE, 'data', 'jc_why_now.json')
if os.path.exists(_rn):
    try:
        _rn_data = json.load(open(_rn, encoding='utf-8'))
        jw.update(_rn_data)   # 新调研优先，覆盖旧的同编号条目
        print('[make_live] 人工调研合并：%d 场' % len(_rn_data))
    except Exception as _e:
        print('[make_live] 调研合并失败：%s' % _e)
inline += '<script>window.__JCWHY__=%s;</script>\n' % jd(
    jw, ensure_ascii=False, separators=(',', ':'))

# ★ 独立基本面模型结果（26132 期，完全不看赔率算出来的）
fund_path = os.path.join(BASE, 'data', 'fundamental26132.json')
if os.path.exists(fund_path):
    fr = json.load(open(fund_path, encoding='utf-8'))
    fund_map = {'%03d' % r['no']: r for r in fr}
    # ★ 第二五〇条：__FUND__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 平局专项分析（26132 期：稳态平局 / 爆冷平局 / 平局超额）
draw_path = os.path.join(BASE, 'data', 'draw26132.json')
if os.path.exists(draw_path):
    dr = json.load(open(draw_path, encoding='utf-8'))
    draw_map = {r['no']: r for r in dr}
    # ★ 第二五〇条：__DRAW__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 北单融合模型（诚实版：改了但回测更差，所以方向仍用市场）
bfp = os.path.join(BASE, 'data', 'bjdc_fusion.json')
if os.path.exists(bfp):
    bfd = json.load(open(bfp, encoding='utf-8'))
    # ★ 第二五〇条：__BJDC_FUSION__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 北单剩余场次：人工判断（不全跟最低SP）
bmp = os.path.join(BASE, 'data', 'bjdc_manual.json')
if os.path.exists(bmp):
    bmd = json.load(open(bmp, encoding='utf-8'))
    # ★ 第二五〇条：__BJDC_MANUAL__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 第一六六条：bjdc_review.json 是旧批次(390 阿职联)，与当日北单无交集，
#   页面读的是 __BJ_REVIEW__（当日已结束场次的赛前推 vs 实际）。
#   旧数据不再注入，避免两套复盘并存导致混淆/污染。

# ★ 竞彩 & 北单 平局专项分析
djb_path = os.path.join(BASE, 'data', 'draw_jc_bjdc.json')
if os.path.exists(djb_path):
    djb = json.load(open(djb_path, encoding='utf-8'))
    # ★ 第二五〇条：__DRAWJB__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 复盘→校准系数（让校准效果在页面上可见）
_cb = os.path.join(BASE, 'data', 'calib.json')
if os.path.exists(_cb):
    _d = json.load(open(_cb, encoding='utf-8'))
    inline += '<script>window.__CALIB__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
# ★ 任九背离追踪表（第三六三条：排名背离 vs 真实赛果，每天累积）
_rd = os.path.join(BASE, 'data', '_r9_diverge.json')
if os.path.exists(_rd):
    _d = json.load(open(_rd, encoding='utf-8'))
    inline += '<script>window.__R9_DIV__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
# ★ 竞彩比分复盘（四档全对照：top3/大的/爆冷/局型/方向）
_jr = os.path.join(BASE, 'data', 'jc_review.json')
if os.path.exists(_jr):
    _d = json.load(open(_jr, encoding='utf-8'))
    inline += '<script>window.__JC_REVIEW__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
# ★ 北单比分复盘（与竞彩完全同口径：top3/大的/爆冷/局型/方向，用赛前原推λ）
_br = os.path.join(BASE, 'data', 'bj_review.json')
if os.path.exists(_br):
    _d = json.load(open(_br, encoding='utf-8'))
    inline += '<script>window.__BJ_REVIEW__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
# ★ 比分复盘（top3/大的/爆冷/局型 全对照真实赛果）
_sr = os.path.join(BASE, 'data', 'score_review.json')
if os.path.exists(_sr):
    _d = json.load(open(_sr, encoding='utf-8'))
    inline += '<script>window.__SCORE_REVIEW__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
# ★ 因子覆盖度（9因子真实覆盖，透明展示）
_fc = os.path.join(BASE, 'data', 'factor_cov.json')
if os.path.exists(_fc):
    _d = json.load(open(_fc, encoding='utf-8'))
    inline += '<script>window.__FACTOR_COV__=%s;</script>\n' % jd(
        _d, ensure_ascii=False, separators=(',', ':'))
inline += ''
# ★ 深度因子（伤停/教练/球队关系/大小球/比分 —— 真实调研）
_df = os.path.join(BASE, 'data', 'deep_factors.json')
if os.path.exists(_df):
    _d = json.load(open(_df, encoding='utf-8'))
    # ★ 合并各玩法 json 里的 deep 字段（_h2h/_ofreal 自动算出来的真实交锋/真实进球）
    for _f in ('two_way.json', 'bj_26097.json', 'sfc26132.json'):
        _p = os.path.join(BASE, 'data', _f)
        if not os.path.exists(_p): continue
        try:
            for _it in json.load(open(_p, encoding='utf-8')):
                _dd = _it.get('deep') or {}
                if not _dd: continue
                # ★ 北单用 num 字段（不是 no），漏了就挂到 '队名|队名' 上，页面按 num 查不到
                _key = str(_it.get('no') or _it.get('num') or '').lstrip('0') or (
                    (_it.get('h') or '') + '|' + (_it.get('a') or ''))
                if not _key or _key == '|': continue
                if _key in _d:
                    for _k, _v in _dd.items():
                        if _v not in (None, '', '—'):
                            # ★ 用 setdefault 会被已存在的 '—' 占位挡住，新调研永远进不来
                            #   只有「现有值为空/—」才写入，真有内容的调研不覆盖
                            if _d[_key].get(_k) in (None, '', '—'): _d[_key][_k] = _v
                else:
                    _d[_key] = dict(_dd)
        except Exception:
            pass
    # ★ 第二五〇条：__DEEP_FACTORS__ 死数据块已删（页面零读取点；清理过期数据）
inline += ''
# ★ 双方向推荐数据 —— 必须放在最前面（页面启动时同步渲染一次）
for _k, _f in [('__TWO_WAY__', 'two_way.json'), ('__BJ_TWO_WAY__', 'bj_26097.json')]:
    _p = os.path.join(BASE, 'data', _f)
    if os.path.exists(_p):
        _d = json.load(open(_p, encoding='utf-8'))
        inline += '<script>window.%s=%s;</script>\n' % (_k, jd(
            _d, ensure_ascii=False, separators=(',', ':')))

# ★ 双轨比分（赔率λ + 球队真实λ 融合）—— 必须放在最前面，
#   因为页面启动时同步渲染一次，若定义在后面会取不到
_fuse = os.path.join(BASE, 'data', 'score_fuse.json')
if os.path.exists(_fuse):
    _fd = json.load(open(_fuse, encoding='utf-8'))
    inline += '<script>window.__SCORE_FUSE__=%s;</script>\n' % jd(
        _fd, ensure_ascii=False, separators=(',', ':'))
    _fn = os.path.join(BASE, '_fuse_fn.txt')
    if os.path.exists(_fn):
        inline += '<script>%s</script>\n' % open(_fn, encoding='utf-8').read()

# 北单（北京单场，只做胜平负）
# ★★ 第三三八条：这里原写死 bj_26097.json，期号一变就永远渲染旧批次
#   （26108 抓到 104 场，页面仍显示 26097 的 17 场）。改成扫描取期号最大者。
#   ★第一六七条仍然有效：北单只准一套数据源，两套并存必错位。
def _latest_bj():
    # ★ 第三四六条：只扫 bj_*.json 取期号最大者 —— 26111 期的 147 场存在
    #   _bj_latest_full.json 里（下划线开头，扫不到），而 bj_26108.json 是 0 场，
    #   于是 __BJDC__ 被注入成 15 字节空块，北单整页空白且守卫全绿。
    #   改成：先取当前期主文件 _bj_latest_full.json（非空即用），再回落期号最大。
    import glob
    _p = os.path.join(BASE, 'data', '_bj_latest_full.json')
    try:
        _d = json.load(open(_p, encoding='utf-8'))
        _n = len(_d.get('matches', _d)) if isinstance(_d, dict) else len(_d)
        if _n > 0:
            return '_bj_latest_full.json'
    except Exception:
        pass
    best, bi = 'bj_26097.json', -1
    for p in glob.glob(os.path.join(BASE, 'data', 'bj_*.json')):
        m = re.search(r'bj_(\d+)\.json$', p)
        if m and int(m.group(1)) > bi:
            bi, best = int(m.group(1)), os.path.basename(p)
    return best
bjdc_path = os.path.join(BASE, 'data', _latest_bj())
if os.path.exists(bjdc_path):
    bjdc = json.load(open(bjdc_path, encoding='utf-8'))
    # ★ renderBjdc 读 D.matches（对象是 {matches:[...]}），bjdc.json 存的是列表
    #   直接注入列表 → D.matches 为空 → 北单整页渲染成"暂无数据"（第一五五条）
    if isinstance(bjdc, list):
        bjdc = {'matches': bjdc}
    # ★ 第一六八条：字段归一化（数据源 odds/num/lbl/final → 渲染层 sp/no/names/mp/rec/conf）
    #   不做这层映射，renderBjdc 里 m.sp.map 抛 TypeError → 整个 script 块中断
    #   → 北单列表和复盘全部不渲染（用户看到的就是"被删了好多东西"）。
    # ★★ 第一七九条：北单新期次（001~010）只有队名，没有 kt/date/tm/SP。
    #   kt 为 None → hbGroup 判定失败 → 全落「今日可买」，且卡片只有"SP 未获取"
    #   （用户看到的现象：北单连胜平负赔率都没了、比分是乱的）。
    #   开赛时间按队名从竞彩 matches 匹配（同一场比赛，时间是事实，不是编的）；
    #   匹配不到的保持空 → 卡片标「开赛时间未获取」。
    _jcIdx = {}
    for _jm in (full.get('matches') or []):
        _h, _a = (_jm.get('h') or '').strip(), (_jm.get('a') or '').strip()
        if _h and _a:
            _jcIdx[(_h, _a)] = _jm
    import re as _re
    def _norm(nm):
        nm = (nm or '').strip()
        for _sfx in ('U23', 'U21', 'U20', '女足', '男足', '亚运', '国家队'):
            nm = nm.replace(_sfx, '')
        nm = _re.sub(r'[\s·・]', '', nm)
        # 去掉尾部单字「亚」（竞彩常写「韩国亚/沙特亚/乌兹别亚」）
        return nm
    def _nameHit(x, y):
        # 队名口径不同（北单「乌兹别克斯坦U23」/竞彩「乌兹别亚」）→ 规范化后比前 2 字
        nx, ny = _norm(x), _norm(y)
        if not nx or not ny: return False
        if nx == ny: return True
        if nx[:2] and nx[:2] == ny[:2]: return True
        return nx in ny or ny in nx
    _nKt = 0
    _nFt = 0
    for _m in bjdc.get('matches', []):
        if _m.get('kt') and _m.get('date'):
            continue
        for (_jh, _ja), _jm in _jcIdx.items():
            if _nameHit(_m.get('h'), _jh) and _nameHit(_m.get('a'), _ja):
                _m['kt'] = (_jm.get('date') or '') + ' ' + (_jm.get('tm') or '')
                _m['date'] = _jm.get('date') or ''
                _m['tm'] = _jm.get('tm') or ''
                _m['lg'] = _m.get('lg') or _jm.get('lg') or ''
                _nKt += 1
                break
        # ★ 第一八〇条：同一场比赛的真实赛果是事实，不是编的 → 可跨玩法回填
        if not _m.get('ft'):
            for (_jh, _ja), _jm in _jcIdx.items():
                if _jm.get('ft') and _nameHit(_m.get('h'), _jh) and _nameHit(_m.get('a'), _ja):
                    _m['ft'] = _jm['ft']
                    _m['ft_note'] = _jm.get('ft_note') or _jm.get('ft')
                    _nFt += 1
                    break
    if _nKt:
        print('  北单补开赛时间：%d 场（从竞彩同名场次匹配）' % _nKt)
    if _nFt:
        print('  北单补真实赛果：%d 场（从竞彩同名场次匹配）' % _nFt)
    for _m in bjdc.get('matches', []):
        # ★ 第一六九条：让球盘 lbl 为 null 时，旧的兜底会填成「主胜/平局/客胜」，
        #   导致让4球场次显示成"主胜"——用户按主胜买，实际是让4球盘，4-0 都算输。
        #   必须按 hcap 生成正确选项名：让球盘 → 让胜/让平/让负；平手/不让球 → 胜平负。
        _lbl = _m.get('lbl')
        if not _lbl:
            _hc = str(_m.get('hcap') or '').strip()   # ★第二九一条：hcap 可能是数字（int），.strip() 直接崩
            if _hc and _hc != '平手盘' and '让' in _hc:
                _lbl = ['让胜', '让平', '让负']
            else:
                _lbl = ['主胜', '平局', '客胜']
        _m['lbl'] = _lbl
        # ★ 第二五八条：北单数据里赔率字段叫 'sp' 不叫 'odds'，
        #   旧代码只读 'odds' → 取到 None → 把真实 sp 覆盖成 [null,null,null]
        #   → hasOdds=false → 页面 _spOk=false → 第二道清空 top3/big/upset。
        _odds = _m.get('odds') or _m.get('sp')
        _m['no'] = _m.get('no') or _m.get('num')
        _m['num'] = _m['no']
        _m['names'] = _lbl
        # ★ 第三〇三条：_odds 可能是字符串数组（enrich 里 odds='%.2f'），
        #   而页面 _spOk 要求 typeof v==='number' → 字符串全被判「SP未获取」
        #   → 399 场全部显示「胜平负 SP 未获取」，方向/概率/比分全被清空。
        #   这里统一转 float；转不动才置 None。
        _sp = None
        for _src in (_m.get('o'), _m.get('sp'), _odds):
            if isinstance(_src, list) and len(_src) == 3:
                try:
                    _sp = [float(x) for x in _src]
                    break
                except (TypeError, ValueError):
                    _sp = None
        _m['sp'] = _sp if _sp else [None, None, None]
        _m['hasOdds'] = isinstance(_odds, list) and len(_odds) == 3
        # ★ 第一六九条：官方未开售/无赔率的场次，不推方向、不编概率（原显示「让胜 0%」是假的）
        _m['noOdds'] = not _m['hasOdds']
        # ★ 第二五八条：北单没有 final/market 字段（概率在 fus），
        #   旧代码 fallback 到 [] → mp=[0,0,0] → 卡片概率位显示 0%，与 fus 矛盾。
        _fin = _m.get('final') or _m.get('market') or _m.get('fus') or []
        _m['mp'] = [int(round(x)) for x in _fin] if len(_fin) == 3 else [0, 0, 0]
        _mi = _lbl.index(_m['main']) if (_m.get('main') in _lbl and _m['hasOdds']) else None
        _m['rec'] = _mi
        _m['conf'] = _m.get('main_p') or (_m['mp'][_mi] if (_mi is not None and len(_m['mp']) == 3) else 0)
        _c = _m['conf'] or 0
        _m['star'] = 5 if _c >= 70 else (4 if _c >= 60 else (3 if _c >= 50 else 2))

    # ★ 北单补算：SP 有值但 fus/final 缺失 → mp 被填成 [0,0,0]，卡片显示 0%、方向空、无分析。
    #   这里用去水概率补齐 mp/conf/star/main，并写一段可核查的分析（只用本页 SP + 归档真实赛果）。
    import os as _os
    _arc_path = _os.path.join(BASE, 'data', '_archive_done.json')
    _bst = {'tot': 0, 'draw': 0, 'flip': 0, 'fl': {}, 'lg': {}, 'band': {}}
    try:
        _arc = json.load(open(_arc_path, encoding='utf-8'))
        for _x in _arc:
            if not _x.get('actual'):
                continue
            _bst['tot'] += 1
            if _x['actual'] == '平局':
                _bst['draw'] += 1
            if _x.get('main') and _x['actual'] != _x.get('main'):
                _bst['flip'] += 1
                _bst['fl'][_x['actual']] = _bst['fl'].get(_x['actual'], 0) + 1
            _g = _x.get('lg') or ''
            if _g:
                _d = _bst['lg'].setdefault(_g, [0, 0])
                _d[1] += 1
                if _x['actual'] == '平局':
                    _d[0] += 1
            if _x.get('main_p') and _x.get('actual'):
                _b0 = int(float(_x['main_p']) // 5) * 5
                _s0 = _bst['band'].setdefault(_b0, [0, 0])
                _s0[1] += 1
                if _x['actual'] == _x.get('main'):
                    _s0[0] += 1
    except Exception:
        pass
    _nFix = 0
    # 澳客北单情报（近况/交锋），由 scripts/fetch_bj_okooo.py 抓取；缺文件就当没有
    try:
        _bjo = json.load(open(os.path.join(BASE, 'data', 'bj_okooo.json'), encoding='utf-8'))
    except Exception:
        _bjo = {}
    for _m in bjdc.get('matches', []):
        if _m.get('ana'):
            continue
        _sp = _m.get('sp') or []
        _ok = len(_sp) == 3 and all(isinstance(v, (int, float)) and v > 1.001 for v in _sp)
        _lb = _m.get('lbl') or ['主胜', '平局', '客胜']
        if not _ok:
            _m['ana'] = ('【分析】本场 SP 未获取（官方未开售或无盘口），按铁律不推方向、不编概率，只列赛程；'
                         '开售后自动补。')
            continue
        if not any(_m.get('mp') or []):
            _inv = [1.0 / x for x in _sp]
            _sum = sum(_inv)
            _p3 = [x / _sum * 100 for x in _inv]
            _m['mp'] = [int(round(x)) for x in _p3]
            _mi0 = max(range(3), key=lambda i: _p3[i])
            _m['main'] = _lb[_mi0]
            _m['rec'] = _mi0
            _m['conf'] = _m['mp'][_mi0]
            _c0 = _m['conf']
            _m['star'] = 5 if _c0 >= 70 else (4 if _c0 >= 60 else (3 if _c0 >= 50 else 2))
            _nFix += 1
        _mp = _m.get('mp') or [0, 0, 0]
        _mi = _m.get('rec')
        _top = _mp[_mi] if isinstance(_mi, int) and len(_mp) == 3 else max(_mp)
        _parts = ['【定价】SP %.2f/%.2f/%.2f 去水后 %.1f/%.1f/%.1f，主推 %s。'
                  % (_sp[0], _sp[1], _sp[2], _mp[0], _mp[1], _mp[2], _lb[_mi] if isinstance(_mi, int) else _lb[0])]
        _b = int(_top // 5) * 5
        _s2 = _bst['band'].get(_b)
        if _s2 and _s2[1] >= 8:
            _hit = _s2[0] / _s2[1] * 100
            _parts.append('【同档校准】%d-%d%% 档归档 %d 场命中 %.1f%%（差 %+.1f）。'
                          % (_b, _b + 5, _s2[1], _hit, _hit - _top))
        else:
            _parts.append('【同档校准】%d-%d%% 档归档不足 8 场，样本不足不评。' % (_b, _b + 5))
        if _bst['tot']:
            _parts.append('【翻车形态】归档 %d 场主推未中 %d 场（%.1f%%），其中平局 %d、客胜 %d、主胜 %d；'
                          '全样本平局率 %.1f%%。'
                          % (_bst['tot'], _bst['flip'], _bst['flip'] / _bst['tot'] * 100,
                             _bst['fl'].get('平局', 0), _bst['fl'].get('客胜', 0), _bst['fl'].get('主胜', 0),
                             _bst['draw'] / _bst['tot'] * 100))
        _lgm = _m.get('lg') or ''
        _lsm = _bst['lg'].get(_lgm)
        if _lsm and _lsm[1] >= 8:
            _parts.append('【联赛平局特性】%s 归档 %d 场平局 %d 场（%.1f%%）。'
                          % (_lgm, _lsm[1], _lsm[0], _lsm[0] / _lsm[1] * 100))
        else:
            _parts.append('【联赛平局特性】%s 归档样本不足 8 场，不给基准。' % (_lgm or '本场联赛'))
        # 近况/交锋：澳客比赛页（fetch_bj_okooo.py 抓的），有就写、没有就照实说缺
        _oi = _bjo.get(str(_m.get('no'))) or _bjo.get(_m.get('no'))
        if _oi and (_oi.get('home') or _oi.get('away')):
            _hv, _av = _oi.get('home') or {}, _oi.get('away') or {}
            _line = '【近况·澳客】'
            if _hv:
                _line += '%s 近10场 %d胜%d平%d负' % (_m.get('h'), _hv.get('w', 0), _hv.get('d', 0), _hv.get('l', 0))
                if _hv.get('venue'):
                    _v = _hv['venue']
                    _line += '（主场 %d胜%d平%d负）' % (_v.get('w', 0), _v.get('d', 0), _v.get('l', 0))
                _line += '%s' % ('；' if _av else '。')
            if _av:
                _line += '%s 近10场 %d胜%d平%d负' % (_m.get('a'), _av.get('w', 0), _av.get('d', 0), _av.get('l', 0))
                if _av.get('venue'):
                    _v = _av['venue']
                    _line += '（客场 %d胜%d平%d负）' % (_v.get('w', 0), _v.get('d', 0), _v.get('l', 0))
                _line += '。'
            _parts.append(_line)
            if _oi.get('h2h'):
                _h2 = _oi['h2h']
                _sub = '【交锋】往绩主队 %d胜%d平%d负' % (_h2.get('w', 0), _h2.get('d', 0), _h2.get('l', 0))
                if _h2.get('venue'):
                    _v = _h2['venue']
                    _sub += '，主场 %d胜%d平%d负' % (_v.get('w', 0), _v.get('d', 0), _v.get('l', 0))
                _parts.append(_sub + '（澳客统计，只作参考，不进模型）。')
            _parts.append('【情报缺口】澳客已给近况与交锋；500 数据页被 EdgeOne 拦，阵容/伤停/推介未采集，不编。')
        else:
            _parts.append('【情报缺口】本场没跑 500 数据页，近况/阵容/交锋留空不编；要看就说一声，我按竞彩那条链路补抓。')
        _parts.append('【结论】%s %.1f%%%s。北单返奖率约 65%%，同样一笔钱长期亏得比竞彩多，注量要压住。'
                      % (_lb[_mi] if isinstance(_mi, int) else _lb[0], _top,
                         '，平局偏热方向不稳，可考虑整场放弃' if _mp[1] >= 27 else '，按单场口径执行，不做长串'))
        _m['ana'] = '\n'.join(_parts)
        _m['ana_ver'] = 'bj-inline'
    if _nFix:
        print('  北单补算概率：%d 场（SP 有值但 fus 缺失）' % _nFix)

    # 北单页只放「在售/未开赛」：抓回来的 _bj_latest_full 跨 4 个销售日（含已完赛 18 场，
    # 前一销售日还有「中国 vs 巴林」这类旧场），原样注入会让用户看到上一期的比赛还在。
    # 已完赛的场次整块转进复盘，不再出现在「在售」列表。
    _bj_all = bjdc.get('matches', [])
    _bj_live = [m for m in _bj_all if not m.get('ft')]
    _bj_done = [m for m in _bj_all if m.get('ft')]
    _bjdc_out = {k: v for k, v in bjdc.items() if k != 'matches'}
    _bjdc_out['matches'] = _bj_live
    _bjdc_out['done_total'] = len(_bj_done)
    print('  北单在售 %d 场（已完赛 %d 场转复盘，不再列在售）' % (len(_bj_live), len(_bj_done)))

    inline += '<script>window.__BJDC__=%s;</script>\n' % jd(
        _bjdc_out, ensure_ascii=False, separators=(',', ':'))

# 北单基本面调研（逐场：排名/状态/伤停/交锋/战意 + 矛盾提示）
bjdc_r_path = os.path.join(BASE, 'data', 'bjdc_research.json')
if os.path.exists(bjdc_r_path):
    bjdc_r = json.load(open(bjdc_r_path, encoding='utf-8'))
    # ★ 第二五〇条：__BJDC_R__ 死数据块已删（页面零读取点；清理过期数据）

# ★ 任九 26132 简洁推荐（方向+双选+平局+比分）
sp_path = os.path.join(BASE, 'data', 'sfc_pick.json')
if os.path.exists(sp_path):
    spd = json.load(open(sp_path, encoding='utf-8'))
    # ★ 第一八〇条：任九与竞彩是同一批比赛，赛果是事实 → 按队名回填
    _ftIdx2 = {}
    for _jm in (full.get('matches') or []):
        if _jm.get('ft'):
            _ftIdx2[(_jm.get('h'), _jm.get('a'))] = _jm['ft']
    # ★ 第二二九条：欧国联等胜负彩独有场次，竞彩 full.json 里没有 → 赛果取不到，
    #   任九卡片永远不显示已完赛。赛果是事实，按队名从当期胜负彩源补一次。
    try:
        _sfc_now_raw = json.load(open(os.path.join(BASE, 'data', 'sfc26133.json'), encoding='utf-8'))
        for _sm in _sfc_now_raw:
            if _sm.get('ft') and (_sm.get('h'), _sm.get('a')) not in _ftIdx2:
                _ftIdx2[(_sm.get('h'), _sm.get('a'))] = _sm['ft']
    except Exception:
        pass
    def _sfcFt(t):
        return _ftIdx2.get((t.get('h'), t.get('a')))
    _nS = 0
    for t in spd:
        _f = _sfcFt(t)
        if _f and not t.get('ft'):
            t['ft'] = _f
            try:
                _i, _j = [int(x) for x in _f.split('-')[:2]]
                t['res'] = 0 if _i > _j else (1 if _i == _j else 2)
            except Exception:
                t['res'] = None
            t['done'] = True
            _nS += 1
    if _nS:
        print('  任九补真实赛果：%d 场' % _nS)
    # ★ 第一八七条：sfc_pick.json 缺四档中的「爆冷」→ 从 sfc26132.json 按队名补齐
    _up_path = os.path.join(BASE, 'data', 'sfc26132.json')
    if os.path.exists(_up_path):
        try:
            _upd = json.load(open(_up_path, encoding='utf-8'))
            _upms = _upd['matches'] if isinstance(_upd, dict) else _upd
            _upIdx = {}
            for _m in _upms:
                if _m.get('h') and _m.get('a'):
                    _upIdx[(_m.get('h'), _m.get('a'))] = _m
            _nU = 0
            for t in spd:
                _m = _upIdx.get((t.get('h'), t.get('a')))
                if not _m:
                    continue
                if not t.get('upset') and _m.get('upset'):
                    t['upset'] = _m['upset']; _nU += 1
                if not t.get('big') and _m.get('big'):
                    t['big'] = _m['big']
            if _nU:
                print('  任九补爆冷档：%d 场' % _nU)
        except Exception as _e:
            print('  任九爆冷补齐失败：%s' % _e)
    # ★ 第二九六条（致命·连续多轮"任九没有"的真正根因）：
    #   sfcPickBlock() 读的是 __SFC_PICK__（不是 __SFC_NOW__），而这里原样注入 sfc_pick.json，
    #   从未做字段映射。渲染函数需要的 fus / date / alt / two / draw_cand 一概不存在：
    #     · t.fus[i] → undefined[i] → TypeError → 整块面板渲染中断 → 任九页全白（无任何报错提示）
    #     · t.date 为空 → 时间只显示 "22:00" 缺日期
    #   → 数据层 14/14 全有、渲染层一片空白，且 node --check 与桩DOM 都查不出来。
    #   修法：注入前统一规范化字段名 + 派生缺失字段。
    _LB3 = ['主胜', '平局', '客胜']
    for _t in (spd or []):
        _p = _t.get('p') or [0, 0, 0]
        _t['fus'] = _t.get('fus') or _p                       # 三向概率：p → fus
        _t['date'] = _t.get('date') or _t.get('tm') or ''     # 日期：tm → date
        _dp = float(_t.get('draw_p') or 0)
        if _t.get('draw_cand') is None:
            _t['draw_cand'] = _dp >= 25.0
        if _t.get('draw_push') is None:
            _t['draw_push'] = False
        # 双选/备选：数据无 alt 时，按概率次高方向派生
        if not _t.get('alt') and len(_p) == 3 and max(_p) > 0:
            _srt = sorted(range(3), key=lambda i: -_p[i])
            if len(_srt) > 1 and _p[_srt[1]] > 0:
                _t['alt'] = _LB3[_srt[1]]
                _t['alt_p'] = round(_p[_srt[1]], 1)
        if _t.get('two') is None:
            _t['two'] = bool(_t.get('alt'))
        for _k in ('top3', 'big', 'refs'):                    # 数组字段兜底，防再崩
            if _t.get(_k) is None:
                _t[_k] = []
    inline += '<script>window.__SFC_PICK__=%s;</script>\n' % jd(
        spd, ensure_ascii=False, separators=(',', ':'))
    print('  任九推荐 %d 场' % len(spd))
    # ★ 第一八〇条：任九复盘（已出结果的场次，逐场对照赛前推→实际）
    _LB = ['主胜', '平局', '客胜']
    _rows = []
    for t in spd:
        if not t.get('ft'):
            continue
        _r = t.get('res')
        _act = _LB[_r] if _r is not None else None
        _main = t.get('main')
        _mp = t.get('main_p')
        _t3 = [x[0] for x in (t.get('top3') or [])]
        _big = (t.get('big') or [None])[0] if t.get('big') else None
        _up = (t.get('upset') or [None])[0] if t.get('upset') else None
        _tot = t.get('tot')
        try:
            _ai, _aj = [int(x) for x in t['ft'].split('-')[:2]]
            _asum = _ai + _aj
            _jx = ('闷战' if _tot < 1.6 else '小球' if _tot < 2.3 else '中等' if _tot < 3.0 else '对攻') if _tot else None
            _jxA = ('闷战' if _asum < 2 else '小球' if _asum < 3 else '中等' if _asum < 4 else '对攻')
        except Exception:
            _asum = None; _jx = None; _jxA = None
        _rows.append({
            'no': t.get('no'), 'lg': t.get('lg'), 'h': t.get('h'), 'a': t.get('a'),
            'date': t.get('date'), 'isHcap': False, 'hcap': '',
            'main': _main, 'main_p': _mp, 'alt': t.get('alt'), 'alt_p': t.get('alt_p'),
            'two': t.get('two'), 'ft': t.get('ft'), 'note': '', 'actual': _act,
            'dirHit': (_act is not None and _main is not None and _act == _main),
            'top3': _t3, 'top3Hit': t.get('ft') in _t3,
            'big': _big, 'bigHit': (_big == t.get('ft')),
            'upset': _up, 'upsetHit': (_up == t.get('ft')),
            'tot_p': _tot, 'tot_a': _asum, 'jx_p': _jx, 'jx_a': _jxA,
            'jxHit': (_jx is not None and _jx == _jxA),
        })
    if _rows:
        _n = len(_rows)
        _d = sum(1 for r in _rows if r['dirHit'])
        _s = {'n': _n, 'dirHit': _d, 'dirPct': round(_d * 100.0 / _n, 1),
              'top3': sum(1 for r in _rows if r['top3Hit']),
              'top3Pct': round(sum(1 for r in _rows if r['top3Hit']) * 100.0 / _n, 1),
              'big': sum(1 for r in _rows if r['bigHit']),
              'bigPct': round(sum(1 for r in _rows if r['bigHit']) * 100.0 / _n, 1),
              'upset': sum(1 for r in _rows if r['upsetHit']),
              'upsetPct': round(sum(1 for r in _rows if r['upsetHit']) * 100.0 / _n, 1),
              'jx': sum(1 for r in _rows if r['jxHit']),
              'jxPct': round(sum(1 for r in _rows if r['jxHit']) * 100.0 / _n, 1)}
        inline += '<script>window.__SFC_REVIEW__=%s;</script>\n' % jd(
            {'date': '', 'src': '竞彩同名场次真实赛果回填', 'stat': _s, 'rows': _rows},
            ensure_ascii=False, separators=(',', ':'))
        print('  任九复盘 %d 场：方向 %d/%d' % (_n, _d, _n))

# ★ 当期任九（26132）推荐数据：字段对齐 srowHTML，供 renderR9/auto9/存档 使用。
#   背景：页面原本只有 __SFC__（sfc.json = 26131 期，9-20 截止、9-21 已开奖），
#   导致选号区标题一直显示「第 26131 期」——是过期期次。新算的 26132 期在
#   data/sfc26132.json，却只注入成了 __SFC_PICK__，选号主区读不到。
#   __SFC__ 保留给复盘（有 score/res/done 真实赛果），当期推荐另走 __SFC_NOW__。
now_path = os.path.join(BASE, 'data', 'sfc26136.json')
# ★ 第二三二条：当期期次改为动态读取，不再硬编码（曾因硬编码 26133 导致过期期次一直显示）
# ★ 第二七〇条：期次/截止 动态读取 sfc_pick.json，不再硬编码
#   （曾因硬编码 26137 导致 26138 期已开售仍显示过期期次）
_SFC_DL = {'26138': '2026-10-11 20:30（中国体彩网官方公告）',
           '26139': '2026-10-12 22:00（中国体彩网官方公告）',
           # ★第二七九条：26140 截止原误写为 10-16（那是 26142），实为 10-13 22:00
           '26140': '2026-10-13 22:00（中国体彩网官方公告·欧冠+英冠，今晚截止）',
           '26141': '2026-10-14 22:00（中国体彩网官方公告）',
           '26142': '2026-10-15 22:00（中国体彩网官方公告·欧罗巴）',
           # ★第二八一条：26144 截止 10-17 21:00（500足彩页官方售彩截止时间）
           '26144': '2026-10-17 21:00（500足彩页官方售彩截止时间）',
           '26145': '2026-10-18 20:30（中国体彩网官方公告·英超+德甲+意甲+西甲+法甲）',
           '26146': '2026-10-21 22:00（500足彩页·欧冠，已截止待开奖）',
           # ★第二八四条：26147 截止 10-22 22:00（500足彩页官方售彩截止时间·欧罗巴14场）
           '26147': '2026-10-22 22:00（500足彩页官方售彩截止时间·欧罗巴14场）',
           # ★第二九〇条：26148 为 10-24 各国联赛，截止 10-23 22:00
           #   （500足彩页显示 26148~26152 均为官方在售，26147 为当前期）
           '26148': '2026-10-23 22:00（500足彩页官方售彩截止时间·10-24各国联赛14场）',
           # ★第二九一条：26149 为 10-24/25 英超+德甲+意甲+西甲，截止 10-24 21:00
           #   500 页 expect=26149 顶部「官方售彩截止时间：10-24 21:00」；
           #   官方赔率列当时仍为 ---（未开盘），欧赔来自澳客，排名两源一致
           '26149': '2026-10-24 21:00（500足彩页官方售彩截止时间·10-24/25四大联赛14场）',
           # ★第三五八条：26155 截止 11-01 21:30（澳客任九页原文「停售11-01 21:30」）。
           #   500 足彩页当日仍显示「当前第26154期」（10-31 22:00 已截止），
           #   新期未放出 → 只能以澳客页为准，不 fallback 到旧期默认值。
           '26155': '2026-11-01 21:30（澳客任九页·停售11-01 21:30）',
           # 26156 截止 11-02 22:00（澳客任九页原文「停售11-02 22:00」）
           '26156': '2026-11-02 22:00（澳客任九页·停售11-02 22:00）',
           # 26157 截止 11-03 22:00（澳客任九页原文「停售11-03 22:00」·欧冠8+英冠6）
           '26157': '2026-11-03 22:00（澳客任九页·停售11-03 22:00）',
           # 26158 截止 11-04 17:30（500足彩页「官方售彩截止时间：11-04 17:30」）
           '26158': '2026-11-04 17:30（500足彩页官方售彩截止时间·亚冠2+欧冠8+英冠3+巴甲1）',
           # 26159 截止 11-05 22:00（澳客任九页原文「停售11-05 22:00」·欧罗巴14场）
           '26159': '2026-11-05 22:00（澳客任九页·停售11-05 22:00·欧罗巴14场）',
           # 26160 截止 11-06 22:00（澳客任九页原文「停售11-06 22:00」+500足彩页双源）
           '26160': '2026-11-06 22:00（澳客任九页·停售11-06 22:00·11-07各国联赛14场）',
           # 26161 截止 11-07 21:30（澳客任九页「停售11-07 21:30」+500足彩页官方售彩截止时间双源）
           '26161': '2026-11-07 21:30（澳客任九页·停售11-07 21:30·500足彩页官方售彩截止时间·英超3+德甲5+意甲4+西甲2）',
           # 26162 截止 11-08 21:30（澳客任九页原文「停售11-08 21:30」+500足彩页「官方在售第26162期」双源）
           '26162': '2026-11-08 21:30（澳客任九页·停售11-08 21:30·英超4+德甲3+意甲4+西甲3）',
           # 26163 截止 11-12 22:00（澳客任九页原文「停售11-12 22:00」·欧国联14场）
           '26163': '2026-11-12 22:00（澳客任九页·停售11-12 22:00·欧国联14场）',
           # 26164 截止 11-14 19:30（500足彩页「官方售彩截止时间：11-14 19:30」+澳客26164页「停售11-14 19:30」双源）
           #   本期14场：国际赛1+欧国联12+巴甲1；其中08/09/10三场澳客欧赔全0.00，标 no_odds 不编概率
           '26164': '2026-11-14 19:30（500足彩页官方售彩截止时间·澳客26164页停售11-14 19:30·国际赛1+欧国联12+巴甲1）',
           # ★第三二九条：26150 截止 10-25 21:30（500足彩页）
           '26150': '2026-10-25 21:30（500足彩页官方售彩截止时间）',
           # ★第三二九条：26151 截止 10-27 17:30，实抓 500 默认页
           #   「当前第26151期 / 官方在售第26152期 / 官方售彩截止时间：10-27 17:30」
           #   与赛程吻合：01-04 亚冠 10-27 18:00 开踢，截止在开赛前
           '26151': '2026-10-27 17:30（500足彩页官方售彩截止时间·亚冠4+德国杯6+意甲3+瑞典超1）'}
try:
    _pk = json.load(open(os.path.join(BASE, 'data', 'sfc_pick.json'), encoding='utf-8'))
    SFC_ISSUE = str((_pk[0] if isinstance(_pk, list) and _pk else {}).get('issue') or '26140')
    # ★ 第三〇四条：模板里的期号一律用占位符，这里统一替换。
    #   写死在模板 = 每次 build 都把旧期号带回来（同'核心定义'那次病）。
except Exception:
    SFC_ISSUE = '26140'
# ★★ 第三二九条：★绝不能再 fallback 到某个具体旧日期★
#   原写法 _SFC_DL.get(期号, '2026-10-11 20:30') —— 26138 的截止被当成默认值，
#   导致 26150/26151 一直显示 10-11，比比赛日 10-28 还早 17 天（用户当场发现）。
#   期次表未覆盖时，必须标「待核实」，而不是编一个看似合理的日期。
# ★ 第五二条（本次修复）：停售时间别写「待核实」——澳客期次页本身就标了停售时间，
#   fetch_sfc_okooo.py 已经把它落进 data/sfc_okooo.json；这里按当期读回来。
_SFC_META = {}
try:
    _mp = os.path.join(BASE, 'data', 'sfc_okooo.json')
    if os.path.exists(_mp):
        _SFC_META = json.load(open(_mp, encoding='utf-8'))
except Exception:
    _SFC_META = {}
if str(_SFC_META.get('issue') or '') == str(SFC_ISSUE) and _SFC_META.get('deadline'):
    SFC_DEADLINE = '停售 %s（澳客期次页标注）' % _SFC_META['deadline']
else:
    SFC_DEADLINE = _SFC_DL.get(SFC_ISSUE) or ('%s 截止时间待核实（期次表未收录，请查澳客/体彩页）' % SFC_ISSUE)
# ★★ 第一八〇条（第一三五条复发）：任九曾有两套数据源并存
#   data/sfc_pick.json（选号卡片读 __SFC_PICK__）与 data/sfc26132.json（__SFC_NOW__）
#   两者在 002 澳大利亚vs巴西（客胜 67.6% vs 88.2%、tot 2.82 vs 3.89）、
#   003 荷兰vs德国（主推 客胜 vs 主胜）上直接矛盾 —— 同一玩法两套数据必错位。
#   → 统一以 sfc_pick.json 为准（与竞彩官方赔率一致），
#     sfc26132.json 只贡献 deep/refs/note/伤停 等辅助字段。
_pick_path = os.path.join(BASE, 'data', 'sfc_pick.json')
if os.path.exists(_pick_path):
    _nd = json.load(open(_pick_path, encoding='utf-8'))
    try:
        _aux = {str(t.get('no')): t for t in json.load(open(now_path, encoding='utf-8'))}
    except Exception:
        _aux = {}
    for _t in _nd:
        _x = _aux.get(str(_t.get('no')))
        if _x:
            for _k in ('deep', 'refs', 'note', 'inj_home', 'inj_away', 'form', 'h2h', 'hist', 'upset'):
                if not _t.get(_k) and _x.get(_k):
                    _t[_k] = _x[_k]
    print('  任九数据源统一为 sfc_pick.json（与竞彩官方赔率一致），sfc26132.json 仅补辅助字段')
else:
    _nd = json.load(open(now_path, encoding='utf-8')) if os.path.exists(now_path) else []
# ★ 第一八〇条：下面这段构建 _now 的逻辑两个分支都要跑，不能塞进 elif 里（曾导致 __SFC_NOW__ 整块不注入）
if _nd:
    # ★ 第一七一条：胜负彩源文件只有 date（无开赛时刻），旧代码把 date 塞进 tm、
    #   date 字段根本没写 → matchStatus() 取不到 m.date → 永远返回 null
    #   → hbGroup 走销售日比较又取不到日期 → 14 场一律判成「今日可买」，
    #   连 9-24 19:35 已踢完的 001 中国vs马尔代夫 也显示能买。
    #   修法：补 date；tm 从竞彩 full['matches'] 按队名匹配真实开赛时刻。
    _tmIdx = {}
    for _m in (full.get('matches') or []):
        _k = (_m.get('h'), _m.get('a'))
        if _m.get('tm'):
            _tmIdx[_k] = _m['tm']
            _tmIdx.setdefault((_m.get('date'), _m.get('tm')), None)
    _matches = []
    for t in _nd:
        _refs = t.get('refs') or []
        _why = t.get('note') or (_refs[0] if _refs else '')
        _tm = _tmIdx.get((t.get('h'), t.get('a'))) or (t.get('tm') or '')
        _sfc_ft = _ftIdx2.get((t.get('h'), t.get('a')))
        _sfc_res = None
        if _sfc_ft:
            try:
                _i, _j = [int(x) for x in _sfc_ft.split('-')[:2]]
                _sfc_res = 0 if _i > _j else (1 if _i == _j else 2)
            except Exception:
                _sfc_res = None
        _matches.append({
            'no': t.get('no'), 'lg': t.get('lg'),
            # ★ 第二九六条：'date' 取自 t['date']，但 sfc_pick.json 里该字段名为 'tm'
            #   → date 恒为空串，页面上时间显示成 "22:00"（缺日期）。
            'date': t.get('date') or t.get('tm') or '', 'tm': _tm, 'h': t.get('h'), 'a': t.get('a'),
            # ★ 第二九六条（致命）：渲染函数 sfcPickBlock 读 t.fus[i] 显示三向概率，
            #   而本处从未生成 'fus'（数据里三向概率字段名叫 'p'）
            #   → t.fus 为 undefined → TypeError → 整块任九面板渲染中断 → 页面空白。
            #   这是我连续多轮"任九没有"却查不出原因的真正根因。
            'fus': t.get('fus') or t.get('p') or [0, 0, 0],
            # 备选/双选：数据里无 alt/two 时按概率派生，避免按钮"备选"标记全丢
            'alt': t.get('alt'), 'alt_p': t.get('alt_p'),
            'two': t.get('two') if t.get('two') is not None else bool(t.get('alt')),
            # 平局候选：draw_p 高于阈值即标记（原字段 draw_cand 从未生成）
            'draw_cand': t.get('draw_cand') if t.get('draw_cand') is not None
                         else (float(t.get('draw_p') or 0) >= 25.0),
            'draw_push': t.get('draw_push') or False,
            'rec': t.get('main'), 'conf': t.get('main_p'),
            'recwhy': _why,
            'pre': t.get('final') or None,
            'done': bool(_sfc_ft), 'score': _sfc_ft, 'res': _sfc_res,
            # 附加：让卡片能显示四档比分 / 双选 / 平局 / 深挖
            'top3': t.get('top3'), 'big': t.get('big'), 'upset': t.get('upset'),
            'tot': t.get('tot'), 'feat': t.get('feat'),
            'gap': t.get('gap'),
            'draw_p': t.get('draw_p'), 'refs': _refs, 'deep': t.get('deep'),
            'odds': t.get('odds'), 'src': t.get('src'), 'hist': t.get('hist'),
            # ★ 第二八七条：ana 原漏同步 → __SFC_NOW__（卡片真正读取的源）里 ana 全空，
            #   页面上一句分析都看不到。必须在这里显式带上。
            'ana': t.get('ana'), 'ana_src': t.get('ana_src'),
        })
    # ★ 第二八八条：_来源 文案原为硬编码旧状态（"0/14 一致…0 场竞彩未开售已标暂无官方赔率"），
    #   与真实数据（14/14 有澳客欧赔）严重不符 —— 用户看到这句就直接判定"任九又没赔率了"。
    #   改为按 matches 实际字段动态统计，绝不再写死。
    _nOdds = len([x for x in _matches if x.get('odds')])
    _nNo   = len([x for x in _matches if not x.get('odds')])
    _nAna  = len([x for x in _matches if x.get('ana')])
    _srcSet = sorted(set(str(x.get('src') or '').split('（')[0].strip()
                         for x in _matches if x.get('src')))
    _srcTxt = '；'.join(_srcSet) if _srcSet else '本轮无赔率来源'
    # ★第三二九条：场次不足 14 时必须说明缺哪几场、为什么缺，不能让用户以为本期只有这么多场。
    #   实测 26151：官方 14 场，01-04 亚冠精英澳客显示"—"未开盘，故只有 05-14 共 10 场有欧赔。
    _miss = ''
    if len(_matches) < 14:
        _have = set(str(x.get('no')).zfill(2) for x in _matches)
        _lack = [('%02d' % i) for i in range(1, 15) if ('%02d' % i) not in _have]
        _miss = ('　|　⚠️ 官方本期共 14 场，缺 %s 共 %d 场：澳客/官方均未开盘（欧赔栏显示「—」）'
                 '，本页不编造概率，仅展示有欧赔的 %d 场'
                 % ('、'.join(_lack), len(_lack), len(_matches)))
    _now = {'_期次': SFC_ISSUE, '_截止': SFC_DEADLINE,
            '_来源': '赛程：中国体彩网 %s 期官方公告　|　赔率：%s　→　%d/%d 场有欧赔、%d 场暂无（竞彩/官方均未开售，不编造）　|　逐场分析 %d/%d'
                     % (SFC_ISSUE, _srcTxt, _nOdds, len(_matches), _nNo, _nAna, len(_matches)) + _miss,
            'matches': _matches}
    inline += '<script>window.__SFC_NOW__=%s;</script>\n' % jd(
        _now, ensure_ascii=False, separators=(',', ':'))
    print('  任九当期(%s) %d 场' % (_now.get('_期次','?'), len(_matches)))

sfc_path = os.path.join(BASE, 'sfc.json')
if os.path.exists(sfc_path):
    sfc = json.load(open(sfc_path, encoding='utf-8'))
    # ★ 第二五〇条：__SFC__ 死数据块已删（页面零读取点；26131期赛果已存档 data/_archived_sfc26131.json）


# ★ 复盘数据（真实赛果，联网调研）
_rev = os.path.join(BASE, 'data', 'review_0923.json')
if os.path.exists(_rev):
    _rd = json.load(open(_rev, encoding='utf-8'))
    # ★ 第二五〇条：__REVIEW__ 死数据块已删（页面零读取点；清理过期数据）
# ★ 9-23 今日亚运男足复盘（中国0-0阿联酋 / 伊朗1-4朝鲜）
_r923b = os.path.join(BASE, 'data', 'review_0923b.json')
if os.path.exists(_r923b):
    _r2 = json.load(open(_r923b, encoding='utf-8'))
    # ★ 第二五〇条：__REVIEW_0923B__ 死数据块已删（页面零读取点；清理过期数据）
    print('  9-23亚运复盘 %d 场' % len(_r2.get('rows', [])))

# ★ 大乐透「本期推荐 2-3 注」（按期推荐，不是按天）
_dltp = os.path.join(BASE, 'dlt_pick.json')
if os.path.exists(_dltp):
    _dp = json.load(open(_dltp, encoding='utf-8'))
    inline += '<script>window.__DLT_PICK__=%s;</script>\n' % jd(
        _dp, ensure_ascii=False, separators=(',', ':'))
    print('  大乐透推荐 %s 期 %d 注' % (_dp.get('issue'), len(_dp.get('plans', []))))
else:
    print('  ⚠ 缺 dlt_pick.json（大乐透本期推荐未生成）')

# ⚠️ 注入点用正则宽松匹配：曾因在 <script> 后插入代码导致硬编码 marker 失配
#    （表现为"未找到注入点"并且产出的是旧文件，极难排查）
# ★ 第二〇五条：内联数据统一后处理
#   1) kt 补全 —— 老批次只有 date+tm，缺 kt 会让「已开赛自动下架」对那批永远失效
#   2) 让球盘 lbl/main/alt 归一化 —— main 不在 lbl 里会让用户按错误标签下单
#   3) f 字段归一化（dict/None -> []）—— 避免 .map/.filter 崩溃
import re as _re2

_HL = ['\u8ba9\u80dc', '\u8ba9\u5e73', '\u8ba9\u8d1f']   # 让胜/让平/让负
_NL = ['\u4e3b\u80dc', '\u5e73\u5c40', '\u5ba2\u80dc']   # 主胜/平局/客胜

def _blk(src, key):
    for mt in _re2.finditer(r'window\.' + key + r'\s*=\s*', src):
        i = mt.end(); depth=0; j=i; inq=False; esc=False
        while j < len(src):
            c = src[j]
            if inq:
                if esc: esc=False
                elif c == '\\\\': esc=True
                elif c == '"': inq=False
            else:
                if c == '"': inq=True
                elif c in '[{': depth+=1
                elif c in ']}':
                    depth-=1
                    if depth==0: j+=1; break
                elif c == ';' and depth==0: break
                elif c == '\\n' and depth==0: break
            j+=1
        try: return (i, j, json.loads(src[i:j]))
        except Exception: pass
    return None

def _is_hcap(m):
    hc = m.get('hcap') or ''
    if isinstance(hc, str) and ('\u8ba9' in hc) and ('\u5e73\u624b' not in hc): return True
    return m.get('lbl') == _HL

def _fix_one(m):
    if not m.get('kt'):
        d = m.get('date') or ''; t = m.get('tm') or ''
        if d and t and _re2.match(r'^\d{1,2}:\d{2}$', t):
            hh, mm = t.split(':')
            m['kt'] = '%s %02d:%s' % (d, int(hh), mm)
    r = m.get('r') or {}
    if _is_hcap(m):
        if m.get('lbl') != _HL: m['lbl'] = _HL
        _ix = {'\u4e3b\u80dc':0,'\u5e73\u5c40':1,'\u5ba2\u80dc':2,
               '\u8ba9\u80dc':0,'\u8ba9\u5e73':1,'\u8ba9\u8d1f':2}
        for k in ('main','alt'):
            v = m.get(k) or r.get(k)
            if v in _ix and v not in _HL:
                if m.get(k): m[k] = _HL[_ix[v]]
                if r.get(k): r[k] = _HL[_ix[v]]
    for h in (m, r):
        if isinstance(h, dict) and 'f' in h and not isinstance(h['f'], list):
            h['f'] = []
    return m

def _norm_inline(s):
    """从 __SFC_PICK__ 建队名->kt 索引，再回填其余块（跨源回填的是开赛时间这一事实）"""
    idx = {}
    b = _blk(s, '__SFC_PICK__')
    if b:
        pm = b[2].get('matches') if isinstance(b[2], dict) else b[2]
        for x in pm or []:
            if x.get('kt'): idx[(x.get('h'), x.get('a'))] = x['kt']
            elif x.get('date') and x.get('tm'):
                idx.setdefault((x.get('h'), x.get('a')), '%s %s' % (x['date'], x['tm']))
    n = 0
    for key in ('__LIVE__','__BJDC__','__SFC_NOW__','__SFC_PICK__','__BJ_TWO_WAY__'):
        b = _blk(s, key)
        if not b: continue
        i, j, obj = b
        ms = obj.get('matches') if isinstance(obj, dict) else obj
        for m in ms or []:
            if isinstance(m, dict):
                _fix_one(m)
                if not m.get('kt') and (m.get('h'), m.get('a')) in idx:
                    m['kt'] = idx[(m.get('h'), m.get('a'))]; n += 1
                # ★ 第二一五条：kt 回填了但 tm 仍是空串 → 卡片时间空白、matchStatus 失效。
                #   渲染读的是 date+tm，必须一并回填（开赛时间属同一事实，可跨源）。
                if m.get('kt') and not (m.get('tm') or '').strip():
                    _k = m['kt']
                    if ' ' in _k:
                        _d, _t = _k.split(' ', 1)
                        m['tm'] = _t.strip(); n += 1
                        if not (m.get('date') or '').strip(): m['date'] = _d.strip()
                    elif len(_k) == 5 and _k[2] == ':':
                        m['tm'] = _k; n += 1
        s = s[:i] + json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + s[j:]
    return s, n

try:
    inline, _nb = _norm_inline(inline)
    print('  \u2605\u7b2c\u4e8c\u30fb\u4e94\u6761\uff1a\u6570\u636e\u5c42\u5f52\u4e00\u5316\uff08\u8de8\u6e90\u56de\u586b kt %d \u573a\uff09' % _nb)
except Exception as _e:
    print('  \u26a0\ufe0f \u6570\u636e\u5c42\u5f52\u4e00\u5316\u5931\u8d25: %s' % _e)

m = re.search(r'<script>\s*\n\s*/\* =+\s*\n\s*1\. 数据层', html)
if not m:
    print('未找到注入点'); sys.exit(1)
html = html[:m.start()] + inline + html[m.start():]
html = html.replace('>内置数据</span>', '>全维度实时</span>', 1)

# ★ 第二一四条：防重复注入 —— 同一个 window.__XXX__= 只保留最后一次定义。
#   根因：模板 index.html 里带一份手工块，make_live 又注入一份，产物出现两份（后份覆盖前份）。
def _dedup_keys(_h):
    _ls = _h.split('\n')
    _seen = {}
    for _i, _s in enumerate(_ls):
        _m = re.match(r'<script>window\.(__\w+__)\s*=', _s)
        if _m and _s.rstrip().endswith('</script>'):
            _seen.setdefault(_m.group(1), []).append(_i)
    _drop = set()
    for _k, _idxs in _seen.items():
        if len(_idxs) > 1:
            _drop.update(_idxs[:-1])
            print('  \u2605 \u53bb\u91cd %s\uff1a%d \u4efd \u2192 1 \u4efd' % (_k, len(_idxs)))
    if _drop:
        _ls = [_s for _i, _s in enumerate(_ls) if _i not in _drop]
    return '\n'.join(_ls)

html = _dedup_keys(html)

out = os.path.join(BASE, 'index_live.html')
# ★ 第三〇四条：模板期号占位符统一替换（模板写死=每次build带回旧期号）
html = html.replace('__SFC_ISSUE__', SFC_ISSUE)
with open(out + '.tmp', 'w', encoding='utf-8') as _f:
    _f.write(html)
os.replace(out + '.tmp', out)

live_dim = [0]*8
for m in full['matches']:
    for i, s in enumerate(m.get('src') or []):
        if s.startswith('live'): live_dim[i] += 1
n = len(full['matches'])
print('生成 index_live.html · %.1f KB · %d 场' % (len(html.encode())/1024, n))
print('来源:', full['source'])
print('时间:', full['generated'])
print('各维实时场次:', ' '.join('%d:%d' % (i+1, c) for i, c in enumerate(live_dim)))

# ★ 第一七六条：核对条属于「乱加东西」，已整体移除（用户未要求）。
#    数量与排序靠数据本身做对，不靠新增 UI。
