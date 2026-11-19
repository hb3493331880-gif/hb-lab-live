# -*- coding: utf-8 -*-
"""对生成后的单文件页面做「人看的这一层」修补。

为什么不在模板上改：模板 engine/template.html 是生成器的输入，
改它会让以后每次 build 都要靠人记着；改成后处理，规则集中在这一个文件里，
可复现、可回滚、每天自动跑都一致。
所有替换都是幂等的（已经改过就跳过），命中数会打印出来。
"""
import io, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'engine', 'index_live.html')
DST = os.path.join(BASE, 'index.html')

CSS_BLOCK = """
/* ===== 布局与可读性修正（build 时注入，勿手工改 prod） ===== */
.issuebar{flex-wrap:wrap}
.issuebar .cd{margin-left:0}
.brand{flex-wrap:wrap;row-gap:4px}
.brand h1{white-space:nowrap}
#p-dlt{padding-bottom:74px}
#p-dlt .dlt-tabs{overflow-x:auto;-webkit-overflow-scrolling:touch}
#p-dlt .dlt-tabs::-webkit-scrollbar{display:none}
#p-dlt .dlt-tab{flex:0 0 auto;padding:10px 12px;white-space:nowrap}
"""

SYNC_ISSUE_JS = """<script>
/* 期号自动对齐：数据换了期号，页头不再写死 */
window.addEventListener('load', function () {
  try {
    var P = window.__DLT_PICK__ || {};
    var s = document.getElementById('dlt_curIss');
    if (s && P.issue) {
      s.innerHTML = '当期 <b style="color:var(--red)">第 ' + P.issue + ' 期</b>' +
                    (P.date ? ' · ' + P.date : '') +
                    (P.last && P.last.iss ? '（上期 ' + P.last.iss + ' 已开奖）' : '');
    }
  } catch (e) {}
});
</script>
"""

FIXES = [
    ('允许双指缩放',
     '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">',
     '<meta name="viewport" content="width=device-width,initial-scale=1">'),

    ('模板占位符泄漏',
     '<button class="btn ${r9tickets===1?\'red\':\'\'}"',
     '<button class="btn"'),

    ('模板占位符泄漏(2注)',
     '<button class="btn ${r9tickets===2?\'red\':\'\'}"',
     '<button class="btn"'),

    ('模板占位符泄漏(3注)',
     '<button class="btn ${r9tickets===3?\'red\':\'\'}"',
     '<button class="btn"'),

    ('时间不再用分钟数',
     "return {k:'over', t:'已结束（约 '+Math.floor(diff)+' 分钟前开赛）'};",
     "var _h=Math.floor(diff/60); return {k:'over', t:'已结束（'+(diff<60? Math.floor(diff)+' 分钟前':(_h<24? _h+' 小时前':Math.floor(_h/24)+' 天前'))+'开赛）'};"),

    ('运维话术：未启动服务器',
     "liveBadge(false, '未启动服务器')",
     "liveBadge(false, '内置数据')"),

    ('运维话术：sync.py',
     '内置数据 · 运行 sync.py 切实时',
     '内置数据 · 点右上角 ⇅ 刷新'),

    ('运维话术：matches.json',
     '内置数据 · 导入 matches.json 切实时',
     '内置数据 · 点右上角 ⇅ 刷新'),

    ('状态徽标不重复',
     "liveBadge(false, '内置数据')",
     "liveBadge(false, '静态快照')"),

    ('DEMO_USER 过期日',
     '<h3>DEMO_USER</h3><p>体验版用户 · 到期 2026-10-01</p>',
     '<h3>DEMO_USER</h3><p>体验版用户</p>'),

    ('乐透标题行允许换行',
     '<div class="dlt-card" style="padding:9px 12px;font-size:12px;color:var(--sub);display:flex;gap:10px;align-items:center">',
     '<div class="dlt-card" style="padding:9px 12px;font-size:12px;color:var(--sub);display:flex;flex-wrap:wrap;gap:5px 10px;align-items:center">'),

    ('乐透当期信息独占一行',
     '<span id="dlt_curIss" style="margin-left:auto">',
     '<span id="dlt_curIss" style="flex:1 0 100%">'),

    ('已结束/已开赛区分',
     "(_over ? '已开赛 · 仅供复盘'",
     "(_over ? (_stt.k==='over' ? '已结束 · 仅供复盘' : '已开赛 · 仅供复盘')"),
]


def main():
    if not os.path.exists(SRC):
        print('[postfix] 找不到 %s，先跑 make_live.py' % SRC)
        return 1
    c = io.open(SRC, encoding='utf-8').read()
    miss = []
    for name, old, new in FIXES:
        n = c.count(old)
        if n:
            c = c.replace(old, new)
            print('  OK   %-18s ×%d' % (name, n))
        else:
            if new not in c:
                miss.append(name)
            print('  SKIP %-18s (已改过或模板变了)' % name)

    # CSS 注入（幂等）
    if '布局与可读性修正' not in c:
        c = c.replace('</head>', '<style>%s</style>\n</head>' % CSS_BLOCK, 1)
        print('  OK   注入 CSS 修正块')
    else:
        print('  SKIP CSS 修正块（已存在）')

    # 期号同步脚本（幂等）
    if '期号自动对齐' not in c:
        c = c.replace('</body></html>', SYNC_ISSUE_JS + '</body></html>', 1)
        if '期号自动对齐' not in c:
            c = c.replace('</body>', SYNC_ISSUE_JS + '</body>', 1)
        print('  OK   注入期号同步脚本')
    else:
        print('  SKIP 期号同步脚本（已存在）')

    io.open(DST, 'w', encoding='utf-8').write(c)
    print('[postfix] 输出 %s · %.1f KB · %d 条未命中'
          % (DST, len(c.encode('utf-8')) / 1024, len(miss)))
    if miss:
        print('           未命中：' + '、'.join(miss))
    return 0


if __name__ == '__main__':
    sys.exit(main())
