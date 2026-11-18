# -*- coding: utf-8 -*-
"""第三六一条 + 第三七七条：串关只推「一个」，且按销售日冻结、不随时间消退。

旧版每次 renderCombos() 都从实时 M（hbGroup===1）重算 → 比赛开踢 / 赔率刷新 / 跨天
都会让这一注变化或消失，第二天也无法复盘。现改为只读 window.__COMBO_HISTORY__
（由 _combo_snap.py 在 build 阶段按日落盘、同日永不覆盖），并附往期复盘列表。
"""
import re, sys, io

OLD_HEAD = '\U0001f525 推荐串关（按把握度自动组合）'
NEW_HEAD = '\U0001f525 今日推荐串关（2串/3串 · 3倍左右）'

NEW_FN = r'''function comboPool(){
  /* 仅作「快照缺失」时的兜底；正常路径不再依赖实时 M */
  try{
    return M.map(function(m){ return m; })
      .filter(function(m){ try{ return hbGroup(m)===1; }catch(e){ return false; } })
      .map(function(m){
        var best = (m.r && m.r.p) ? m.r.p.indexOf(Math.max.apply(null, m.r.p)) : 0;
        var p = (m.r && m.r.p) ? m.r.p[best] : 0;
        var o = (m.o && m.o.length===3) ? m.o[best] : 0;
        return {m:m, best:best, p:p, o:o, c:confidence(m)};
      })
      .filter(function(x){ return x.o > 1.05 && x.p > 0; })
      .sort(function(a,b){ return b.p - a.p; })
      .slice(0, 18);
  }catch(e){ return []; }
}
function _comboSearch(pool, n, lo, hi){
  var best = null, N = pool.length;
  var idx = [];
  function rec(start, depth){
    if(depth === n){
      var odd = 1, pr = 1;
      for(var i=0;i<n;i++){ odd *= pool[idx[i]].o; pr *= pool[idx[i]].p; }
      if(odd < lo || odd > hi) return;
      if(!best || pr > best.pr) best = {pr:pr, odd:odd, sel:idx.slice()};
      return;
    }
    for(var i=start;i<N;i++){ idx.push(i); rec(i+1, depth+1); idx.pop(); }
  }
  rec(0, 0);
  return best;
}
function _comboCard(pool, n, name, best, widened){
  var sel = best.sel.map(function(i){ return pool[i]; });
  var odd = best.odd, pr = best.pr;
  var minC = Math.min.apply(null, sel.map(function(x){ return x.c; }));
  var tag = (typeof confTag === 'function') ? confTag(minC)[0] : '';
  return '<div class="combo-card" style="border-left:3px solid #2e7dd1">'
    + '<div class="cc-hd"><b>' + name + ' · ' + odd.toFixed(2) + '倍</b>'
    + '<span style="color:#2e7dd1;font-size:11px">全中概率 <b>' + (pr*100).toFixed(1) + '%</b></span></div>'
    + '<div class="cc-list">'
    + sel.map(function(x){
        return '<div class="cc-item">'
          + '<span class="cc-n">' + x.m.no + '</span>'
          + '<span class="cc-v">' + x.m.h + ' vs ' + x.m.a + '</span>'
          + '<span class="cc-p">' + HL[x.best] + '</span>'
          + '<span class="cc-o">' + x.o.toFixed(2) + '</span>'
          + '<span class="cc-c">' + x.c + '%</span></div>';
      }).join('')
    + '</div>'
    + '<div class="cc-ft">投 2 元全中 <b>¥' + (odd*2).toFixed(2) + '</b>'
    + '<span style="color:var(--dim)">　最低把握 ' + minC + '%（' + tag + '）　每注期望 ' + ((odd*2*pr - 2) >= 0 ? '+' : '') + (odd*2*pr - 2).toFixed(2) + ' 元</span></div>'
    + (widened ? '<div style="font-size:9px;color:var(--gold);margin-top:4px">⚠️ 今日场次赔率结构凑不出 2.6~3.6 倍，已放宽到 2.2~4.5 倍取最优解</div>' : '')
    + '</div>';
}
function _chTag(r, isToday){
  if(r.result==='hit')   return '<span style="color:#1a9e5c">✅ 命中</span>';
  if(r.result==='miss')  return '<span style="color:#c0392b">❌ 未中</span>';
  if(r.result==='partial') return '<span style="color:var(--gold)">◐ 部分</span>';
  return '<span style="color:var(--dim)">⏳ ' + (isToday?'待开赛':'赛果待回填') + '</span>';
}
function _comboCardFrozen(r, isToday, label){
  var legs = r.legs || [];
  var h = '<div class="combo-card" style="border-left:3px solid ' + (isToday?'#2e7dd1':'#8a8a8a') + '">'
    + '<div class="cc-hd"><b>' + (label || (isToday?'今日推荐':('最近定稿 '+r.date))) + ' · ' + r.name + ' · ' + Number(r.odd).toFixed(2) + '倍</b>'
    + '<span style="color:#2e7dd1;font-size:11px">全中概率 <b>' + (Number(r.pr)*100).toFixed(1) + '%</b>　' + _chTag(r,isToday) + '</span></div>'
    + '<div class="cc-list">';
  legs.forEach(function(x){
    var mark = x.hit===true ? '<span style="color:#1a9e5c">✓</span>'
             : (x.hit===false ? '<span style="color:#c0392b">✗</span>' : '<span style="color:var(--dim)">·</span>');
    h += '<div class="cc-item">'
      + '<span class="cc-n">' + (x.no||'') + '</span>'
      + '<span class="cc-v">' + (x.h||'') + ' vs ' + (x.a||'') + '</span>'
      + '<span class="cc-p">' + (x.pick||'') + '</span>'
      + '<span class="cc-o">' + Number(x.odd||0).toFixed(2) + '</span>'
      + '<span class="cc-c">' + mark + ' ' + (x.actual ? (x.actual + '') : ('把握' + (x.conf!=null?x.conf:'?') + '%')) + '</span></div>';
  });
  h += '</div>'
    + '<div class="cc-ft">投 2 元全中 <b>¥' + (Number(r.odd)*2).toFixed(2) + '</b>'
    + '<span style="color:var(--dim)">　' + (r.generated?('定稿于 '+r.generated):'') + '　<b>已冻结，不随开赛/换日改动</b></span></div>'
    + (r.widened ? '<div style="font-size:9px;color:var(--gold);margin-top:4px">⚠️ 当日赔率结构凑不出 2.6~3.6 倍，已放宽到 2.2~4.5 倍取最优解</div>' : '')
    + '</div>';
  return h;
}
function renderCombos(){
  /* ★ 第三七七条：只读按日落盘的冻结快照；同日重跑不重算，跨日不消退 */
  const box = $('comboRec'); if(!box) return;
  var H = window.__COMBO_HISTORY__ || {};
  var days = Object.keys(H).sort().reverse();
  var today = (typeof _hbDayStr === 'function') ? _hbDayStr() : '';
  var h = '', shownDay = '';
  if(H[today] && (H[today].legs||[]).length){
    h = _comboCardFrozen(H[today], true, '今日推荐'); shownDay = today;
  }else if(days.length){
    /* ★ 跨过午夜/旧批次已开赛：不重算、不消失，原样回显最近一次定稿 */
    h = _comboCardFrozen(H[days[0]], false, '最近定稿 '+days[0]); shownDay = days[0];
    h += '<div style="font-size:10px;color:var(--gold);margin:5px 0 8px">⚠️ 今日暂无新可买场次，原样回显 '+days[0]+' 的定稿（不重算、不改写、不消失），可直接在下方复盘。</div>';
  }else{
    /* 兜底：快照文件缺失时，仍按旧逻辑算一次（不改变已冻结历史） */
    var pool = comboPool();
    if(pool.length < 2){ box.innerHTML = '<div class="dlt-empty">暂无快照且今日可买场次不足</div>'; return; }
    var cands = [];
    [[2,'2串1'],[3,'3串1']].forEach(function(pair){
      var n=pair[0]; if(pool.length<n) return;
      var b=_comboSearch(pool,n,2.6,3.6), w=false;
      if(!b){ b=_comboSearch(pool,n,2.2,4.5); w=true; }
      if(b) cands.push({n:n,name:pair[1],best:b,widened:w});
    });
    if(!cands.length){ box.innerHTML = '<div class="dlt-empty">今日场次赔率结构不足以组出目标串关</div>'; return; }
    cands.sort(function(a,b){ return b.best.pr - a.best.pr; });
    var win=cands[0];
    h = _comboCard(pool, win.n, win.name, win.best, win.widened)
       + '<div style="font-size:9px;color:var(--gold)">⚠️ 未读到落盘快照，本次为临时计算（建议跑一次 _combo_snap.py 固化）</div>';
  }
  h += '<div style="font-size:9px;color:var(--dim);line-height:1.7;margin:6px 0 10px">'
     + '挑选方式：只取<b>今日可买</b>场次，按模型去水概率降序取前 18 场做候选池，'
     + '在 <b>2.6~3.6 倍</b>区间内分别穷举 2 串 / 3 串，<b>取全中概率更高者，只推这一个</b>。'
     + '<b>每个销售日只定稿一次并落盘，之后不因赔率刷新、开赛或换日改动</b>；往期可在下方展开复盘。'
     + '已删除高倍（4~10×）与 4 串以上长串。概率为去水概率连乘，<b>未做场次间相关性调整</b>；'
     + '竞彩返奖率约 65%，每注期望为负，当玩法不当投资。</div>';
  var past = days.filter(function(d){ return d !== shownDay; }).slice(0, 14);
  if(past.length){
    h += '<details style="margin-top:4px"><summary style="cursor:pointer;font-size:11px;color:var(--dim);padding:5px 0">'
       + '📅 往期 2串1（共 '+days.length+' 天，点开复盘）</summary>'
       + '<div style="max-height:320px;overflow:auto;border-top:1px solid var(--line);margin-top:4px">';
    past.forEach(function(d){
      var r=H[d], legs=r.legs||[];
      h += '<div style="padding:5px 0;border-bottom:1px dashed var(--line)">'
         + '<div style="font-size:11px"><b>'+d+'</b>　'+r.name+'　'+Number(r.odd).toFixed(2)+'倍　'+_chTag(r,false)+'</div>';
      legs.forEach(function(x){
        h += '<div style="font-size:10px;color:var(--dim);padding-left:8px">'
           + (x.no||'')+' '+(x.h||'')+' vs '+(x.a||'')+'　'+(x.pick||'')+' @'+Number(x.odd||0).toFixed(2)
           + '　→ '+(x.actual ? (x.actual+' '+(x.hit===true?'✓':(x.hit===false?'✗':''))) : '赛果待回填')
           + '</div>';
      });
      h += '</div>';
    });
    h += '</div></details>';
  }
  box.innerHTML = h;
}
'''


def patch(path):
    s = io.open(path, encoding='utf-8').read()
    orig = s
    # 1) 删除静态高倍块
    s2 = re.sub(r'<!--MYHIGH290:BEGIN-->.*?<!--MYHIGH290:END-->', '', s, flags=re.S)
    rm = (len(s) - len(s2))
    s = s2
    # 2) 改标题
    if OLD_HEAD in s:
        s = s.replace(OLD_HEAD, NEW_HEAD)
    # 3) 换掉 renderCombos（含 comboPool / _comboSearch / _comboCard 一并重写）
    start = s.index('function comboPool(){')
    endmark = "box.innerHTML = h || '<div class=\"dlt-empty\">场次不足</div>';\n}"
    if endmark in s[start:]:
        end = s.index(endmark, start) + len(endmark)
    else:
        end = s.index("  box.innerHTML = h;\n}", start) + len("  box.innerHTML = h;\n}")
    s = s[:start] + NEW_FN + s[end:]
    io.open(path, 'w', encoding='utf-8').write(s)
    print(path, 'MYHIGH removed bytes:', rm, 'changed:', s != orig)


for p in sys.argv[1:]:
    patch(p)
