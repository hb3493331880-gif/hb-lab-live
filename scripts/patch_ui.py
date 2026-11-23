# -*- coding: utf-8 -*-
"""把 template.html 里的「立即更新 / 新鲜度自检 / 徽标文案」改动同步进已生成的 index.html。
不重跑 build.py，避免动到抓到的数据。"""
import io, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(BASE, 'index.html')
TPL = os.path.join(BASE, 'engine', 'template.html')

def rd(p):
    with io.open(p, encoding='utf-8') as f:
        return f.read()

def wr(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)

tpl = rd(TPL)
html = rd(PAGE)
changed = 0

# 1) syncLive + 新鲜度自检
mark_start = '/* ★★ 第二一〇条'
mark_end = '/* ---------- 主题 / toast / 时钟 ---------- */'
i = tpl.find(mark_start)
j = tpl.find(mark_end, i)
assert i > 0 and j > i, 'template 段落没找到'
new_block = tpl[i:j]

old_a = html.find('async function syncLive(){')
old_b = html.find(mark_end, old_a) if old_a > 0 else -1
if old_a > 0 and old_b > old_a:
    html = html[:old_a] + new_block + html[old_b:]
    changed += 1
elif '第二一一条' not in html:
    print('[patch] 警告：index.html 里没找到 syncLive 段')

# 2) liveBadge 徽标文案（连不上本地服务器时不再谎报「内置数据」）
new_badge = """  }else{
    var base = window.LIVE_RT.base || '';
    var isFile = !window.LIVE_RT.fromPage;
    if(window.__LIVE__ && window.__LIVE__.matches && window.__LIVE__.matches.length){
      var g = String(window.__LIVE__.generated || '');
      const a = liveAge(window.__LIVE__);
      b.innerHTML = '<span style="color:#0a0;font-weight:700">● 已载入最新</span> · 数据 ' + (g || a.txt)
        + ' <span style="font-size:9px;color:var(--sub)">每15分钟自动更新</span>';
      b.title = '页面内嵌数据生成时间：' + g + '\\n后台本机每 15 分钟、云端每 30 分钟自动重建并发布。\\n手机端每 2 分钟自检，有新版本会自动刷新。点这里可立即拉最新。';
      return;
    }
    b.innerHTML = '<span style="color:#a60">○ 内置数据</span>'
      + (err? ' · ' + err : '');
    b.title = isFile"""
pat = re.compile(r"""  \}else\{\n    var base = window\.LIVE_RT\.base \|\| '';\n    var isFile = !window\.LIVE_RT\.fromPage;\n    b\.innerHTML = '<span style="color:#a60">○ 内置数据</span>'\n      \+ \(err\? ' · ' \+ err : ''\);\n    b\.title = isFile""")
m = pat.search(html)
if m:
    html = html[:m.start()] + new_badge + html[m.end():]
    changed += 1
else:
    print('[patch] 警告：liveBadge 段未匹配')

# 3) 底部「立即更新」按钮：走统一的 hardReload，并把「数据时间」写进按钮
html = html.replace(
    "onclick=\"(function(){var u=location.pathname+'?v='+Date.now();'\n        'location.replace(u);})()\"",
    'onclick="try{hardReload()}catch(e){location.replace(location.pathname+\'?v=\'+Date.now())}"')
html = html.replace('<span>🔄 立即更新</span>', '<span>🔄 立即更新</span>')

wr(PAGE, html)
print('[patch] 完成，改动块数 =', changed, '· 页大小', len(html))
