#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【第三〇一条】一键刷新脚本 —— 竞彩 / 北单 / 任九 / 大乐透 全模块

用法：
    python3 refresh.py plan    输出本次需要人工抓取的 URL 清单（给 web_fetch 用）
    python3 refresh.py jc      playwright 自动抓竞彩官方 webapi（脚本自己能抓）
    python3 refresh.py build   解析 raw/ 下已抓好的文件 → 建模 → 建库 → 建页面 → 验证
    python3 refresh.py         全部（jc + build），raw 缺失会提示

raw/ 约定（web_fetch 落盘，文件名固定）：
    raw/bjdc.txt        500 北单  trade.500.com/bjdc/?expect=<期号>
    raw/sfc_okooo.txt   澳客任九  m.okooo.com/zucai/?LotteryNo=<期号>
    raw/dlt.txt         大乐透开奖（可选，缺则跳过）

铁律（第二九二/二九七/二九九条）：
  * 抓不到 = 参数错了，先怀疑 ?expect= / ?LotteryNo=，不许说"源封了"
  * 期号以页面顶部「当前第N期」为准，"官方在售"是下一期
  * 无赔率的场次直接丢弃，不编造
  * 交付前 zip 内文件 md5 必须 == 本地文件
"""
import io, json, math, os, re, shutil, subprocess, sys, time, zipfile, hashlib
import datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

import _lib
import _vendor          # [365] 玄学依赖引导（vendor/ 优先，缺失自动补装）
from _lib import (name_eq as _lib_name_eq, strip_lg as _lib_strip_lg,
                  http_get as _lib_http_get, dir_of_ft as _lib_dir_of_ft,
                  md5_of, safe_inject, norm_team, ALIAS, PROBE_LOG)

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
DATA = os.path.join(BASE, 'data')
LIVE = os.path.join(BASE, 'index_live.html')
TPL = os.path.join(BASE, 'index.html')
LB = ['主胜', '平局', '客胜']


# ==================== 通用模型 ====================
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


def fit_lam(ph, pd, pa):
    """粗网格 + 局部细化"""
    best, bd = (1.2, 1.0), 9e9
    for lh in [x * 0.1 for x in range(3, 45)]:
        for la in [x * 0.1 for x in range(3, 45)]:
            h, d, a = poisson3(lh, la)
            e = (h - ph) ** 2 + (d - pd) ** 2 + (a - pa) ** 2
            if e < bd:
                bd, best = e, (lh, la)
    lh0, la0 = best
    bd2, best2 = bd, best
    for lh in [lh0 + x * 0.01 for x in range(-10, 11)]:
        for la in [la0 + x * 0.01 for x in range(-10, 11)]:
            if lh <= 0 or la <= 0:
                continue
            h, d, a = poisson3(lh, la)
            e = (h - ph) ** 2 + (d - pd) ** 2 + (a - pa) ** 2
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
    """欧赔 → 完整模型"""
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


# ==================== 分析文风（自然段落，第二九九条） ====================
def enrich(t):
    """补齐页面渲染需要的视图字段（第二九八条：缺任一字段 → 整块静默崩）"""
    # ★ 第三三三条：无赔率场次（no_odds）绝不给默认 33.3，那是编造概率。
    if t.get('no_odds'):
        t['p'] = None
        t['sp'] = None
        t['odds'] = None
    p = t.get('p') or [33.3, 33.3, 33.3]
    order = sorted(range(3), key=lambda i: -p[i])
    t['lbl'] = LB
    # ★ 第三〇三条根治：odds/sp 必须是数字。
    #   存字符串会让渲染层 typeof v==='number' 判否 → 整块被清空，
    #   且不报错。上次只在渲染层加 Number() 容错，根因没除。
    t['odds'] = [round(float(x), 2) for x in t['o']] if t.get('o') else t.get('odds')
    t['sp'] = t['odds']
    t['num'] = t.get('no') or ''
    # ★ 时间归一：date=YYYY-MM-DD / tm=HH:MM / kt=YYYY-MM-DD HH:MM:00
    #   页面 JS 按 kt 判定开赛，格式错 → 全场误判「已结束超24小时」
    d = (t.get('date') or '').strip()
    tm = (t.get('tm') or '').strip()
    if not tm and ' ' in d:
        d, tm = d.split(' ', 1)
    if len(d) <= 5 and '-' in d:          # 澳客给 '10-24'，缺年份
        import datetime as _dt
        y = _dt.date.today().year
        mm = int(d.split('-')[0])
        if mm < _dt.date.today().month - 6:
            y += 1
        d = '%d-%s' % (y, d)
    tm = tm[:5]
    t['date'], t['tm'] = d, tm
    t['kt'] = ('%s %s:00' % (d, tm)) if (d and tm) else d
    if t.get('no_odds'):
        # ★ 第三三三条：无赔率场次不赋推荐方向，避免用默认 33.3% 编造「推荐主胜」
        t['main'], t['main_p'] = None, None
        t['alt'], t['alt_p'] = None, None
        t['gap'] = None
    else:
        t['main'] = LB[order[0]]
        t['main_p'] = p[order[0]]
        t['alt'] = LB[order[1]]
        t['alt_p'] = p[order[1]]
        t['gap'] = round(p[order[0]] - p[order[1]], 1)
    t['two'] = (t['gap'] is not None) and (t['gap'] < 8)  # 前二接近 → 建议双选
    t['tot'] = t.get('tot') or round((t.get('lh') or 1.2) + (t.get('la') or 1.0), 1)
    tt = t['tot']
    t['feat'] = ('小球格局' if tt < 2.3 else
                 ('中等进球量' if tt < 2.9 else '对攻格局'))
    t['draw_p'] = p[1]
    t['top3'] = t.get('top3') or [x['s'] for x in (t.get('top') or [])[:3]]
    t['ana'] = gen_ana(t)
    return t



# ===== 身价表（transfermarkt 德转，2026-10-24 快照，单位：百万欧元）=====
# 来源：transfermarkt 各联赛页 total market value 列，web_fetch 抓取
TMV = {
 # 英超 GB1
 'Manchester City':1500.0,'Arsenal FC':1380.0,'Chelsea FC':1150.0,'Liverpool FC':1090.0,
 'ManUtd':928.8,'Tottenham':836.0,'Newcastle':712.1,'Brighton':700.0,'Brentford':633.8,
 'AstonVilla':633.7,'Bournemouth':624.2,'CrystalPalace':603.2,'Nottingham':554.0,
 'Sunderland':458.28,'Leeds':453.55,'Everton':436.8,'Fulham':418.6,'Ipswich':380.75,
 'Coventry':322.7,'Hull':295.3,
 # 意甲 IT1
 'Inter':738.3,'Juventus':613.6,'Como':568.15,'ACMilan':503.2,'Roma':498.4,
 'Atalanta':449.05,'Napoli':424.5,'Fiorentina':353.25,'Lazio':262.05,'Bologna':229.15,
 'Sassuolo':219.1,'Torino':171.1,'Genoa':165.8,'Udinese':161.8,'Parma':156.13,
 'Cagliari':141.85,'Venezia':120.33,'Frosinone':113.6,'Monza':112.5,'Lecce':82.55,
 # 德甲 L1
 'Bayern':1040.0,'Dortmund':587.9,'Leverkusen':520.45,'Leipzig':514.95,'Stuttgart':399.45,
 'Frankfurt':288.15,'Hoffenheim':287.55,'Freiburg':244.2,'Augsburg':192.0,'Mainz':159.7,
 'Koln':157.7,'Hamburg':144.7,'Gladbach':134.95,'Bremen':124.25,'UnionBerlin':111.48,
 'Schalke':74.53,'Elversberg':74.25,'Paderborn':53.88,
 # 西甲 ES1
 'RealMadrid':1500.0,'Barcelona':1300.0,'Atletico':703.5,'Villarreal':368.05,
 'RealSociedad':291.8,'Betis':258.1,'AthleticBilbao':229.8,'Celta':180.3,'Sevilla':176.8,
 'Valencia':156.5,'Espanyol':141.6,'Deportivo':125.0,'Santander':114.5,'Rayo':100.8,
 'Getafe':98.9,'Levante':87.5,'Osasuna':82.0,'Elche':74.3,'Alaves':72.9,'Malaga':62.45,
}
# 中文简称 → 德转 key（★ 只映射已抓取的 4 个联赛；其余返回 None，不编造）
CN2TM = {
 '曼城':'Manchester City','阿森纳':'Arsenal FC','切尔西':'Chelsea FC','利物浦':'Liverpool FC',
 '曼联':'ManUtd','热刺':'Tottenham','纽卡斯尔':'Newcastle','布莱顿':'Brighton',
 '布伦特':'Brentford','维拉':'AstonVilla','伯恩茅斯':'Bournemouth','水晶宫':'CrystalPalace',
 '诺丁汉':'Nottingham','桑德兰':'Sunderland','利兹联':'Leeds','埃弗顿':'Everton',
 '富勒姆':'Fulham','伊普斯':'Ipswich','考文垂':'Coventry','赫尔城':'Hull',
 '国米':'Inter','尤文':'Juventus','科莫':'Como','AC米兰':'ACMilan','罗马':'Roma',
 '亚特兰大':'Atalanta','那不勒斯':'Napoli','佛罗伦萨':'Fiorentina','拉齐奥':'Lazio',
 '博洛尼亚':'Bologna','萨索洛':'Sassuolo','都灵':'Torino','热那亚':'Genoa',
 '乌迪内斯':'Udinese','帕尔马':'Parma','卡利亚里':'Cagliari','威尼斯':'Venezia',
 '蒙扎':'Monza','莱切':'Lecce',
 '拜仁':'Bayern','多特':'Dortmund','勒沃库森':'Leverkusen','莱红牛':'Leipzig',
 '斯图加特':'Stuttgart','法兰克福':'Frankfurt','霍芬海姆':'Hoffenheim','弗赖堡':'Freiburg',
 '奥格斯堡':'Augsburg','美因茨':'Mainz','科隆':'Koln','汉堡':'Hamburg','门兴':'Gladbach',
 '不来梅':'Bremen','柏林联':'UnionBerlin','沙尔克':'Schalke','埃沃斯堡':'Elversberg',
 '帕德博恩':'Paderborn',
 '皇马':'RealMadrid','巴萨':'Barcelona','马竞':'Atletico','比利亚雷亚尔':'Villarreal',
 '皇家社会':'RealSociedad','社会':'RealSociedad','贝蒂斯':'Betis','毕尔巴鄂':'AthleticBilbao',
 '塞尔塔':'Celta','塞维利亚':'Sevilla','瓦伦西亚':'Valencia','西班牙人':'Espanyol',
 '拉科':'Deportivo','桑坦德':'Santander','巴列卡诺':'Rayo','赫塔费':'Getafe',
 '莱万特':'Levante','奥萨苏纳':'Osasuna','埃尔切':'Elche','阿拉维斯':'Alaves','马拉加':'Malaga',
}


# TMV_EXT_V2 第二批：葡超/法甲/英冠/荷甲（德转 2026-10-24 快照）
# 荷甲只取到 6 队有明确数值，其余队不收录（★ 不编造）
TMV.update({
 'PSV':306.5,'Feyenoord':245.23,'Ajax':228.45,'AZ':161.45,'Twente':101.3,'Utrecht':64.9,
 'Sporting':487.5,'Benfica':362.5,'Porto':312.7,'Braga':125.1,'Guimaraes':50.23,
 'Famalicao':49.35,'RioAve':40.0,'Estoril':33.25,'SantaClara':27.7,'GilVicente':26.98,
 'Arouca':26.7,'Moreirense':24.95,'Farense':21.4,'AVS':20.15,'CasaPia':20.05,
 'Boavista':17.65,'Nacional':16.78,'Estrela':15.25,
 'PSG':1360.0,'Monaco':377.65,'Strasbourg':319.9,'Lyon':264.45,'Rennes':253.4,'Lille':253.3,
 'Lens':243.0,'ParisFC':191.6,'Marseille':188.8,'Nice':150.25,'Toulouse':123.9,
 'Lorient':99.05,'Auxerre':96.0,'Brest':87.8,'Angers':65.5,'LeHavre':62.25,
 'Troyes':43.25,'LeMans':33.5,
 'WestHam':278.7,'Wolves':248.65,'Middlesbrough':155.3,'Southampton':154.3,'Burnley':138.1,
 'Swansea':117.2,'SheffieldUtd':115.75,'Norwich':113.03,'Stoke':108.15,'Wrexham':102.7,
 'Birmingham':99.75,'Watford':97.5,'Millwall':88.05,'WestBrom':78.4,'BristolCity':75.75,
 'Derby':73.9,'QPR':72.73,'Preston':58.8,'Charlton':45.75,'Portsmouth':41.35,
 'Blackburn':41.0,'Bolton':38.43,'Cardiff':33.15,'Lincoln':28.25,
})
CN2TM.update({
 '埃因霍温':'PSV','费耶诺德':'Feyenoord','阿贾克斯':'Ajax','阿尔克马尔':'AZ',
 '特温特':'Twente','乌德勒支':'Utrecht',
 '波尔图':'Porto','本菲卡':'Benfica','里斯本竞技':'Sporting','布拉加':'Braga',
 '吉马良斯':'Guimaraes','法马利康':'Famalicao','阿马多拉':'Estrela','卡萨皮亚':'CasaPia',
 '吉维森特':'GilVicente','里奥阿维':'RioAve','埃斯托里尔':'Estoril',
 '圣克拉拉':'SantaClara','阿鲁卡':'Arouca','莫雷伦斯':'Moreirense','法伦斯':'Farense',
 '博阿维斯塔':'Boavista','马德拉国民':'Nacional',
 '巴黎圣曼':'PSG','摩纳哥':'Monaco','斯特拉斯堡':'Strasbourg','里昂':'Lyon','雷恩':'Rennes',
 '里尔':'Lille','朗斯':'Lens','巴黎FC':'ParisFC','马赛':'Marseille','尼斯':'Nice',
 '图卢兹':'Toulouse','洛里昂':'Lorient','欧塞尔':'Auxerre','布雷斯特':'Brest',
 '昂热':'Angers','勒阿弗尔':'LeHavre','特鲁瓦':'Troyes','勒芒':'LeMans',
 '西汉姆':'WestHam','狼队':'Wolves','米堡':'Middlesbrough','南安普顿':'Southampton',
 '伯恩利':'Burnley','斯旺西':'Swansea','谢菲联':'SheffieldUtd','诺维奇':'Norwich',
 '斯托克城':'Stoke','伯明翰':'Birmingham','沃特福德':'Watford','米尔沃尔':'Millwall',
 '西布罗姆':'WestBrom','布里斯托':'BristolCity','德比郡':'Derby','女王巡游':'QPR',
 '普雷斯顿':'Preston','查尔顿':'Charlton','朴次茅斯':'Portsmouth','布莱克本':'Blackburn',
 '博尔顿':'Bolton','卡迪夫城':'Cardiff','林肯城':'Lincoln',
})

def _val_of(cn):
    """中文队名 → 身价（百万欧）；未覆盖返回 None"""
    k = CN2TM.get(cn)
    return TMV.get(k) if k else None

def val_text(m):
    """生成身价对比句；数据缺失返回空串（★ 不编造）"""
    vh, va = _val_of(m.get('h') or ''), _val_of(m.get('a') or '')
    if not vh or not va:
        return ''
    r = max(vh, va) / min(vh, va)
    who = m['h'] if vh >= va else m['a']
    hi = max(vh, va) / 100.0
    lo = min(vh, va) / 100.0
    if r >= 2.0:
        j = '身价差%.1f倍，实力差距明显' % r
    elif r >= 1.3:
        j = '身价高%.0f%%，有一定优势' % ((r - 1) * 100)
    else:
        j = '身价接近，纸面实力相当'
    return '%s身价%.2f亿欧、%s%.2f亿欧，%s' % (
        who, hi, (m['a'] if who == m['h'] else m['h']), lo, j)


def gen_ana(m):
    """m: 含 h/a/hrank/arank/lg/o/p/tot/top/main"""
    # ★ 第三三三条：无赔率场次直接返回说明文案，不进概率逻辑
    if m.get('no_odds'):
        return ('【结论】本场 %s 官方赛程在列，但欧洲赔率未开盘（澳客显示 0.00），'
                '无市场定价即无法反解概率，按铁律不填估算值冒充。'
                '建议：复式全包或整体回避，不要盲猜。' % (m.get('lg') or '本场'))
    h, a = m['h'], m['a']
    hr, ar = m.get('hrank'), m.get('arank')
    p = m['p']
    idx = LB.index(m['main']) if m.get('main') in LB else p.index(max(p))
    prob = p[idx]
    draw = p[1]
    tot = m.get('tot') or 2.5
    lg = m.get('lg') or ''

    parts = []
    # 排名对比
    if hr and ar:
        if hr < ar:
            parts.append('%s%s第%d，%s仅列%s第%d，主队排名明显占优' % (h, lg, hr, a, lg, ar))
        elif hr > ar:
            parts.append('%s%s第%d，%s%s第%d，客队排名明显占优' % (h, lg, hr, a, lg, ar))
        else:
            parts.append('%s%s第%d，%s同列第%d，双方排名接近' % (h, lg, hr, a, ar))
    else:
        parts.append('%s主场迎战%s' % (h, a))
    # 身价对比（德转，缺失则不写）
    _vt = val_text(m)
    if _vt:
        parts.append(_vt)
    # 概率判断
    parts.append('%s%.2f、%.1f%%，%s' % (
        LB[idx], m['o'][idx], prob,
        '是本期确定性最高的一场' if prob >= 65 else
        ('确定性靠前' if prob >= 58 else
         ('把握尚可' if prob >= 50 else '把握一般'))))
    # 平局
    parts.append('平局%.1f%%，%s' % (
        draw, '属正常区间' if draw < 25 else ('偏高，需防冷' if draw < 28 else '是本场最大风险')))
    # 进球
    parts.append('进球预期%.1f球' % tot)
    # 背离
    # ★ 第三四七条：旧的一句式背离已由 _diverge347.block 的【定价·排名一致性】
    #   段取代（量化到背离分/领先位数/实证命中率）。这里不再输出，否则同一场
    #   出现两次背离描述（实测竞彩页 13 处重复）。
    # 比分
    if m.get('top'):
        try:
            parts.append('比分主推 %s' % '、'.join(
                (t.get('s') if isinstance(t, dict) else t) for t in m['top'][:3]))
        except Exception:
            pass
    # ★ 第三一一条：不再在这里写"建议"（可当胆材 / 双选放弃）。
    #   结论统一由 _ana310.verdict_block 生成，且必须放在分析之后。
    txt = '。'.join(parts) + '。'
    # ★ 第三一〇条：追加【基本面】【状态/气势/反弹】【伤停影响】
    #   必须在 gen_ana 内部生成 —— 事后 patch ana 字符串会被 build 重算覆盖（已踩过）。
    #   旧 _ana306 里硬编码"伤停未采集"，会盖掉真实伤停，已弃用。
    try:
        import _ana310
        txt += _ana310.build_ana(m)
    except Exception as _e:
        txt += '【基本面】未采集（%s: %s）。' % (type(_e).__name__, str(_e)[:60])
    return txt



# ==================== 伤停（官方，★ 当前被 WAF 拦截）====================
INJ_API = ('https://webapi.sporttery.cn/gateway/uniform/football/'
           'getTodayInjurySuspensionV1.qry?channel=c')

def _find_chrome():
    """★ 第三七五条：浏览器路径不再写死一个。

    多数机器没有 /usr/bin/google-chrome；优先顺序：
    系统路径 -> playwright 自带 chromium -> playwright 自报路径。
    全找不到就明确返回 None，交给调用方回落，不静默重试刷屏。
    """
    import glob
    cands = ['/usr/bin/google-chrome', '/usr/bin/chromium',
             '/opt/chromium/chrome-linux/chrome']
    cands += sorted(glob.glob(os.path.expanduser(
        '~/.cache/ms-playwright/chromium-*/chrome-linux/chrome')), reverse=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ep = p.chromium.executable_path
            if ep and os.path.exists(ep):
                return ep
    except Exception:
        pass
    return None


def fetch_injury():
    """★ 第三〇五条：官方「今日全部伤停」，一次拿全。

    实测状态（2026-10-24）：该路径被腾讯云 WAF 拦截，返回 403
    「您的请求已中断」。且高频重试会牵连同域名的 getMatchCalculatorV1
    （竞彩接口）一起 403 —— 所以：失败即返回 None，绝不重试刷屏、绝不编造。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return None, 'playwright 不可用：%s' % e
    chrome = _find_chrome()
    if not chrome:
        return None, '未找到 chrome（已查系统路径 + playwright 自带 chromium）'
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=chrome, args=['--no-sandbox'])
            pg = b.new_page()
            pg.set_extra_http_headers({'User-Agent': UA, 'Referer': 'https://www.sporttery.cn/'})
            r = pg.goto(INJ_API, timeout=30000)
            if not r or r.status != 200:
                b.close()
                return None, 'HTTP %s（WAF 拦截）' % (r.status if r else '?')
            body = pg.inner_text('body')
            b.close()
            d = json.loads(body)
            if not d.get('success'):
                return None, 'success=false'
            return d.get('value'), 'ok'
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


# ==================== 解析：澳客任九 ====================
RE_SFC = re.compile(
    r'(?P<no>\d{1,2})\s*\n+\s*(?P<lg>[^\n]+?)\s*\n+\s*'
    r'(?P<md>\d{2}-\d{2})\s*\n+\s*(?P<hm>\d{2}:\d{2})\s*\n+'
    r'(?:[^\n\[]*\n){0,6}?'
    r'\[(?P<hr>\d+)\](?P<h>[^\n\[]+?)\s*\n+\s*VS\s*\n+\s*'
    r'(?P<a>[^\n\[]+?)\[(?P<ar>\d+)\][^\n]*\s*\n+[^\[]{0,60}?'
    r'胜\s*(?P<o1>\d+\.\d+)\s*\n+\s*平\s*(?P<o2>\d+\.\d+)\s*\n+\s*负\s*(?P<o3>\d+\.\d+)',
    re.S)

# ★ 第三一六条：澳客在「跨联赛对阵」时把联赛名拼进队名（德乙波鸿 / K联大田 /
#   中超国安）。不剥离会导致队名匹配失败、伤停止不了。
# ★ 第三三三条：_LG_PREFIX 唯一定义在 _lib.py，此处不再重复维护


def _strip_lg(name):
    """剥离联赛前缀 —— 委托 _lib.strip_lg（第三二九条：单一实现）"""
    return _lib_strip_lg(name)


def parse_sfc(path):
    s = io.open(path, encoding='utf-8', errors='ignore').read()
    mi = re.search(r'第(\d{5})期', s)
    issue = mi.group(1) if mi else None
    out = []
    for m in RE_SFC.finditer(s):
        o = [float(m.group('o1')), float(m.group('o2')), float(m.group('o3'))]
        # ★ 第三三三条：澳客对未开盘场次（亚冠等）返回「胜 0.00 平 0.00 负 0.00」。
        #   旧逻辑 min(o)<=1.01 → continue，把官方赛程里的场次整条丢弃，
        #   导致任九只有 10 场、01-04 消失。这是「解析层丢数据」不是源没有。
        #   正确做法：保留场次、标 no_odds=True，不跑 model（无赔率算不出概率），
        #   不进串关候选池，渲染层显示「未开盘／无市场定价」。
        if min(o) <= 1.01:
            t = {'no': m.group('no').zfill(2), 'issue': issue,
                 'lg': m.group('lg').strip(),
                 'date': m.group('md'), 'tm': m.group('hm'),
                 'h': _strip_lg(m.group('h')), 'a': _strip_lg(m.group('a')),
                 'hrank': None, 'arank': None,
                 'o': None, 'odds': None, 'p': None, 'tot': None,
                 'draw_p': None, 'main': None, 'main_p': None,
                 'top': [], 'top3': [], 'ft': None,
                 'no_odds': True,
                 'src': '澳客%s期（官方赛程；本场欧赔未开盘，不编造概率）' % issue}
            out.append(enrich(t))
            continue
        t = {'no': m.group('no').zfill(2), 'issue': issue, 'lg': m.group('lg').strip(),
             'date': m.group('md'), 'tm': m.group('hm'),
             'h': _strip_lg(m.group('h')), 'a': _strip_lg(m.group('a')),
             'hrank': int(m.group('hr')), 'arank': int(m.group('ar')),
             'o': o, 'odds': o}
        mm = model(o)
        t.update(mm)
        t['main'] = LB[max(range(3), key=lambda i: mm['p'][i])]
        t['top3'] = [x['s'] for x in mm['top'][:3]]
        t['ft'] = None
        t['src'] = '澳客%s期' % issue
        out.append(enrich(t))
    return issue, out


# ==================== 解析：500 北单 ====================
# ★ 第三三八条：网页转 markdown 后「星期二」变成锟斤拷（乱码），
#   要求 \s*星期 必匹配 → heads 为空 → 所有场次 date 落空。
#   改成只认日期本身，后面的星期/乱码一律放行。
RE_BJ_HEAD = re.compile(r'(\d{4}-\d{2}-\d{2})\s*[^\n(]*?\s*\(\s*\d{1,2}[：:]\d{2}')
# ★ 排名方括号是可选的：捷克杯/波兰杯等低级别赛事没有排名，
#   旧正则强制要求 → 26108 期 147 场只解析出 57 场，静默丢 90 场。
RE_BJ = re.compile(
    r'(?P<no>\d{1,3})\s*\n+\s*(?P<lg>[^\n]+?)\s*\n+\s*(?P<hm>\d{2}:\d{2})\s*\n+'
    r'\s*(?:\[(?P<hr>\d+)\]\s*\n+)?'
    r'\s*(?P<h>[^\n\[]+?)\s*\n+\s*(?P<hcap>[+-]?\d*)\s*\n+\s*'
    r'(?P<a>[^\n\[]+?)\s*\n+\s*'
    r'(?:\[(?P<ar>\d+)\]\s*\n+)?'
    r'(?P<o1>\d+\.\d{2})(?P<o2>\d+\.\d{2})(?P<o3>\d+\.\d{2})',
    re.S)


def parse_bjdc(path):
    s = io.open(path, encoding='utf-8', errors='ignore').read()
    mi = re.search(r'已截止\[(\d+)', s)
    # 日期分组：找每个 "YYYY-MM-DD 星期" 的位置
    heads = [(m.start(), m.group(1)) for m in RE_BJ_HEAD.finditer(s)]
    out = []
    for m in RE_BJ.finditer(s):
        pos = m.start()
        cur = heads[0][1] if heads else ''
        for st, d in heads:
            if st <= pos:
                cur = d
            else:
                break
        o = [float(m.group('o1')), float(m.group('o2')), float(m.group('o3'))]
        if min(o) <= 1.01:
            continue
        hm = m.group('hm')
        # 分组是 10:00--次日10:00，凌晨场次归属次日
        if int(hm[:2]) < 10:
            cur = nextday(cur)
        t = {'no': m.group('no').zfill(3), 'lg': m.group('lg').strip(),
             'date': cur, 'tm': hm,
             'h': _strip_lg(m.group('h')), 'a': _strip_lg(m.group('a')),
             'hrank': int(m.group('hr')) if m.group('hr') else None,
             'arank': int(m.group('ar')) if m.group('ar') else None,
             'hcap': m.group('hcap').strip() or '0', 'o': o, 'odds': o}
        mm = model(o)
        t.update(mm)
        t['main'] = LB[max(range(3), key=lambda i: mm['p'][i])]
        t['top3'] = [x['s'] for x in mm['top'][:3]]
        t['ft'] = None
        t['src'] = '500北单'
        # ★ 借鉴第三〇四条 C：北单是奖池制动态 SP，会冒出 238 这种
        #   「几乎没人押」的值，拿它算串关 EV 会爆出 +1509 元之类的荒谬数。
        #   这里只打标记不丢数据：展示照常，串关候选池排除 sp_ok=False。
        t['sp_ok'] = bool(min(o) > 1.02 and max(o) < 25)
        out.append(enrich(t))
    # 去重：500 页面同场次可能出现在多个区块（热门/全部等）
    seen, ded = set(), []
    for t in out:
        k = (t['h'], t['a'], t['date'], t['tm'])
        if k in seen:
            continue
        seen.add(k)
        ded.append(t)
    ded.sort(key=lambda x: (x['date'], x['tm'], x['no']))
    for i, t in enumerate(ded):
        t['no'] = str(i + 1).zfill(3)
    return ded


def nextday(d):
    import datetime
    try:
        dt = datetime.datetime.strptime(d, '%Y-%m-%d') + datetime.timedelta(days=1)
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return d


# ==================== 抓竞彩（运行时探测链） ====================
JC_API = ('https://webapi.sporttery.cn/gateway/uniform/football/'
          'getMatchCalculatorV1.qry?poolCode=had&channel=c')

# ★ 第三二三条：绝不写死"哪个工具通"——本环境出口策略随时段变
#   （WAF 令牌桶 / IP 信誉浮动），单轮基准不具备跨时段稳定性。
#   每轮更新开头现探一次，结果记进当轮日志。
PROBE_LOG = []


def _http_get(url, timeout=25):
    """运行时探测链 —— 委托 _lib.http_get（第三二三条）"""
    txt, via = _lib_http_get(url, timeout=timeout)
    PROBE_LOG[:] = _lib.PROBE_LOG
    return txt, via


def fetch_jc():
    """★ 第三二三条：走运行时探测链，不预设哪个工具通。"""
    txt, via = _http_get(JC_API)
    print('  竞彩探测途径: %s' % via)
    if not txt:
        return []
    try:
        j = json.loads(txt)
    except Exception:
        return []
    out = []
    for grp in (j.get('value') or {}).get('matchInfoList', []):
        for m in grp.get('subMatchList', []):
            o = []
            for k in ('h', 'd', 'a'):
                v = (m.get('had') or {}).get(k)
                if v in (None, '', '-'):
                    v = 0
                o.append(float(v))
            if min(o) <= 1.01:
                continue   # 未开售，不编造
            hr = re.search(r'\[(\w+?)(\d+)\]', m.get('homeRank') or '')
            ar = re.search(r'\[(\w+?)(\d+)\]', m.get('awayRank') or '')
            t = {'no': str(m.get('matchNumStr') or m.get('matchNum') or ''),
                 'lg': m.get('leagueAbbName') or m.get('matchName') or '',
                 'date': m.get('matchDate') or '',
                 'tm': (m.get('matchTime') or '')[:5],
                 'h': m.get('homeTeamAbbName') or m.get('homeTeamAllName') or '',
                 'a': m.get('awayTeamAbbName') or m.get('awayTeamAllName') or '',
                 'hrank': int(hr.group(2)) if hr else None,
                 'arank': int(ar.group(2)) if ar else None,
                 # ★ 第三七一条：homeRank 形如 "[欧罗巴10]"，方括号里的标签本身就是
                 #   官方给的赛事名次口径。旧代码只取数字把标签丢了，雷达只能拿 lg 去猜。
                 #   保留后可直接写明"竞彩官方欧罗巴积分榜"，不再混用联赛排名。
                 'hrank_lg': hr.group(1) if hr else None,
                 'arank_lg': ar.group(1) if ar else None,
                 'o': o, 'odds': o, 'src': '官方webapi'}
            mm = model(o)
            t.update(mm)
            t['main'] = LB[max(range(3), key=lambda i: mm['p'][i])]
            t['top3'] = [x['s'] for x in mm['top'][:3]]
            t['ft'] = None
            out.append(enrich(t))
    return out


# ==================== 期号 / plan ====================
def latest_bj_file():
    """★ 第三三八条：北单文件名硬编码 bj_26097.json，期号一变就永远读旧数据。
       改成扫描 data/bj_*.json 取期号最大者（mtime 不可靠：旧文件可能被 touch）。"""
    import glob
    # ★ 第三四六条 B：期号最大 ≠ 有数据。实测 bj_26108.json 是 0 场空壳，
    #   只按期号选会选中它 → G4 守卫恒 FAIL、页面也拿不到场次。
    #   改为「期号最大且场次数 > 0」。
    cands = []
    for p in glob.glob(os.path.join(DATA, 'bj_*.json')):
        m = re.search(r'bj_(\d+)\.json$', p)
        if not m:
            continue
        try:
            d = json.load(io.open(p, encoding='utf-8'))
            ms = d.get('matches') if isinstance(d, dict) else d
            n = len(ms or [])
        except Exception:
            n = 0
        cands.append((int(m.group(1)), n, os.path.basename(p)))
    live = [c for c in cands if c[1] > 0]
    if live:
        return max(live, key=lambda x: (x[0], x[1]))[2]
    if cands:
        return max(cands, key=lambda x: x[0])[2]
    return '_bj_latest_full.json'


def cur_issue(kind):
    if kind == 'sfc':
        try:
            a = json.load(io.open(os.path.join(DATA, 'sfc_pick.json'), encoding='utf-8'))
            return a[0].get('issue')
        except Exception:
            return None
    if kind == 'bj':
        for f in [latest_bj_file(), '_bj_latest_full.json']:
            try:
                a = json.load(io.open(os.path.join(DATA, f), encoding='utf-8'))
                if a:
                    return a[0].get('issue')
            except Exception:
                pass
    return None



def cmd_doctor():
    """★ 借鉴第三〇四条 D：不靠 ls 猜目录，让 playwright 自己报路径。

    踩过的坑：HOME=/workspace/.home 时缓存在
    /workspace/.home/.cache/ms-playwright/，而 /root/.cache 里躺着
    镜像遗留的僵尸目录（旧结构、缺 headless shell）。我反复查僵尸目录，
    以为「装不上」，其实早就装好了。本命令一次说清。
    """
    rep = []
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return ['playwright 未安装：%s' % e]
    # ① 系统 chrome（实测可用，优先）
    for c in ['/usr/bin/google-chrome', '/usr/bin/chromium',
              '/opt/chromium/chrome-linux/chrome']:
        rep.append('%s 系统浏览器 %s：%s' % (
            '[OK]' if os.path.exists(c) else '[--]', c,
            '存在' if os.path.exists(c) else '无'))
    # ② playwright 自报路径
    try:
        with sync_playwright() as p:
            ep = p.chromium.executable_path
        rep.append('[OK] playwright 自报路径：%s' % ep)
        rep.append('     存在：%s' % os.path.exists(ep))
        cache = os.path.dirname(os.path.dirname(os.path.dirname(ep)))
        rep.append('     真实缓存目录：%s' % cache)
        if os.path.isdir(cache):
            for d in sorted(os.listdir(cache)):
                if d.startswith(('chromium', 'ffmpeg')):
                    rep.append('     包：%s' % d)
    except Exception as e:
        rep.append('[!!] playwright 路径探测失败：%s' % e)
    # ③ 实测渲染
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path='/usr/bin/google-chrome',
                                  args=['--no-sandbox'])
            pg = b.new_page()
            pg.goto('data:text/html,<h1>ok</h1>')
            r = pg.inner_text('h1')
            b.close()
        rep.append('%s 渲染实测：%s' % ('[OK]' if r == 'ok' else '[!!]', r))
    except Exception as e:
        rep.append('[!!] 渲染实测失败：%s' % str(e)[:200])
    return rep


def cmd_plan():
    i = cur_issue('sfc')
    print('== 需要抓取的 URL（web_fetch 留空 prompt，落盘到 raw/）==')
    if i:
        print('任九 当前 %s → raw/sfc_okooo.txt' % i)
        print('  https://m.okooo.com/zucai/?LotteryNo=%s' % i)
        try:
            n = int(i) + 1
            print('  （若已截止则抓下一期 %d）https://m.okooo.com/zucai/?LotteryNo=%d' % (n, n))
        except Exception:
            pass
    else:
        print('任九 期号未知 → 先抓 https://trade.500.com/sfc/ 看顶部「当前第N期」')
    print('北单 → raw/bjdc.txt')
    print('  https://trade.500.com/bjdc/?expect=<期号>   ← ?date= 无效，必须 ?expect=')
    print('大乐透开奖 → raw/dlt.txt（可选）')
    print('  https://www.lottery.gov.cn/kj/kjlb.html')


# ==================== build ====================
def cmd_build():
    os.makedirs(RAW, exist_ok=True)
    rep = []

    # --- 任九 ---
    f = os.path.join(RAW, 'sfc_okooo.txt')
    if os.path.exists(f):
        issue, sfc = parse_sfc(f)
        if sfc:
            fp = os.path.join(DATA, 'sfc_pick.json')
            try:
                cur = json.load(io.open(fp, encoding='utf-8'))
            except Exception:
                cur = []
            # 期号不同 → 旧场次先进归档再整体替换
            if cur and cur[0].get('issue') not in (None, issue):
                ap = os.path.join(BASE, ARCHIVE)
                try:
                    arc = json.load(io.open(ap, encoding='utf-8'))
                except Exception:
                    arc = []
                for t in cur:
                    t['_m'] = '任九'
                arc.extend(cur)
                json.dump(arc, io.open(ap, 'w', encoding='utf-8'),
                          ensure_ascii=False, indent=1)
                rep.append('任九：旧期 %s 归档 %d 场' % (cur[0].get('issue'), len(cur)))
            json.dump(sfc, io.open(fp, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            rep.append('任九 %s 期：%d 场' % (issue, len(sfc)))
        else:
            rep.append('任九：解析 0 场 —— 检查 raw/sfc_okooo.txt 结构')
    else:
        rep.append('任九：缺 raw/sfc_okooo.txt（跳过）')

    # --- 北单 ---
    f = os.path.join(RAW, 'bjdc.txt')
    if os.path.exists(f):
        bj = parse_bjdc(f)
        if bj:
            # ★ 第三一四条：raw/bjdc.txt 是历史快照，含大量已开赛场次。
            #   清理步骤刚把它们归档进 _archive_done.json，这里若不过滤会原样合并回来
            #   （实测：归档 177 场后又被"新增 177"，北单永远清不掉旧场次）。
            _now = datetime.datetime.now()
            _keep = []
            for _t in bj:
                _kt = str(_t.get('kt') or '')[:16]
                try:
                    _dt = datetime.datetime.strptime(_kt, '%Y-%m-%d %H:%M')
                except Exception:
                    _keep.append(_t)
                    continue
                if _dt < _now and not _t.get('ft'):
                    continue          # 已开赛且无赛果 → 丢弃，不回填
                _keep.append(_t)
            if len(_keep) != len(bj):
                rep.append('北单：过滤已开赛且无赛果 %d 场（剩 %d）'
                           % (len(bj) - len(_keep), len(_keep)))
            bj = _keep
            # ★ 第三四六条：北单源文件不能只写 [latest_bj_file(), '_bj_latest_full.json']
            #   两个固定名 —— 新期号文件（如 _bj_26111.json）永远不会进合并列表，
            #   抓到了也落不进页面（实测 147 场全丢）。改成扫描 bj_*.json/_bj_*.json。
            # ★ 第三六六条：上面的「扫描全部」反过来把非赛程中间产物
            #   （_bj_inj_official* 伤停映射、_bj_jc_overlap 元组表、bj_intel_map 等）
            #   当成赛程文件 merge_keep，给它们塞进 matches 键 —— 实测污染 6 个历史档，
            #   而 G1-G5 守卫查不到（字段在、只是多了个不该有的键）。
            #   现只认「纯期号赛程文件」+ 页面主文件，其余一律不合并。
            import glob as _gl
            _SKIP = ('inj_', 'overlap', 'intel_map', 'miss', 'result_today',
                     'review', 'two_way', 'raw', 'parsed', 'all_', 'cur_')
            _bjf = [os.path.basename(x) for x in
                    sorted(_gl.glob(os.path.join(DATA, 'bj_*.json')))
                    if not any(k in os.path.basename(x) for k in _SKIP)]
            _bjf += [os.path.basename(x) for x in
                     sorted(_gl.glob(os.path.join(DATA, '_bj_*.json')))
                     if not any(k in os.path.basename(x) for k in _SKIP)
                     and re.search(r'_bj_\d+\.json$', x)]
            # ★ 第三六九条：页面只读 _bj_latest_full.json。扫描全部 bj_*.json 并逐个
            #   merge_keep，会把同一批新场次反复灌进历史档（实测重复 build 后
            #   bj_26097.json 489 场、_bj_latest_full.json 397 场，其中大量是历史残留），
            #   且守卫查不出来。只写主文件，历史档保持不动。
            # ★ 第三七〇条：merge_keep 是「合并」，主文件里上一批次已开赛且无赛果的
            #   场次不会被 clean 清掉（clean 只动归档库），每次 build 都累加回来。
            #   实测 11-08：主文件 215 场里只有 139 场是当日新批次，另含 11-07 的 6 场。
            #   合并前先按「已开赛且无赛果」过滤主文件，与 raw 侧同一规则。
            _mf = os.path.join(DATA, '_bj_latest_full.json')
            try:
                _old = json.load(io.open(_mf, encoding='utf-8'))
                _oms = _old.get('matches', []) if isinstance(_old, dict) else _old
                _fresh = []
                for _t in _oms:
                    if not isinstance(_t, dict):
                        continue
                    if _t.get('ft'):
                        _fresh.append(_t)
                        continue
                    _kt = str(_t.get('kt') or ('%s %s' % (_t.get('date', ''), _t.get('tm', ''))))[:16]
                    try:
                        _dt = datetime.datetime.strptime(_kt, '%Y-%m-%d %H:%M')
                    except Exception:
                        _fresh.append(_t)
                        continue
                    if _dt < _now:
                        continue
                    _fresh.append(_t)
                if isinstance(_old, dict):
                    _old['matches'] = _fresh
                else:
                    _old = {'matches': _fresh}
                json.dump(_old, io.open(_mf, 'w', encoding='utf-8'), ensure_ascii=False)
                if len(_fresh) != len(_oms):
                    rep.append('北单主文件：清掉已开赛无赛果 %d 场（剩 %d）'
                               % (len(_oms) - len(_fresh), len(_fresh)))
            except Exception as _e:
                rep.append('北单主文件清理跳过：%s' % _e)
            for x in ['_bj_latest_full.json']:
                tot, add = merge_keep(os.path.join(DATA, x), bj, key_of)
                rep.append('北单 %s：合并后 %d 场（新增 %d）' % (x, tot, add))
            # ★ 第三四一条：任九亚冠等「澳客不开盘」场次，改由北单 SP 反解补齐。
            #   必须在北单落盘【之后】跑（依赖 _bj_latest_full.json），且必须在流程内 ——
            #   手工改 sfc_pick.json 会被下一轮 parse_sfc 整份覆盖（已复发 6 次）。
            try:
                # ★ 第三四五条：这里【不能】写 import subprocess。
                #   函数内有 import 会让 subprocess 变成局部变量，而 862 行 make_live
                #   也用它；一旦北单分支被跳过（raw/bjdc.txt 不存在），局部变量从未
                #   赋值 → UnboundLocalError，整个 build 崩在最后一步。
                #   顶层已 import subprocess，直接用即可。
                _r = subprocess.run(
                    [sys.executable, os.path.join(BASE, '_sfc_acl.py')],
                    capture_output=True, text=True, timeout=60)
                for _ln in (_r.stdout or '').strip().split('\n'):
                    if _ln.strip():
                        rep.append('任九补齐·' + _ln.strip())
            except Exception as _e:
                rep.append('任九补齐失败：%s' % _e)
        else:
            rep.append('北单：解析 0 场 —— 检查 raw/bjdc.txt 结构')
    else:
        rep.append('北单：缺 raw/bjdc.txt（跳过）')

    # --- 竞彩 ---
    f = os.path.join(RAW, 'jc.json')
    if os.path.exists(f):
        jc = json.load(io.open(f, encoding='utf-8'))
        rep.append('竞彩：%d 场（来自 raw/jc.json）' % len(jc))
    else:
        jc = []
    if jc:
        full_p = os.path.join(DATA, 'full.json')
        try:
            full = json.load(io.open(full_p, encoding='utf-8'))
        except Exception:
            full = {'matches': []}
        _idx = {key_of(t): i for i, t in enumerate(full.get('matches') or [])}
        for t in jc:
            k = key_of(t)
            if k in _idx:
                nonempty_update(full['matches'][_idx[k]], t,
                                 protect=('ft', 'dirHit', 'result'))
            else:
                full['matches'].append(t)
        full['generated'] = time.strftime('%Y-%m-%d %H:%M')
        full['source'] = ('官方 webapi.sporttery.cn getMatchCalculatorV1 '
                          '（playwright 抓取，%d 场，含官方排名）' % len(jc))
        json.dump(full, io.open(full_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        rep.append('竞彩：写入 data/full.json %d 场' % len(jc))

    # ★ 第三一一条：竞彩 ana 必须在这里全量重算，不能依赖 raw/jc.json 里的旧 ana。
    #   raw/jc.json 是抓取时的快照，改了 gen_ana 之后它不会自动更新
    #   （实测：build 后 73 场里只有 14 场有【结论】，其余 59 场是旧文案）。
    #   顺序铁律：先分析（伤停 → 状态），最后【结论】。
    try:
        _fp = os.path.join(DATA, 'full.json')
        _full = json.load(io.open(_fp, encoding='utf-8'))
        _arr = _full.get('matches') or []
        _n = 0
        for _t in _arr:
            if not isinstance(_t, dict) or not _t.get('h'):
                continue
            try:
                _t['ana'] = gen_ana(_t)
                _n += 1
            except Exception:
                pass
        json.dump(_full, io.open(_fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        rep.append('竞彩 ana 全量重算 %d 场（先分析→最后结论）' % _n)
    except Exception as e:
        rep.append('!! 竞彩 ana 重算失败: %s' % str(e)[:120])

    # ★ 第三一〇条：伤停/状态/基本面统一由 gen_ana 内的 _ana310 生成。
    #   旧的 _inj_apply_all 是"事后 patch ana 字符串"，会被 enrich() 的
    #   gen_ana 重算覆盖（实测 28→2），且其文案没有"影响判断"。已弃用。

    # ★ 第三一一条 B：任九/北单 ana 也要全量重算（保证"先分析→最后结论"，
    #   且每场都必须有【结论】，不能只有部分场次有）。
    try:
        _r = subprocess.run([sys.executable, '_ana311.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=300)
        rep.append('ana311: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! ana311 失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! ana311 异常: %s' % e)

    # ★ 第三七五条：先从项目内官方积分榜响应恢复小组快照，再跑排名/战意。
    #   uel_rank.json 一丢，整段会静默消失（「第一次可以第二次不行」的根因）。
    #   脚本自带保护：已有独立源（same_source=false）时不覆盖。
    try:
        _r = subprocess.run([sys.executable, '_uel_from_intel.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=120)
        rep.append('欧战榜快照: %s' % ((_r.stdout or '').strip().split('\n')[0] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 欧战榜快照异常: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 欧战榜快照异常: %s' % e)

    # ★ 第三七一条：欧战排名独立源交叉校验。必须在 _radar310 之前 ——
    #   雷达读 uel_ana.json 把【欧战排名】段拼进爆冷文案。缺快照时写 {}，
    #   不阻断 build、不编造名次（本机 FotMob 403，靠本地 uel_rank.json）。
    try:
        _r = subprocess.run([sys.executable, '_uel_ana.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=120)
        rep.append('欧战排名: %s' % ((_r.stdout or '').strip().split('\n')[0] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 欧战排名异常: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 欧战排名异常: %s' % e)

    # ★ 第三七二条：由排名+积分推导战意。必须在 _radar310 之前 ——
    #   雷达读 uel_motiv.json 拼进爆冷文案；缺快照/模板时写 {}，不编造。
    try:
        _r = subprocess.run([sys.executable, '_uel_motivation.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=120)
        rep.append('战意: %s' % ((_r.stdout or '').strip().split('\n')[0] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 战意异常: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 战意异常: %s' % e)

    # ★ 第三一〇条 B：爆冷雷达随期次重建（★ 必须改模板 index.html，
    #   只改产物会被下次 build 从模板带回旧期数据 —— 已复发两次）。
    try:
        _r = subprocess.run([sys.executable, '_radar310.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=180)
        rep.append('雷达: %s' % (_r.stdout or '').strip().split('\n')[0])
        if _r.returncode != 0:
            rep.append('!! 雷达失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 雷达异常: %s' % e)

    # ★ 第三一九条 B：教练注入必须在 ana311 之后（ana311 会全量重算 ana，
    #   先注入会被覆盖 —— 首次漏掉就是被重算冲掉的）。
    try:
        _r = subprocess.run([sys.executable, '_coach_apply.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=180)
        rep.append('教练: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 教练注入失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 教练注入异常: %s' % e)

    # ★ 第三三一条：联赛平局特性（冷门率报告结论落地）。必须在 ana311 /
    #   教练注入之后 —— 前两者会全量重算 ana，先注入会被冲掉（已复发三次）。
    try:
        _r = subprocess.run([sys.executable, '_lgdraw.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=120)
        rep.append('联赛平局: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 联赛平局失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 联赛平局异常: %s' % e)

    # ★ 第三三二条：校准 / 翻车形态 / 异常复核 三段。必须在 _ana311 /
    #   _coach_apply / _lgdraw 之后 —— 前三者会全量重算 ana，先注入会被冲掉。
    #   固化原因：这三段此前靠手工跑，忘了跑页面就整段消失，且守卫查不到
    #   （"段落没生成"不属于 undefined/期号/场数任何一类检查）。
    # ★ 第三六七条：原写法只是 subprocess 跑一遍 _ana332.py 的 __main__（打印示例），
    #   真正落地靠 _ana310.build_ana 里的 import。那段 print 是空转，且翻车形态段
    #   因 % 未转义被吞掉时它照样绿。改成直接检查三段是否都生成得出来。
    try:
        import _ana332 as _A3
        _demo = _A3.build({'p': [62.0, 22.0, 16.0], 'o': [1.55, 3.9, 5.2], 'main': '主胜'})
        _miss = [k for k in ('【校准', '【翻车形态', '【异常复核') if k not in _demo]
        rep.append('校准332: %s' % ('三段齐全' if not _miss else '!! 缺段 ' + ','.join(_miss)))
    except Exception as e:
        rep.append('!! 校准332 异常: %s' % e)

    # ★ 第三四七条：定价·排名背离。同样必须在 ana 重算之后。
    try:
        _r = subprocess.run([sys.executable, '_diverge347.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=200)
        rep.append('背离347: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 背离347 失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 背离347 异常: %s' % e)

    # ★ 第三五三条：北单伤停（竞彩赛程matchId → 逐场接口 → 按队名注入）
    #   必须放在 _ana311 / _lgdraw 之后，否则 ana 重算会把注入冲掉。
    try:
        _r = subprocess.run([sys.executable, '_bj_inj353.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=280)
        rep.append('北单伤停: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 北单伤停失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 北单伤停异常: %s' % e)

    # --- 建页面 ---
    r = subprocess.run([sys.executable, 'make_live.py'], cwd=BASE,
                       capture_output=True, text=True, timeout=300)
    tail = (r.stdout or '').strip().split('\n')[-3:]
    rep.append('make_live: %s' % ' | '.join(tail))
    if r.returncode != 0:
        rep.append('!! make_live 失败: %s' % (r.stderr or '')[-300:])

    # ★ 第三六一条：串关只推 1 个（2串或3串二选一，约 3 倍 SP）。
    #   必须在 make_live 之后 —— 它同时改产物 index_live.html 和模板 index.html
    #   （只改产物的话，下次 build 从模板重新内联就退回 2 张卡，已复发）。
    try:
        _r = subprocess.run([sys.executable, '_combo361.py',
                             'index.html', 'index_live.html'], cwd=BASE,
                            capture_output=True, text=True, timeout=180)
        rep.append('串关361: %s' % ((_r.stdout or '').strip().split('\n')[-1] or 'done'))
        if _r.returncode != 0:
            rep.append('!! 串关361 失败: %s' % (_r.stderr or '')[-200:])
    except Exception as e:
        rep.append('!! 串关361 异常: %s' % e)

    # ★ 第三六八条：审计修复补丁（幂等）。必须在 make_live 之后 ——
    #   它同时改模板 index.html 与产物 index_live.html，以及生成脚本里的文案源，
    #   只改产物的话下次 build 会从模板重新内联、把旧逻辑写回来（本项目已复发多次）。
    try:
        _r = subprocess.run([sys.executable, '_audit_fix.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=180)
        _tail = (_r.stdout or '').strip().split('\n')
        rep.append('审计补丁368: %s' % (_tail[-2] if len(_tail) >= 2 else 'done'))
        if _r.returncode != 0:
            rep.append('!! 审计补丁368 有未命中项: %s' % (_r.stdout or '')[-400:])
    except Exception as e:
        rep.append('!! 审计补丁368 异常: %s' % e)

    # ★ 第三七七条：每日 2串1 按销售日「一次定稿、落盘冻结」。
    #   必须在 make_live / _combo361 / _audit_fix 全部之后 —— 它读 index_live.html
    #   里的 __LIVE__ 算当天这一注，写 data/combo_history.json，再把历史注入两个页面。
    #   同一天重跑不会覆盖（防止开赛/赔率刷新/换日把推荐改掉或清空）。
    try:
        _r = subprocess.run([sys.executable, '_combo_snap.py'], cwd=BASE,
                            capture_output=True, text=True, timeout=180)
        _tail = (_r.stdout or '').strip().split('\n')
        rep.append('串关快照377: %s' % (_tail[-1] if _tail else 'done'))
        if _r.returncode != 0:
            rep.append('!! 串关快照377 失败: %s' % (_r.stderr or '')[-300:])
    except Exception as e:
        rep.append('!! 串关快照377 异常: %s' % e)
    return rep


def cmd_inj():
    """★ 第三五二条：官方「今日全部伤停」（三段路径，urllib 直连，无需浏览器）。

    来源：getAllTodayInjurySuspensionV1.qry（uniform/football/jcInfo/）
    旧 fetch_injury() 走两段路径 football/getInjurySuspensionV1.qry → E0001，
    且该函数从未被调用（死代码），官方源实际上一直没接进流程。
    """
    try:
        import _inj352
    except Exception as e:
        print('  伤停模块不可用：%s' % e)
        return None
    try:
        merged, stat = _inj352.build()
    except Exception as e:
        print('  官方伤停抓取异常：%s' % e)
        return None
    if merged is None:
        print('  官方伤停抓取失败：%s' % stat.get('err'))
        return None
    fp = _inj352.save(merged, stat)
    print('  官方 %d 场 / %d 人 → %s'
          % (stat['official_matches'], stat['official_players'], fp))
    print('  官方直用 %d · 回落二手 %d · 过期丢弃 %d'
          % (stat['official'], stat['fallback'], stat['stale_dropped']))
    # 官方只给当天 → 原始档按日存档，历史可回溯
    print('  原始档 %s' % stat['raw_file'])
    return stat['official_matches']


def cmd_jc():
    jc = fetch_jc()
    if not jc:
        print('竞彩抓取 0 场（接口或结构变化）')
        return 0
    os.makedirs(RAW, exist_ok=True)
    json.dump(jc, io.open(os.path.join(RAW, 'jc.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('竞彩官方 webapi：%d 场 → raw/jc.json' % len(jc))
    for t in jc[:3]:
        print('  %s %s vs %s  %.2f/%.2f/%.2f  %s' % (
            t['no'], t['h'], t['a'], t['o'][0], t['o'][1], t['o'][2], t['main']))
    return len(jc)



def cmd_st():
    """★ 第三四五条：官方情报（交锋/伤停/近况/积分榜）以 getMatchListV1 的 matchId 作主键。

    换期后 matchId 全变，而 data/_st_intel_by_team.json 按队名索引 —— 不重跑的话
    新一期队名一条都查不到，页面「官方伤停/官方近况」从 19 场静默掉到 0 场，
    所有守卫都是绿的（因为字段存在只是没值）。实测复发过 2 次。

    三步必须按顺序：_st_ml(抓赛程拿 matchId) → _st_batch(批量请求四端点)
    → _st_parse(建队名索引)。MAXN 是单批上限，太小会漏抓。
    """
    import os as _os
    env = dict(_os.environ)
    env.setdefault('MAXN', '80')
    out = []
    for sc, nm in [('_st_ml.py', '赛程主键'), ('_st_ml2.py', '展开rows'),
                   ('_st_batch.py', '批量情报'), ('_st_parse.py', '队名索引')]:
        try:
            r = subprocess.run([sys.executable, sc], cwd=BASE, env=env,
                               capture_output=True, text=True, timeout=900)
            tail = (r.stdout or '').strip().split('\n')[-2:]
            out.append('%s: rc=%d %s' % (nm, r.returncode, ' | '.join(tail)))
            if r.returncode != 0:
                out.append('  !! %s' % (r.stderr or '')[-200:])
        except Exception as e:
            out.append('!! %s 异常: %s' % (nm, str(e)[:120]))
    return out


def cmd_guards():
    """★ 借鉴第三〇四条 E：把踩过的坑固化成断言，而不是靠人肉检查。

    每条守卫都对应一次真实事故：
      G1 zip 内 md5 == 本地         ← 第二九四条「装旧文件」
      G2 产物无未转义 </            ← A
      G3 任九期号在数据源中可找到    ← 第二九七条「期次错位」
      G4 北单 sp 通过校验数 > 0      ← 第三〇三条「类型不符全被清空」
      G5 页面无 undefined/NaN 可见   ← 长期顽疾
    """
    import hashlib, zipfile
    g = []

    # G1
    zp = os.path.join(BASE, 'hb-lab.zip')
    if os.path.exists(zp):
        try:
            a = hashlib.md5(io.open(LIVE, 'rb').read()).hexdigest()
            with zipfile.ZipFile(zp) as z:
                b = hashlib.md5(z.read('index_live.html')).hexdigest()
            g.append(('G1 zip内==本地md5', a == b, ''))
        except Exception as e:
            g.append(('G1 zip内==本地md5', False, str(e)[:80]))
    else:
        g.append(('G1 zip内==本地md5', None, '无 zip'))

    # G2
    try:
        s = io.open(LIVE, encoding='utf-8', errors='ignore').read()
        bad = 0
        for m in re.finditer(r'<script>\s*window\.__[A-Z_]+__\s*=', s):
            seg = s[m.end():m.end() + 400000]
            end = seg.find('</script>')
            body = seg[:end] if end > 0 else seg
            # 只防真会闭合 script 的写法（</script）；JS 字符串里的 </div> 是合法的
            if re.search(r'</script', body, re.I):
                bad += 1
        g.append(('G2 注入区无裸</', bad == 0, '%d 处' % bad))
    except Exception as e:
        g.append(('G2 注入区无裸</', False, str(e)[:80]))

    # G3
    try:
        s = io.open(LIVE, encoding='utf-8', errors='ignore').read()
        iss = set(re.findall(r'26\d{3}', s))
        fp = os.path.join(DATA, 'sfc_pick.json')
        okI, note = None, '无 sfc_pick.json'
        if os.path.exists(fp):
            cur = json.load(io.open(fp, encoding='utf-8'))
            ci = str(cur[0].get('issue')) if cur else None
            okI = bool(ci and ci in iss)
            note = '数据 %s / 页面 %s' % (ci, sorted(iss)[:4])
        g.append(('G3 任九期号一致', okI, note))
    except Exception as e:
        g.append(('G3 任九期号一致', False, str(e)[:80]))

    # G4
    try:
        # ★ 第三四六条 C：页面实际读的是 _bj_latest_full.json（主文件），
        #   G4 必须查它，只查 latest_bj_file() 会查到空壳文件误报。
        def _cnt(fp):
            try:
                d = json.load(io.open(fp, encoding='utf-8'))
            except Exception:
                return 0
            ms = d.get('matches') if isinstance(d, dict) else d
            return sum(1 for t in (ms or [])
                       if isinstance(t.get('sp'), list)
                       and all(isinstance(x, (int, float)) for x in t['sp'][:3]))
        nnum = _cnt(os.path.join(DATA, '_bj_latest_full.json'))
        if nnum == 0:
            nnum = _cnt(os.path.join(DATA, latest_bj_file()))
        g.append(('G4 北单sp数字型>0', nnum > 0, '%d 场' % nnum))
    except Exception as e:
        g.append(('G4 北单sp数字型>0', False, str(e)[:80]))

    # G5
    try:
        s = io.open(LIVE, encoding='utf-8', errors='ignore').read()
        s = re.sub(r'<script[\s\S]*?</script>', '', s)
        s = re.sub(r'<[^>]+>', ' ', s)
        # ★ 第三三〇条：静态 HTML 里查不到运行时拼接出的 undefined
        #   （如 '把握 '+t.main_p+'%' 在源码里是正常代码，运行时才变 undefined）。
        #   真正的运行时检查在 verify() 的逐 tab innerText 扫描里。
        #   这里只查「源码里写死的」脏值，标注清楚避免误信。
        g.append(('G5 静态文本无undefined(不覆盖运行时)', 'undefined' not in s,
                  '%d 次 · 运行时以 verify 为准' % s.count('undefined')))
        g.append(('G5 静态文本无NaN(不覆盖运行时)', 'NaN' not in s, '%d 次' % s.count('NaN')))
    except Exception as e:
        g.append(('G5 可见文本', False, str(e)[:80]))

    # G6 ★ 第三七七条：串关「一次定稿」不能静默失效。
    #   两个真实事故：① 快照没生成 → 页面走临时计算；② 注入块落在 </body>
    #   附近，立即执行的 renderCombos() 先跑 → 读到 0 天。守卫查三件事。
    try:
        hp = os.path.join(DATA, 'combo_history.json')
        hist = json.load(io.open(hp, encoding='utf-8')) if os.path.exists(hp) else {}
        s6 = io.open(LIVE, encoding='utf-8', errors='ignore').read()
        m6 = re.search(r'window\.__COMBO_HISTORY__=(\{.*?\});', s6, re.S)
        inj = json.loads(m6.group(1)) if m6 else {}
        nday, ninj = len(hist), len(inj)
        frozen_ok = all((r.get('legs') and r.get('frozen')) for r in hist.values())
        pos_ok = (s6.find('COMBOHIST:BEGIN') >= 0
                  and s6.find('COMBOHIST:BEGIN') < s6.find('renderCombos();'))
        g.append(('G6 串关快照冻结且前置注入',
                  nday > 0 and nday == ninj and frozen_ok and pos_ok,
                  '%d天/注入%d天·冻结%s·位置%s' % (nday, ninj, frozen_ok, pos_ok)))
    except Exception as e:
        g.append(('G6 串关快照冻结且前置注入', False, str(e)[:80]))

    print('=== 回归守卫 ===')
    bad = 0
    for name, ok, note in g:
        tag = 'PASS' if ok else ('SKIP' if ok is None else 'FAIL')
        if ok is False:
            bad += 1
        print('  [%s] %-24s %s' % (tag, name, note))
    print('  → %d 项失败' % bad)
    return bad


def cmd_pack():
    zp = os.path.join(BASE, 'hb-lab.zip')
    files = ['index_live.html', 'index.html', 'refresh.py', 'make_live.py',
             'README_kouling.md',
             # ★ 第三六八条：审计修复的幂等补丁、真机验证脚本与落地清单必须随包交付
             '_audit_fix.py', '_audit_verify.py', '审计修复落地清单.md',
             # ★ 第三七一条：打包是白名单制，不加这三个，拿到包跑 refresh.py build
             #   会在「欧战排名」步直接报缺 _uel_ana.py（链路自洽要求随包交付）。
             '_uel_table.py', '_uel_ana.py', '_radar310.py',
             # ★ 第三七二条：战意模块（快照模板在 data/ 遍历时自动带上）
             '_uel_motivation.py', '_uel_from_intel.py',
             # ★ 第三七五条：官方接口直连层（随包交付，否则换机跑不了）
             '_st_direct.py',
             # ★ 第三七七条：每日串关冻结快照（缺了 build 会跳过定稿，推荐又会漂移）
             '_combo_snap.py', '_combo361.py']
    for d in ['data', 'raw']:
        p = os.path.join(BASE, d)
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                fp = os.path.join(p, fn)
                if os.path.isfile(fp) and os.path.getsize(fp) < 40 * 1024 * 1024:
                    files.append(os.path.join(d, fn))
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            fp = os.path.join(BASE, f)
            if os.path.exists(fp):
                z.write(fp, f)
    # md5 校验（第二九四条）
    def md5(p):
        return hashlib.md5(io.open(p, 'rb').read()).hexdigest()
    a = md5(LIVE)
    with zipfile.ZipFile(zp) as z:
        b = hashlib.md5(z.read('index_live.html')).hexdigest()
    ok = (a == b)
    print('打包 %s · %.1f MB · md5 %s · 一致性 %s' % (
        zp, os.path.getsize(zp) / 1024 / 1024, a[:8], 'OK' if ok else 'FAIL'))
    if not ok:
        print('!! zip 内文件与本地不一致，交付失败')
    return ok


def cmd_h2h():
    """【第三一七条】历史交锋库：刷新 openfootball 近3季 + 队名归一
    数据源：openfootball(2023-24~2025-26) + 本地 odds_hist(2002-2013)
    """
    import subprocess, sys
    out = []
    base = os.path.dirname(os.path.abspath(__file__))
    for script, desc in [('_of_map317.py', '队名归一+近期交锋')]:
        try:
            r = subprocess.run([sys.executable, os.path.join(base, script)],
                               capture_output=True, timeout=300)
            t = (r.stdout or b'').decode('utf-8', 'ignore').strip()
            out.append('%s: %s' % (desc, t.splitlines()[-1] if t else '无输出'))
        except Exception as e:
            out.append('%s 失败: %s' % (desc, str(e)[:60]))
    try:
        sys.path.insert(0, base)
        import _h2h317 as H
        n = H.load()
        out.append('交锋库载入: %d 场 / 近期组合 %d / 历史组合 %d'
                   % (n, len(H.IDXR), len(H.IDX)))
    except Exception as e:
        out.append('交锋库载入失败: %s' % str(e)[:60])
    return out


def cmd_init():
    """一次性：把页面内嵌历史复盘（__JC_REVIEW__/__BJ_REVIEW__）导入归档库。
    ★ 历史数据只存在于页面里，data/ 每次被覆盖 —— 不导入则复盘统计永远从 0 开始"""
    ap = os.path.join(BASE, ARCHIVE)
    try:
        arc = json.load(io.open(ap, encoding='utf-8'))
    except Exception:
        arc = []
    have = {key_of(t) + (t.get('_m', ''),) for t in arc}
    rep = []
    for fn, mod in [('jc_review.json', '竞彩'), ('bj_review.json', '北单')]:
        fp = os.path.join(DATA, fn)
        if not os.path.exists(fp):
            rep.append('%s 不存在（跳过）' % fn)
            continue
        try:
            o = json.load(io.open(fp, encoding='utf-8'))
        except Exception as e:
            rep.append('%s 解析失败 %s' % (fn, str(e)[:60]))
            continue
        rows = o.get('rows') or []
        add = 0
        for t in rows:
            if not isinstance(t, dict):
                continue
            t.setdefault('_m', mod)
            key = key_of(t) + (mod,)
            if key in have:
                continue
            have.add(key)
            arc.append(t)
            add += 1
        rep.append('%s → 导入 %d 场（文件共 %d）' % (fn, add, len(rows)))
    json.dump(arc, io.open(ap, 'w', encoding='utf-8'), ensure_ascii=False)
    ft = [t for t in arc if t.get('ft')]
    rep.append('归档库：%d 场（带赛果 %d）' % (len(arc), len(ft)))
    rep.append(fmt_stat('  统一口径', ft))
    return rep


# ==================== 清理：已踢完场次 ====================

def nonempty_update(dst, src, protect=()):
    """★ 借鉴第三〇四条 B：合并时空值不得覆盖真值。

    直接整体赋值会把上一轮的真实数据刷空 —— 最典型的场景是：
    上轮已回填赛果 ft，本轮新抓的同一场次 ft 为 None，
    整体替换就把赛果抹掉了，复盘库永远攒不起来。
    protect 里的键一旦有值就永不退化（如 ft 赛果）。
    """
    for k, v in src.items():
        if v is None or v == '' or v == [] or v == {}:
            continue
        if k in protect and dst.get(k) not in (None, '', [], {}):
            continue
        dst[k] = v
    return dst


def merge_keep(opath, new, keyf):
    """★ 合并而非覆盖：历史场次（尤其带赛果的）必须保留，
       否则每轮 build 都会清零复盘库 —— 这是复盘永远无数据的根因"""
    try:
        a = json.load(io.open(opath, encoding='utf-8'))
    except Exception:
        a = {'matches': []}
    if isinstance(a, dict):
        old = a.get('matches') or []
    else:
        old, a = a, {'matches': []}
    # ★ 第三五四条：中间产物文件（如 _bj_jc_overlap.json 是 [编号,mid,主,客] 元组列表）
    #   会被第三四六条的 _bj_*.json 扫描裹进来，元素不是 dict → key_of 抛
    #   'list' object has no attribute 'get'，整个 build 崩在最后一步（实测）。
    #   只保留 dict 元素，并对非赛程文件（无 h/a 键）直接跳过。
    if old and not all(isinstance(t, dict) for t in old):
        # 元素不是 dict → 不是赛程文件（中间产物），原样返回，绝不写入
        return len(old), 0
    idx = {keyf(t): i for i, t in enumerate(old)}
    add = 0
    for t in new:
        k = keyf(t)
        if k in idx:
            nonempty_update(old[idx[k]], t,
                             protect=('ft', 'dirHit', 'result'))
        else:
            old.append(t)
            add += 1
    a['matches'] = old
    json.dump(a, io.open(opath, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return len(old), add


def key_of(t):
    return (t.get('h') or '', t.get('a') or '', (t.get('date') or '')[:10])


ARCHIVE = 'data/_archive_done.json'


def cmd_clean():
    """已开赛超 12h 的场次移入归档（不直接删，保住赛果用于统计）"""
    import datetime
    now = datetime.datetime.now()
    rep = []
    ap = os.path.join(BASE, ARCHIVE)
    try:
        arc = json.load(io.open(ap, encoding='utf-8'))
    except Exception:
        arc = []
    for name, fn in [('竞彩', 'full.json'), ('北单', latest_bj_file()),
                     ('北单', '_bj_latest_full.json'), ('任九', 'sfc_pick.json')]:
        fp = os.path.join(DATA, fn)
        if not os.path.exists(fp):
            continue
        try:
            a = json.load(io.open(fp, encoding='utf-8'))
        except Exception:
            continue
        arr = a.get('matches') if isinstance(a, dict) else a
        keep, done = [], []
        for t in arr:
            kt = (t.get('kt') or ('%s %s' % (t.get('date', ''), t.get('tm', '')))).strip()
            try:
                dt = datetime.datetime.strptime(kt[:19], '%Y-%m-%d %H:%M:%S')
                over = (now - dt).total_seconds() >= 12 * 3600
            except Exception:
                over = False
            (done if over else keep).append(t)
        for t in done:
            t['_m'] = name
        arc.extend(done)
        if isinstance(a, dict):
            a['matches'] = keep
        else:
            a = keep
        json.dump(a, io.open(fp, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        if done:
            rep.append('%s %s：归档 %d 场，剩 %d' % (name, fn, len(done), len(keep)))
    seen, ded = set(), []
    for t in arc:
        k = key_of(t) + (t.get('_m', ''),)
        if k in seen:
            continue
        seen.add(k)
        ded.append(t)
    json.dump(ded, io.open(ap, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    rep.append('归档库 %s：累计 %d 场（带赛果 %d）'
               % (ARCHIVE, len(ded), len([t for t in ded if t.get('ft')])))
    return rep


# ==================== 复盘 ====================
RE_FT = re.compile(r'(?P<h>[\u4e00-\u9fa5A-Za-z0-9\.\-]{2,20})\s*(?:vs|VS|-)\s*'
                   r'(?P<a>[\u4e00-\u9fa5A-Za-z0-9\.\-]{2,20})\s*[^\d]{0,6}'
                   r'(?P<x>\d)\s*[:：\-]\s*(?P<y>\d)')


def parse_results(path):
    """从 raw/results.txt（500 完场页）抽 主 vs 客 x:y"""
    s = io.open(path, encoding='utf-8', errors='ignore').read()
    out = []
    for m in RE_FT.finditer(s):
        out.append((m.group('h').strip(), m.group('a').strip(),
                    '%s-%s' % (m.group('x'), m.group('y'))))
    return out


def name_eq(x, y):
    """队名匹配 —— 委托 _lib.name_eq（含归一化+别名表，第三二九条）"""
    return _lib_name_eq(x, y)


def dir_of_ft(ft):
    """比分->方向 —— 解析委托 _lib.dir_of_ft，返回仍用 LB 中文格式"""
    d = _lib_dir_of_ft(ft)
    return {'W': LB[0], 'D': LB[1], 'L': LB[2]}.get(d)


def is_spf_dir(v):
    """是否胜平负方向。'让胜/让平/让负' 属让球盘，禁止混入胜平负统计"""
    return v in (LB[0], LB[1], LB[2])


def pick_dir(t):
    """取赛前推荐方向，兼容新旧两套管账字段（第二九八条）"""
    return t.get('main') or t.get('pre_main')


def pick_alt(t):
    return t.get('alt') or t.get('pre_alt')


def _kicked_off(t, now=None):
    """★ 第三五八条：本场是否已开踢。

    赛果回填只按主客队名匹配会串场 —— 历史同名对阵（利物浦vs阿森纳）的比分
    被贴到还没开踢的本场上。判据：kt/date+tm 必须早于当前时间。
    时间缺失时保守返回 False（不回填），宁可漏也不可错。
    """
    import datetime as _dt
    now = now or _dt.datetime.now()
    kt = (t.get('kt') or '').strip()
    if not kt:
        d, m = (t.get('date') or '').strip(), str(t.get('tm') or '').strip()
        if not d:
            return False
        kt = '%s %s' % (d, (m or '00:00')[:5])
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return _dt.datetime.strptime(kt[:19], fmt) <= now
        except Exception:
            continue
    return False


def hit_of(t, ft):
    """方向是否命中"""
    real = dir_of_ft(ft)
    if not real:
        return None
    t['ft'] = ft
    t['real'] = real
    t['dirHit'] = (real == pick_dir(t))
    return t['dirHit']


def stat_of(rows):
    """统一命中率口径（第二九八条，三条硬规则）：
       R1 兼容新旧字段 main/pre_main（漏 pre_main 会少算 60% 样本）
       R2 剔除让球盘方向 让胜/让平/让负（混入胜平负统计属口径污染）
       R3 平局单独双口径：主推 recall（结构性=0）+ 备选 precision
    """
    tot = hit = 0
    dm = dh = 0          # 备选=平局：候选数 / 命中数
    adraw = 0            # 实际打出平局总数
    draw_main = 0        # 实际平局中主推就是平局的（结构性 0）
    for t in rows:
        real = dir_of_ft(t.get('ft'))
        if not real:
            continue
        if real == LB[1]:
            adraw += 1
        m = pick_dir(t)
        if is_spf_dir(m):                      # R2
            tot += 1
            if m == real:
                hit += 1
            if real == LB[1] and m == LB[1]:
                draw_main += 1
        if pick_alt(t) == LB[1]:               # R3 备选
            dm += 1
            if real == LB[1]:
                dh += 1
    return {
        'n': tot, 'hit': hit,
        'rate': round(100.0 * hit / tot, 1) if tot else 0,
        'alt_draw_n': dm, 'alt_draw_hit': dh,
        'alt_draw_rate': round(100.0 * dh / dm, 1) if dm else 0,
        'real_draw': adraw, 'draw_main_hit': draw_main,
        'draw_recall': round(100.0 * draw_main / adraw, 1) if adraw else 0,
    }


def fmt_stat(name, rows):
    s = stat_of(rows)
    return ('%s | 方向 %d/%d=%.1f%% | 平局备选 %d/%d=%.1f%% '
            '| 实际平局 %d 主推命中 %d(recall %.1f%%)'
            % (name, s['hit'], s['n'], s['rate'],
               s['alt_draw_hit'], s['alt_draw_n'], s['alt_draw_rate'],
               s['real_draw'], s['draw_main_hit'], s['draw_recall']))


def cmd_review():
    """赛果回填 + 双口径命中率（第二七二条：按队名双向匹配，禁用编号）"""
    fp = os.path.join(RAW, 'results.txt')
    if not os.path.exists(fp):
        return ['复盘：缺 raw/results.txt（500 完场页，需 web_fetch），跳过']
    res = parse_results(fp)
    if not res:
        return ['复盘：raw/results.txt 解析 0 场赛果']
    rep = ['复盘：原文解析到 %d 条赛果' % len(res)]
    # 主库 + 归档库一起回填（已踢完的都在归档库，只回填主库会永远 0）
    targets = [('竞彩', os.path.join(DATA, 'full.json'), True),
               ('北单', os.path.join(DATA, latest_bj_file()), True),
               ('任九', os.path.join(DATA, 'sfc_pick.json'), True),
               ('归档', os.path.join(BASE, ARCHIVE), False)]
    agg = {}
    for name, p, isdict in targets:
        if not os.path.exists(p):
            continue
        try:
            a = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        arr = a.get('matches') if (isdict and isinstance(a, dict)) else a
        if not isinstance(arr, list):
            continue
        nfill = 0
        nskip = 0
        for t in arr:
            if t.get('ft'):
                continue
            # ★ 第三五八条：队名匹配成功 ≠ 是本场。必须再校验开赛时间，
            #   未开踢的场次禁止回填赛果（实测竞彩 40 场里 33 场被贴上历史同名
            #   对阵的比分，利物浦vs阿森纳 11-02 00:30 未踢却显示 0-4）。
            if not _kicked_off(t):
                nskip += 1
                continue
            for h, x, ft in res:
                # ★ 双向：两边都必须匹配（第二七二条事故）
                if name_eq(t.get('h', ''), h) and name_eq(t.get('a', ''), x):
                    hit_of(t, ft)
                    nfill += 1
                    break
        if nskip:
            rep.append('%s：%d 场未开踢，跳过回填' % (name, nskip))
        json.dump(a, io.open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        agg.setdefault(name, []).extend([t for t in arr if t.get('ft')])
        if nfill:
            rep.append('%s：回填 %d 场' % (name, nfill))
    for name in sorted(agg):
        rows = agg[name]
        if not rows:
            continue
        rep.append(fmt_stat(name, rows))
    return rep


# ==================== 大乐透 ====================
def cmd_dlt():
    """大乐透：回填开奖 + 调玄学引擎生成下期（第二九九条文风）"""
    import datetime
    rep = []
    # [365] 依赖前置检测：sxtwl/lunar_python 丢失过 6 次，每次都"静默不出注"
    _ok, _msg = _vendor.ensure()
    if not _ok:
        rep.append('!! 大乐透玄学依赖缺失（%s）→ 二十八宿/值神/日九星将为 None' % _msg)
    else:
        rep.append('大乐透玄学依赖：%s' % _msg)
    # 1) 开奖回填
    fp = os.path.join(RAW, 'dlt.txt')
    if os.path.exists(fp):
        txt = io.open(fp, encoding='utf-8', errors='ignore').read()
        m = re.search(r'(\d{5})[^\d]{0,12}'
                      r'(\d{2})[\s,]+(\d{2})[\s,]+(\d{2})[\s,]+(\d{2})[\s,]+(\d{2})'
                      r'[^\d]{0,12}(\d{2})[\s,]+(\d{2})', txt)
        if m:
            rep.append('大乐透开奖：%s 期  %s %s %s %s %s + %s %s'
                       % (m.group(1), *m.groups()[1:]))
        else:
            rep.append('大乐透：raw/dlt.txt 未匹配开奖号（结构变了，需人工看）')
    else:
        rep.append('大乐透：缺 raw/dlt.txt（开奖回填跳过）')
    # 2) 生成下期玄学注
    nxt = next_dlt_day()
    for sc in ['_dlt_mystic282.py']:
        sp = os.path.join(BASE, sc)
        if not os.path.exists(sp):
            rep.append('大乐透：%s 不存在，玄学注需人工生成' % sc)
            continue
        try:
            r = subprocess.run([sys.executable, sc, nxt], cwd=BASE,
                               capture_output=True, text=True, timeout=180)
            out = (r.stdout or '').strip().split('\n')
            rep.append('大乐透玄学(%s)：%s' % (nxt, (out[-1] if out else '无输出')[:120]))
            if r.returncode != 0:
                rep.append('  !! %s 返回码 %d: %s' % (sc, r.returncode, (r.stderr or '')[-150:]))
        except Exception as e:
            rep.append('大乐透：%s 跑失败 %s' % (sc, str(e)[:80]))
    # 3) [344] 固化：玄学结果 → dlt_pick.json（页面读的是这个文件，
    #    不跑这步大乐透就会"静默不更新"）
    try:
        iss = next_dlt_issue(nxt)
        r = subprocess.run([sys.executable, '_dlt_gen.py', iss, nxt],
                           cwd=BASE, capture_output=True, text=True, timeout=240)
        last = (r.stdout or '').strip().split('\n')[-1] if (r.stdout or '').strip() else '无输出'
        rep.append('大乐透玄学注(%s期)：%s' % (iss, last[:120]))
        if r.returncode != 0:
            rep.append('  !! _dlt_gen.py 返回码 %d: %s' % (r.returncode, (r.stderr or '')[-150:]))
    except Exception as e:
        rep.append('大乐透：_dlt_gen.py 跑失败 %s' % str(e)[:80])
    return rep


def next_dlt_issue(target_date):
    """由本地历史最后一期推算目标开奖日的期号（大乐透周一/三/六开奖）"""
    import datetime as _dt
    try:
        h = json.load(io.open(os.path.join(BASE, 'data', 'dlt_history_full.json'),
                              encoding='utf-8', errors='ignore'))
        if isinstance(h, dict):
            h = h.get('rows') or h.get('items') or list(h.values())[0]
        last = [r for r in h if r.get('f')][-1]
        base_iss = int(last['iss'])
        y, m, d = [int(x) for x in last['date'].split('-')]
        cur = _dt.date(y, m, d)
    except Exception:
        return '00000'
    ty, tm, td = [int(x) for x in target_date.split('-')]
    end = _dt.date(ty, tm, td)
    n = 0
    cur += _dt.timedelta(days=1)
    while cur <= end:
        if cur.weekday() in (0, 2, 5):
            n += 1
        cur += _dt.timedelta(days=1)
    return str(base_iss + n)


def next_dlt_day():
    """大乐透开奖日：每周一/三/六
    ★ 第三五四条：旧版从 range(1,8) 起步 = 只从明天找，
      于是「今天就是开奖日且未到 20:30 开奖时间」时会被跳过 ——
      实测 2026-10-31（周六）12:20 跑，返回的是 11-02 → 26125 期，
      把当晚 26124 期整期漏掉（用户前一天刚要过 26124）。
      正确：先判今天（开奖日且未过 20:30），否则才往后找。"""
    import datetime
    d = datetime.date.today()
    now = datetime.datetime.now()
    if d.weekday() in (0, 2, 5) and now.hour < 20:
        return d.strftime('%Y-%m-%d')
    for i in range(1, 8):
        x = d + datetime.timedelta(days=i)
        if x.weekday() in (0, 2, 5):
            return x.strftime('%Y-%m-%d')
    return d.strftime('%Y-%m-%d')


# ==================== 浏览器验证 ====================
def cmd_r9ft():
    """任九真实赛果回填 + 背离追踪表（第三六三条，每天累积）
       1) 官方赛果接口抓区间  2) 按队名+日期回填  3) 生成 _r9_diverge.json
    """
    import subprocess as _sp, datetime as _dt, json as _js, os as _os
    out = []
    arch_p = _os.path.join(BASE, 'data', '_archive_done.json')
    # 区间：覆盖归档里任九最早日期 ~ 明天
    beg = (_dt.date.today() - _dt.timedelta(days=14)).isoformat()
    end = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
    try:
        arch = _js.load(open(arch_p, encoding='utf-8'))
        ds = [x.get('date') for x in arch
              if x.get('_m') == '任九' and x.get('date')]
        if ds:
            beg = min(min(ds), beg)
    except Exception as e:
        out.append('读归档失败 %s' % str(e)[:80])
    for script, args in (('_fetch_ft363.py', [beg, end]),
                         ('_ftmatch363.py', []),
                         ('_r9_diverge.py', [])):
        p = _os.path.join(BASE, script)
        if not _os.path.exists(p):
            out.append('缺脚本 %s' % script); continue
        try:
            r = _sp.run([sys.executable, script] + args, cwd=BASE,
                        capture_output=True, text=True, timeout=240)
            tail = [l for l in (r.stdout or '').strip().split('\n') if l.strip()]
            out.append('%s: %s' % (script, tail[-1][:150] if tail else '无输出'))
            if r.returncode != 0:
                out.append('  !! %s rc=%d %s' % (script, r.returncode,
                                                 (r.stderr or '')[-200:]))
        except Exception as e:
            out.append('!! %s 异常 %s' % (script, str(e)[:120]))
    # 统计
    try:
        d = _js.load(open(_os.path.join(BASE, 'data', '_r9_diverge.json'),
                          encoding='utf-8'))
        out.append('追踪表：%d 场，已开赛 %d，主推命中 %d'
                   % (d.get('n', 0), d.get('n_done', 0), d.get('hit', 0)))
    except Exception:
        pass
    return out


def cmd_selfcheck():
    """【第三二九条】自动自检：让问题自己暴露

    ★ 第三七五条：补两层「验证到底验证了什么」——
      (1) 落盘前对所有 .py 跑 ast.parse（行为验证抓不到语法坏，
          复盘里 82 项全绿但 update_all.py 语法坏就是这么漏的）
      (2) 反向断言：段落存在但快照缺失 = 假数据，必须报出来，
          防「第一次可以第二次不行」
    """
    import subprocess, glob, ast
    pre = []
    pys = sorted(glob.glob(os.path.join(BASE, '*.py')))
    bad = []
    for p in pys:
        try:
            ast.parse(io.open(p, encoding='utf-8', errors='replace').read(),
                      filename=p)
        except SyntaxError as e:
            bad.append('%s:%s' % (os.path.basename(p), e.lineno))
    pre.append('[OK] ast.parse %d 个 .py 全通过' % len(pys) if not bad
               else '[!!] 语法坏: ' + ', '.join(bad))
    try:
        h = io.open(LIVE, encoding='utf-8', errors='replace').read()
    except Exception:
        h = ''
    n_motiv, n_rank = h.count('【战意】'), h.count('【欧战排名】')
    has_snap = any(os.path.exists(os.path.join(BASE, 'data', f))
                   for f in ('uel_rank.json', 'uel_motiv.json', 'uel_ana.json'))
    if (n_motiv or n_rank) and not has_snap:
        pre.append('[!!] 战意/欧战排名段存在但快照全缺 —— 假数据')
    else:
        pre.append('[OK] 段落反向断言: 战意%d/欧战排名%d, 快照%s'
                   % (n_motiv, n_rank, '有' if has_snap else '无'))
    r = subprocess.run([sys.executable, '_selfcheck.py'], cwd=BASE,
                       capture_output=True, text=True, timeout=300)
    return pre + [(r.stdout or '') + (r.stderr or '')]


def cmd_verify():
    """浏览器实跑：逐 tab 点击 + pageerror 捕获（第二九六条）

    第三二一条修订 —— 原版三个准确率缺陷：
      ① 选择器 '.maintab,.tab,[data-tab]' 与真实结构不符
         真实是两套：data-p(主导航 5 个) + data-v(底栏 4 个)
      ② 无内容量下限 → 切到空容器(682字符)也报"异常 0 项"
      ③ 无断言 tab 数量 → 页面结构变了发现不了
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return ['验证：playwright 不可用，跳过']
    chrome = '/usr/bin/google-chrome'
    if not os.path.exists(chrome):
        return ['验证：系统 chrome 不存在，跳过']

    # ③ 内容量下限（分级）—— 统一阈值会误判：
    #    me 是会员/订阅页，本来就只有几百字；fupan 有历史复盘即算合格。
    #    低于下限 = 空壳；写死在此便于审计，改页面时同步改。
    MIN_LEN_DEFAULT = 1500
    MIN_LEN_BY_TAB = {
        'r9': 8000,      # 任九 14 场，含分析
        'jc': 8000,      # 竞彩数十场
        'bjdc': 20000,   # 北单数百场
        'bf': 3000,      # 比分页
        'dlt': 2000,     # 大乐透
        'saopan': 20000,  # 扫盘
        'fupan': 900,    # 复盘：历史样本 ~300 字 + 说明
        'me': 600,       # 会员/订阅页，本就简单
    }
    EXPECT_P = 5            # 主导航期望数
    EXPECT_V = 4            # 底栏期望数

    rep, errs = [], 0
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome,
                              args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = b.new_page()
        pg.on('pageerror', lambda e: rep.append('!! pageerror: %s' % str(e)[:120]))
        pg.goto('file://' + LIVE, timeout=60000, wait_until='domcontentloaded')
        pg.wait_for_timeout(1800)

        # ① 两套真实选择器；排除 data-p 里的数字键（那是场次选项 0/1/2 不是 tab）
        groups = pg.evaluate("""() => {
          const out = {p: [], v: []};
          document.querySelectorAll('[data-p]').forEach(e => {
            const k = e.getAttribute('data-p');
            if (/^\\d+$/.test(k)) return;              // 场次选项，跳过
            out.p.push([k, (e.innerText||'').trim().replace(/\\s+/g,'')]);
          });
          document.querySelectorAll('[data-v]').forEach(e => {
            out.v.push([e.getAttribute('data-v'), (e.innerText||'').trim().replace(/\\s+/g,'')]);
          });
          return out;
        }""")

        for grp, sel, expect in (('p', 'data-p', EXPECT_P), ('v', 'data-v', EXPECT_V)):
            items = groups[grp]
            if len(items) != expect:
                errs += 1
                rep.append('!! %s tab 数 %d != 期望 %d（结构变了）' % (sel, len(items), expect))
            for k, nm in items:
                try:
                    pg.evaluate("""([s,k])=>{const e=document.querySelector('['+s+'="'+k+'"]');
                                   if(e) e.click();}""", [sel, k])
                    pg.wait_for_timeout(450)
                    ln = pg.evaluate('document.body.innerText.length')
                    need = MIN_LEN_BY_TAB.get(k, MIN_LEN_DEFAULT)
                    # ★第三三五条：bf(比分)页卡片数 = 竞彩在售场数，场数少时
                    #   固定阈值 3000 会误报"空壳"（今日仅4场→1837字符，数据是全的）。
                    #   阈值改为按条目数动态算，空壳判定才不随场次数漂移。
                    # ★第三三八条：系数 350 是按「竞彩场次多」时量出来的，
                    #   27 场实测 9013 字符（约 334/场）→ 阈值 9750 误报空壳。
                    #   降到 280/场；bjdc 同理改动态（104 场 117246，约 1127/场）。
                    if k == 'bf':
                        try:
                            _n = pg.evaluate('(window.__LIVE__&&window.__LIVE__.matches||[]).length') or 0
                        except Exception:
                            _n = 0
                        need = max(900, int(_n) * 280 + 300)
                    if k == 'bjdc':
                        try:
                            _n = pg.evaluate('(window.__BJDC__&&window.__BJDC__.matches||[]).length') or 0
                        except Exception:
                            _n = 0
                        need = max(3000, int(_n) * 900 + 500)
                    flag = ''
                    if ln < need:                       # ② 空壳判定（分级）
                        errs += 1
                        flag = '  << 空壳(< %d)' % need
                    rep.append('tab[%s|%s] bodyLen=%d/需%d%s' % (sel, k, ln, need, flag))
                    # ③ ★ 第三三〇条：每个 tab 单独查运行时脏值
                    #    静态 G5 查不到（undefined 是 JS 拼接出来的），
                    #    且只在最后查一次 body 会漏掉未停留的 tab。
                    _t = pg.evaluate('document.body.innerText')
                    for _b in ['undefined', 'NaN', '[object Object]', 'null']:
                        _c = _t.count(_b)
                        if _c:
                            errs += 1
                            rep.append('!! tab[%s|%s] 含 %s × %d' % (sel, k, _b, _c))
                except Exception as e:
                    errs += 1
                    rep.append('!! tab[%s|%s] 点击失败 %s' % (sel, k, str(e)[:60]))

        txt = pg.evaluate('document.body.innerText')
        for bad in ['undefined', 'NaN', '[object Object]', 'null']:
            c = txt.count(bad)
            if c:
                errs += 1
                rep.append('!! 可见文本含 %s × %d' % (bad, c))
        b.close()
    n = len(groups.get('p', [])) + len(groups.get('v', []))
    rep.append('验证：tab %d 个（data-p %d / data-v %d），异常 %d 项'
               % (n, len(groups.get('p', [])), len(groups.get('v', [])), errs))
    return rep


TODO_TMPL = """
== 脚本做不了、需要人工（web_fetch）的 ==
  1. 北单  → raw/bjdc.txt
     https://trade.500.com/bjdc/?expect=<期号>    ← ?date= 无效！
  2. 任九  → raw/sfc_okooo.txt
     https://m.okooo.com/zucai/?LotteryNo=<期号>
  3. 赛果  → raw/results.txt（复盘用，500 完场页）
  4. 大乐透开奖 → raw/dlt.txt（可选）
抓完落盘后重跑：python3 refresh.py build
"""


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd == 'init':
        for x in cmd_init():
            print(x)
    elif cmd == 'h2h':
        for x in cmd_h2h():
            print(x)
    elif cmd == 'guards':
        sys.exit(1 if cmd_guards() else 0)
    elif cmd == 'doctor':
        for x in cmd_doctor():
            print(x)
    elif cmd == 'plan':
        cmd_plan()
        print(TODO_TMPL)
    elif cmd == 'jc':
        cmd_jc()
    elif cmd == 'inj':
        cmd_inj()
    elif cmd == 'bjinj':
        import subprocess as _sp
        r = _sp.run([sys.executable, '_bj_inj353.py'], cwd=BASE,
                    capture_output=True, text=True)
        print((r.stdout or '')[-1500:])
        if r.returncode != 0:
            print((r.stderr or '')[-600:])
    elif cmd == 'st':
        for x in cmd_st():
            print(x)
    elif cmd == 'clean':
        for x in cmd_clean():
            print(x)
    elif cmd == 'review':
        for x in cmd_review():
            print(x)
    elif cmd == 'dlt':
        for x in cmd_dlt():
            print(x)
    elif cmd == 'verify':
        for x in cmd_verify():
            print(x)
    elif cmd == 'r9ft':
        for x in cmd_r9ft():
            print('  ' + x)
    elif cmd == 'selfcheck':
        # ★ 第三七五条：这里原来直接跑 _selfcheck.py，绕过了 cmd_selfcheck，
        #   导致新加的 ast 自检 / 反向断言「单独跑时根本不执行」——
        #   又一起「验证全绿但它到底验证了什么」。统一走 cmd_selfcheck。
        import re as _re
        out = cmd_selfcheck()
        for x in out:
            print(x)
        m = _re.search(r'严重\s*0\s*/\s*警告', '\n'.join(out))
        sys.exit(0 if m else 1)
    elif cmd == 'pack':
        cmd_pack()
    elif cmd == 'build':
        for x in cmd_build():
            print(x)
        cmd_pack()
    else:
        # all：全串，每步异常不中断，最后汇总待人工清单
        # 顺序不可换：先复盘回填赛果 → 再清已踢完 → 再灌新数据建页
        steps = [('导入历史归档', cmd_init), ('抓竞彩', cmd_jc),
                 ('官方今日伤停', cmd_inj),
                 ('官方情报(需浏览器)', cmd_st),
                 ('历史交锋库', cmd_h2h),
                 ('复盘回填', cmd_review),
                 ('清理已踢完', cmd_clean),
                 ('任九赛果+背离追踪', cmd_r9ft),
                 # ★ 第三六七条：大乐透必须在 build 之前。all 原顺序是 build→dlt，
                 #   dlt 生成的 dlt_pick.json（26127）进不了已打包的页面，页面永远
                 #   停在上一期（26126）且不报错。产物与模板同改不够，流程顺序也要改。
                 ('大乐透', cmd_dlt),
                 ('解析建模建页', cmd_build),
                 ('浏览器验证', cmd_verify),
                 ('自动自检', cmd_selfcheck)]
        for nm, fn in steps:
            print('---- %s ----' % nm)
            try:
                r = fn()
                if isinstance(r, list):
                    for x in r:
                        print('  ' + x)
                elif r is not None:
                    print('  %s' % r)
            except Exception as e:
                print('  !! %s 抛错：%s' % (nm, str(e)[:200]))
        cmd_pack()
        print(TODO_TMPL)
