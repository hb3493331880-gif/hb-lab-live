#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ 第三六八条：按《HB_FOOTBALL_LAB_审计报告.md》落地的幂等修复补丁。

设计约束（都是本项目反复踩过的坑）：
  1. 幂等 —— 每处替换带修复标记，重跑不会重复插入；old 必须命中且恰好 1 次，否则记 FAIL 不静默。
  2. 模板 + 产物双改 —— 只改 index_live.html 的话，下次 make_live.py 从 index.html 重新内联就退回原样。
  3. 生成脚本同改 —— 已烘焙进产物的文案（190+ 处）由 _radar310/_calc_radar/_ana332/_ana310 产生，
     只改 HTML 不改脚本，下次 build 又会写回旧文案。
  4. 固化进 refresh.py cmd_build（在 make_live / _combo361 之后重放）。
  5. 不碰数值模型（P1-9 需重新标定，本轮不动），只做「纯收益不改架构」的修复。
"""
import os
import re
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = ['index.html', 'index_live.html']
RESULTS = []


def rec(tag, ok, detail=''):
    RESULTS.append((tag, ok, detail))
    flag = 'OK  ' if ok is True else ('SKIP' if ok is None else 'FAIL')
    print('[%s] %-42s %s' % (flag, tag, detail))


def read(f):
    p = os.path.join(BASE, f)
    if not os.path.exists(p):
        return None
    return open(p, encoding='utf-8', errors='replace').read()


def write(f, s):
    open(os.path.join(BASE, f), 'w', encoding='utf-8').write(s)


def exact(files, tag, old, new, mark=None):
    """精确替换：old 必须恰好命中 1 次；mark 存在则跳过（幂等）。"""
    for f in files:
        s = read(f)
        if s is None:
            rec(tag + '@' + f, False, '文件不存在')
            continue
        if mark and mark in s:
            rec(tag + '@' + f, None, '已修复')
            continue
        n = s.count(old)
        if n != 1:
            rec(tag + '@' + f, False, 'old 命中 %d 次（要求 1 次）' % n)
            continue
        write(f, s.replace(old, new, 1))
        rec(tag + '@' + f, True, '已替换')


def sub_files(files, tag, pattern, repl, mark=None, minhit=1):
    """正则替换（用于已烘焙进产物的文案），repl 可为函数。"""
    for f in files:
        s = read(f)
        if s is None:
            rec(tag + '@' + f, False, '文件不存在')
            continue
        if mark and mark in s:
            rec(tag + '@' + f, None, '已修复')
            continue
        s2, n = re.subn(pattern, repl, s)
        if n < minhit:
            rec(tag + '@' + f, False, '命中 %d 处（要求 >=%d）' % (n, minhit))
            continue
        write(f, s2)
        rec(tag + '@' + f, True, '替换 %d 处' % n)


# ============================================================
# P0-0 手动选中被静默清空（最高优先）
# ============================================================
R0_OLD = """function __pickR9(no,i){
  try{
    if(sfc[no]===i) delete sfc[no]; else sfc[no]=i;
    if(typeof renderR9==='function') renderR9();
  }catch(e){ console.warn('pickR9',e); }
}
function __syncR9(){
  try{
    sfc = {};
    for(var k in __R9_SEL){ var v=__R9_SEL[k]; if(v && v.length) sfc[k]=v[0]; }
    if(typeof renderR9==='function') renderR9();
  }catch(e){}
}"""
R0_NEW = """/* ★ 审计 P0-0：两套选择状态改为「合并」而不是覆盖。
   原 __syncR9 先 sfc={} 再只从 __R9_SEL 回填 → 手动在列表里选的场次每次重绘被静默清空
   （真机复现：选3场 → 重绘 → 0/9）。规则「第二九八条」原实现反了。 */
function __pickR9(no,i){
  try{
    if(sfc[no]===i){ delete sfc[no]; delete __R9_SEL[no]; }
    else { sfc[no]=i; __R9_SEL[no]=[i]; }
    if(typeof renderR9==='function') renderR9();
  }catch(e){ console.warn('pickR9',e); }
}
function __syncR9(){
  try{
    for(var k in sfc){ if(sfc[k]!=null && (!__R9_SEL[k] || !__R9_SEL[k].length)) __R9_SEL[k]=[sfc[k]]; }
    for(var k2 in __R9_SEL){ var v=__R9_SEL[k2]; if(v && v.length) sfc[k2]=v[0]; }
    if(typeof renderR9==='function') renderR9();
  }catch(e){ console.error('syncR9',e); }
}"""
exact(HTML, 'P0-0 选择状态合并', R0_OLD, R0_NEW, mark='★ 审计 P0-0')

# ============================================================
# P0-2 爆冷分支恒为空
# ============================================================
R2_OLD = """    var up = t.upset || t.alt_sc;
    var cd = dirOfScore(up && up[0]);
    if(cd!==null && cd!==mainIdx && (up[1]||0) >= 6)
      list.push({idx:cd, base:(up[1]||0)+BU+jv, kind:'爆冷',
                 why:'爆冷 '+up[0]+' '+up[1]+'%（冷门 +'+BU+'）'});"""
R2_NEW = """     /* ★ 审计 P0-2：原读 t.upset，但 __SFC_PICK__ 无此字段 → 爆冷分支恒空。
        __SFC_NOW__.upset 的语义是「次可能比分」，方向常等于主推，反推冷门方向在语义上就是错的。
        改为：从本场三项概率里取「非主推、非平局」中概率最高的方向（弱方胜）作冷门候选。 */
     var probs = (t.p && t.p.length===3) ? t.p.map(function(x){return Number(x)||0;})
                : ((t.fus && t.fus.length===3) ? t.fus.map(function(x){return Number(x)||0;}) : null);
     if(mainIdx<0 && probs) mainIdx = probs.indexOf(Math.max.apply(null,probs));
     var upIdx=-1, upP=0;
     if(probs){
       for(var q=0;q<3;q++){
         if(q===mainIdx || q===1) continue;
         if(probs[q]>upP){ upP=probs[q]; upIdx=q; }
       }
     }
     if(upIdx>=0)
       list.push({idx:upIdx, base:upP+BU+jv, kind:'爆冷',
                  why:'冷门 '+LB[upIdx]+'：市场隐含'+upP.toFixed(1)+'%（弱方胜）'});"""
exact(HTML, 'P0-2 爆冷候选', R2_OLD, R2_NEW, mark='★ 审计 P0-2')

R3_OLD = """      picked.push(add); inP[add.t.no]=1; have++;
    }
  }
  ensure('平局', (cfg && cfg.minD != null) ? cfg.minD : 2);"""
R3_NEW = """       picked.push(add); inP[add.t.no]=1; have++;
     }
     if(have < need){
       window.__R9_MIX_NOTE__ = (window.__R9_MIX_NOTE__||'') + '本期无'+kind+'候选，保底未执行；';
       console.warn('r9Unified ensure: 无'+kind+'候选');
     }
   }
   ensure('平局', (cfg && cfg.minD != null) ? cfg.minD : 2);"""
exact(HTML, 'P0-2 ensure无候选提示', R3_OLD, R3_NEW, mark='r9Unified ensure: 无')

# ============================================================
# P1-2 倒计时写死 20:15
# ============================================================
R4_OLD = """function tick(){
  const d=new Date();
  $('clock').textContent = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  const end=new Date(d); end.setHours(20,15,0,0);
  let s=Math.floor((end-d)/1000); if(s<0) s+=86400;
  $('cd').textContent='截止 '+String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
}"""
R4_NEW = r"""/* ★ 审计 P1-2：原写死 20:15，过点后仍倒计时到"明天 20:15"；
   改读 SFC._截止（与任九页同一口径），过期直接显示「已截止」。 */
function tick(){
  const d=new Date();
  $('clock').textContent = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  var dl = (typeof SFC!=='undefined' && SFC && SFC._截止) ? String(SFC._截止) : '';
  var mt = dl.match(/(\d{4})-(\d{2})-(\d{2})[^\d]*(\d{1,2}):(\d{2})/)
        || dl.match(/(\d{2})-(\d{2})[^\d]*(\d{1,2}):(\d{2})/);
  var end=null;
  try{
    if(mt && mt.length===6) end=new Date(+mt[1],+mt[2]-1,+mt[3],+mt[4],+mt[5],0);
    else if(mt) end=new Date(d.getFullYear(),+mt[1]-1,+mt[2],+mt[3],+mt[4],0);
  }catch(e){ end=null; }
  if(!end || isNaN(end.getTime())){ $('cd').textContent = dl ? ('截止 '+dl) : '截止见任九页'; return; }
  let s=Math.floor((end-d)/1000);
  if(s<0){ $('cd').textContent='已截止'; return; }
  $('cd').textContent='截止 '+String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');
}"""
exact(HTML, 'P1-2 倒计时读截止', R4_OLD, R4_NEW, mark='★ 审计 P1-2')

# ============================================================
# P2-0b esc() 不转义单引号（第一小步）
# ============================================================
exact(HTML, 'P2-0b esc单引号', '.replace(/[&<>"]/g, function(c){',
      '.replace(/[&<>"\']/g, function(c){', mark="/[&<>\"']/g")

# ============================================================
# 附录：默认按钮改 r9AutoTop（混合策略仅显式调用）
# ============================================================
R6_OLD = """function r9Auto(mode){
  /* ★ 第一八八条：mode=1/2 都走「统一评分池」——平局 + 爆冷 + 主推同池竞争，不再分开两组 */
  r9Unified();
  if(mode===2){ sfcPickBlock(); return; }
  sfcPickBlock(); return;"""
R6_NEW = """function r9Auto(mode){
  /* ★ 审计附录：默认一律 r9AutoTop（纯把握排序）。
     r9Unified 的「平局+6」硬凑平局实测净损失约 21.7pt 把握，仅作显式混合选项保留。 */
  if(mode===2 && typeof r9AutoMix==='function'){ r9AutoMix(); return; }
  r9AutoTop(); sfcPickBlock(); return;"""
exact(HTML, '附录 默认r9AutoTop', R6_OLD, R6_NEW, mark='★ 审计附录')

# ============================================================
# P1-3 四注完全相同（jitter 换种子 12 次仍撞车）
# ============================================================
R7_OLD = """function r9Plans(){
  var CFG = [
    {n:'① 均衡混合', d:6,  u:10},
    {n:'② 偏平局',   d:13, u:5 },
    {n:'③ 偏爆冷',   d:3,  u:17},
    {n:'④ 稳中带冷', d:2,  u:4 }
  ];
  var SIG = {};
  __R9_PLANS = CFG.map(function(c, ci){
    var p = null, sig = '', seed = ci;
    for(var k=0; k<12; k++){
      p = r9Unified({bonusD:c.d, bonusU:c.u, minD:2, minU:2,
                     jitter:9, seed:seed, apply:false});
      sig = p.map(function(x){ return x.t.no+':'+x.best.idx; }).join(',');
      if(!SIG[sig]) break;
      seed += 7;                       /* 撞车就换种子重摇，保证 4 注互不相同 */
    }
    SIG[sig] = 1;
    return {name:c.n, picks:p.map(function(x){
      return {no:x.t.no, h:x.t.h, a:x.t.a, idx:x.best.idx,
              kind:x.best.kind, why:x.best.why, two:!!x.t.two, alt:x.t.alt};
    })};
  });
  r9ApplyPlan(0);
}"""
R7_NEW = """/* ★ 审计 P1-3 / 用户实测：原 4 注靠 jitter(0~9)+换种子，各场 base 差距远大于 9，
   排序永不改变 → 四注签名完全相同（12 次换种子也撞车）。改为确定性差异化：
   ① 把握前9   ② 换掉第9   ③ 换掉第8-9   ④ 平局+冷门混合（显式标注牺牲把握换覆盖） */
function r9Plans(){
  var D = (window.__SFC_PICK__||[]).slice()
            .filter(function(t){ return t.main && t.main_p; })
            .sort(function(a,b){ return (b.main_p||0)-(a.main_p||0); });
  var LB = ['主胜','平局','客胜'];
  var CFG = [
    {n:'① 把握优先（纯排序）', k:0},
    {n:'② 换第9场',           k:1},
    {n:'③ 换第8-9场',         k:2},
    {n:'④ 平局+冷门混合（牺牲把握换覆盖）', k:3}
  ];
  __R9_PLANS = CFG.map(function(c){
    var picks;
    if(c.k===3){
      var p = r9Unified({bonusD:6, bonusU:10, minD:2, minU:2, apply:false});
      picks = p.map(function(x){
        return {no:x.t.no, h:x.t.h, a:x.t.a, idx:x.best.idx,
                kind:x.best.kind, why:x.best.why, two:!!x.t.two, alt:x.t.alt};
      });
    }else{
      var use = D.slice(0,9);
      if(c.k>=1 && D.length>9)  use[8] = D[9];
      if(c.k>=2 && D.length>10) use[7] = D[10];
      picks = use.map(function(t){
        var ii = LB.indexOf(t.main);
        return {no:t.no, h:t.h, a:t.a, idx:(ii<0?0:ii), kind:'主推',
                why:'把握排序 '+t.main+' '+t.main_p+'%', two:!!t.two, alt:t.alt};
      });
    }
    return {name:c.n, picks:picks};
  });
  r9ApplyPlan(0);
}"""
exact(HTML, 'P1-3 四注差异化', R7_OLD, R7_NEW, mark='★ 审计 P1-3')

# ============================================================
# P0-1-B 把「8 维模型」的话说明白（A 方案落地前不冒充）
# ============================================================
exact(HTML, 'P0-1B 标签改口径',
      '<span class="tag">HB竞技 · 8 维模型</span>',
      '<span class="tag">赔率模型 + 8 维因子解读</span>'
      '<span class="tag" style="font-size:9px">本页概率 = 赔率去水概率；8 维因子仅用于文字解释，未参与数值计算</span>',
      mark='本页概率 = 赔率去水概率')
exact(HTML, 'P0-1B 比分说明',
      "'比分由 <b>8 维模型 → 泊松进球分布</b> 算出，取概率最高的 3 个。'+",
      "'比分由 <b>赔率去水概率 → 泊松进球分布</b> 推算，取概率最高的 3 个；8 维因子仅用于解读、未参与数值计算。'+",
      mark='赔率去水概率 → 泊松进球分布')
exact(HTML, 'P0-1B λ说明',
      "'<b style=\"color:var(--red)\">源头是同一个 λ</b>：先用 8 个维度修正进球预期 λ，再代进泊松分布枚举比分。'+",
      "'<b style=\"color:var(--red)\">源头是同一个 λ</b>：由赔率去水概率反解进球预期 λ，再代进泊松分布枚举比分。8 维因子当前只用于文字解读，未修正 λ。'+",
      mark='未修正 λ')

# ============================================================
# P0-3 雷达页头「平局占 6 成」与正文 40.4% 打架
# ============================================================
exact(HTML, 'P0-3 雷达页头实测口径',
      '翻车样本中平局占6成，故平局率是核心因子。',
      '翻车443场中平局179场(40.4%)、客胜177场(40.0%)、主胜87场(19.6%)；'
      '全样本平局率20.3%，翻车时平局占比是常时的1.99倍。'
      '分档样本合计与复盘总数存在差额，未纳入分档的场次不参与命中率统计。',
      mark='未纳入分档的场次不参与命中率统计')

# ============================================================
# P0-4 背离阈值 >=2.0 + 补单位（生成脚本 + 产物烘焙文本）
# ============================================================
exact(['_radar310.py'], 'P0-4 雷达阈值',
      """            if div > 0:
                rk += '市场定价与排名相反，背离%.1f为突出项。' % div
            else:""",
      """            if div >= 2.0:
                 rk += '市场定价与排名相反，名次背离%.1f位为突出项（=|名次差|×0.6）。' % div
            elif div > 0:
                 rk += '市场定价与排名相反，名次背离%.1f位（未达突出项阈值2.0）。' % div
            else:""",
      mark='名次背离%.1f位')
exact(['_diverge347.py'], 'P0-4 竞彩阈值',
      """    seg.append('市场定价与排名相反，背离%.1f为突出项。' % c['div'])""",
      """     if c['div'] >= 2.0:
          seg.append('市场定价与排名相反，名次背离%.1f位为突出项（=|名次差|×0.6）。' % c['div'])
     else:
          seg.append('市场定价与排名相反，名次背离%.1f位（未达突出项阈值2.0）。' % c['div'])""",
      mark='名次背离%.1f位')


def _div_repl(m):
    v = float(m.group(1))
    if v >= 2.0:
        return '名次背离%s位为突出项' % m.group(1)
    return '名次背离%s位（轻微）' % m.group(1)


sub_files(HTML, 'P0-4 产物背离文案', r'背离(\d+\.\d)为突出项', _div_repl,
          mark='名次背离', minhit=1)

# ============================================================
# P0-5 末档「80-200%」→「80-90%」+ 小样本标注
# ============================================================
exact(['_calc_radar.py'], 'P0-5 末档名', "return '80-200'", "return '80-90'",
      mark="return '80-90'")
sub_files(HTML, 'P0-5 产物末档名', r'80-200%档', '80-90%档（n=22，样本偏小，仅供参考）',
          minhit=0)

# ============================================================
# P0-7 形态文案是恒等式，不是风险信号
# ============================================================
NEW_SHAPE = '主推方即名次弱势方（背离项），失手风险来自平局或反向穿透'
exact(['_radar310.py'], 'P0-7 雷达形态', "shape.append('排名弱势方掀翻')",
      "shape.append('%s')" % NEW_SHAPE, mark=NEW_SHAPE)
exact(['_calc_radar.py'], 'P0-7 计算形态', "if against: forms.append('排名弱势方掀翻')",
      "if against: forms.append('%s')" % NEW_SHAPE, mark=NEW_SHAPE)
sub_files(HTML, 'P0-7 产物形态文案', '排名弱势方掀翻', NEW_SHAPE, minhit=0)

# ============================================================
# P1-4 积分榜 0 被吞成 ?（生成脚本 + 产物烘焙文本）
# ============================================================
STZ_DEF = '''

def _stz(*vals):
    """★ 审计 P1-4：0 是合法战绩值，不能用 `or '?'` 吞掉（0平0负 显示成 ?平?负）。"""
    for v in vals:
        if v is not None and v != '':
            return str(v)
    return '?'
'''
s = read('_st_official.py')
if s and 'def _stz(' not in s:
    pos = s.find('\n# ---------- 伤停')
    if pos < 0:
        pos = s.find('\ndef ')
    if pos > 0:
        write('_st_official.py', s[:pos] + STZ_DEF + s[pos:])
        rec('P1-4 加_stz', True, '已插入')
    else:
        rec('P1-4 加_stz', False, '找不到插入点')
elif s:
    rec('P1-4 加_stz', None, '已存在')
for _old, _new in [
    ("d.get('ranking') or d.get('rank') or '?'", "_stz(d.get('ranking'), d.get('rank'))"),
    ("d.get('points') or '?'", "_stz(d.get('points'))"),
    ("d.get('winGoalMatchCnt') or d.get('winCnt') or '?'", "_stz(d.get('winGoalMatchCnt'), d.get('winCnt'))"),
    ("d.get('drawMatchCnt') or d.get('drawCnt') or '?'", "_stz(d.get('drawMatchCnt'), d.get('drawCnt'))"),
    ("d.get('lossGoalMatchCnt') or d.get('lossCnt') or '?'", "_stz(d.get('lossGoalMatchCnt'), d.get('lossCnt'))"),
    ("d.get('goalCnt') or d.get('goalsFor') or '?'", "_stz(d.get('goalCnt'), d.get('goalsFor'))"),
    ("d.get('lossGoalCnt') or d.get('goalsAgainst') or '?'", "_stz(d.get('lossGoalCnt'), d.get('goalsAgainst'))"),
]:
    exact(['_st_official.py'], 'P1-4 字段 ' + _old[:24], _old, _new, mark=_new)
# 产物里已烘焙的战绩 ? —— 只动「胜/平/负/进/失」前后的问号，不动 第?名 / ?分
sub_files(HTML, 'P1-4 产物战绩问号', r'\?([胜平负])', r'0\1', minhit=0)
sub_files(HTML, 'P1-4 产物进失问号', r'(?<=[进失])\?', '0', minhit=0)

# ============================================================
# P0-6 两套「同档」表：先做口径标注（合并两表需重跑全量生成，本轮不动数值）
# ============================================================
exact(['_ana332.py'], 'P0-6 校准段标注',
      "'【校准】模型给%.1f%%，%d场实测同档实际命中%.1f%%（%d场样本），'",
      "'【校准·表A｜赛前概率分档】模型给%.1f%%，%d场实测同档实际命中%.1f%%（%d场样本），'",
      mark='【校准·表A')
exact(['_ana310.py'], 'P0-6 结论段标注',
      "'模型给%.1f%%，校准后实际预期%.1f%%（同档%d场样本），赔率%.2f隐含%.1f%%，'",
      "'模型给%.1f%%，校准后实际预期%.1f%%（【结论·表B】同档%d场样本；与【校准】段表A档定义不同，仅作相对排序），赔率%.2f隐含%.1f%%，'",
      mark='【结论·表B')
sub_files(HTML, 'P0-6 产物校准段标注', '【校准】模型给', '【校准·表A】模型给', minhit=0)
sub_files(HTML, 'P0-6 产物结论段标注', r'校准后实际预期(?!（表B口径）)',
          '校准后实际预期（表B口径）', minhit=0)

# ============================================================
# P1-8 已开赛场次不再给「★ 就买这个」
# ============================================================
R14_OLD = """  ms.forEach(function(m){
    var p=m.r.p||[], o=m.o;"""
R14_NEW = """   ms.forEach(function(m){
     var p=m.r.p||[], o=m.o;
     /* ★ 审计 P1-8：开赛即停售，已开赛场次置灰、不再给投注建议 */
     var _stt = (typeof matchStatus==='function') ? matchStatus(m) : null;
     var _over = !!(_stt && (_stt.k==='live' || _stt.k==='over'));"""
exact(HTML, 'P1-8 已开赛判定', R14_OLD, R14_NEW, mark='★ 审计 P1-8')
R14B_OLD = """      '<td style="padding:3px 4px;font-size:10px"><b style="color:'+col+'">'+
        ((tw && tw.main) ? '★'+tw.main : LB[best])+'</b>'+"""
R14B_NEW = """       '<td style="padding:3px 4px;font-size:10px' + (_over?';opacity:.45':'') + '"><b style="color:'+col+'">'+
         (_over ? '已开赛 · 仅供复盘' : ((tw && tw.main) ? '★'+tw.main : LB[best]))+'</b>'+"""
exact(HTML, 'P1-8 投注建议置灰', R14B_OLD, R14B_NEW, mark='已开赛 · 仅供复盘')

# ============================================================
# P1-10 健壮性：f 里 NaN 会毁掉整场概率
# ============================================================
R18_OLD = "_fArr.forEach((v,i)=> d += (W[i]||0)*(typeof v==='number'?v:0));   // d ∈ [-1,1]"
R18_NEW = ("_fArr.forEach((v,i)=>{ var _v=Number(v);"
           " if(Number.isFinite(_v)) d += (W[i]||0)*Math.max(-1,Math.min(1,_v)); });"
           " d = Math.max(-1, Math.min(1, Number.isFinite(d)?d:0));")
exact(HTML, 'P1-10 finite校验', R18_OLD, R18_NEW, mark='Number.isFinite(_v)')

# ============================================================
# 汇总
# ============================================================
ok = sum(1 for _, s, _ in RESULTS if s is True)
skip = sum(1 for _, s, _ in RESULTS if s is None)
fail = sum(1 for _, s, _ in RESULTS if s is False)
print('\n==== 汇总: OK %d / SKIP %d / FAIL %d' % (ok, skip, fail))
if fail:
    print('FAIL 明细:')
    for t, s, d in RESULTS:
        if s is False:
            print('  -', t, d)
report = os.path.join(BASE, 'data', '_audit_fix_report.json')
try:
    os.makedirs(os.path.dirname(report), exist_ok=True)
    json.dump([{'tag': t, 'status': ('ok' if s is True else ('skip' if s is None else 'fail')), 'detail': d}
               for t, s, d in RESULTS],
              open(report, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('报告:', report)
except Exception as e:
    print('报告写入失败:', e)
sys.exit(0 if fail == 0 else 1)
