# -*- coding: utf-8 -*-
"""一条命令跑完整个流水线：抓数据 → 生成单页 → 后处理 → 产出 index.html

用法：
    python scripts/build.py

退出码：0 = 页面已产出（抓取失败也会用上一版数据建页，绝不产出空白页）
"""
import os, subprocess, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def step(title, args, cwd=BASE, required=True):
    print('\n=== %s ===' % title)
    t0 = time.time()
    r = subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='ignore')
    out = (r.stdout or '').strip()
    err = (r.stderr or '').strip()
    for ln in (out.splitlines()[-12:] if out else []):
        print('  ' + ln)
    if r.returncode != 0:
        print('  [失败 rc=%d]' % r.returncode)
        if err:
            print('  ' + '\n  '.join(err.splitlines()[-8:]))
        if required:
            raise SystemExit(1)
    print('  (%.1fs)' % (time.time() - t0))
    return r.returncode


def main():
    # 四个板块各抓各的，任何一个源挂了都不阻断出页：脚本自己保留旧数据并返回 0
    step('1/6 抓取官方竞彩', [os.path.join('scripts', 'fetch.py')], required=False)
    step('2/6 抓取任九 14 场', [os.path.join('scripts', 'fetch_sfc.py')], required=False)
    # 2b：官方 500 开售前没有 data-sp，用澳客 m 站（手机 UA）补 14 场终盘欧赔
    step('2b/6 任九补赔率（澳客 m 站）', [os.path.join('scripts', 'fetch_sfc_okooo.py')], required=False)
    step('3/6 抓取北单在售', [os.path.join('scripts', 'fetch_bjdc.py')], required=False)
    # 3b：北单逐场近况/交锋（澳客比赛页；500 全站被 EdgeOne 拦，云端只能走澳客）
    step('3b/6 北单情报（澳客近况/交锋）', [os.path.join('scripts', 'fetch_bj_okooo.py')], required=False)
    # 3c：澳客三维情报（伤停阵容/技术统计/积分战意）——替代被封的 500 数据页，零人工验证
    step('3c/6 三维情报（澳客）', [os.path.join('scripts', 'fetch_intel_okooo.py')], required=False)
    # 3d：澳客赛果（复盘回填用）+ 当日快照（保住历史比分，否则隔天复盘永远查不到）
    step('3d/6 赛果与历史快照', [os.path.join('scripts', 'fetch_results_okooo.py')], required=False)
    step('3e/6 当日快照', [os.path.join('scripts', 'snapshot_history.py')], required=False)
    # 3f：退役/告别公告（直播吧足球新闻，关键词过滤后按队名挂到对应场次）
    step('3f/6 退役公告', [os.path.join('scripts', 'fetch_retire.py')], required=False)
    step('4/6 抓取大乐透开奖 + 选号', [os.path.join('scripts', 'fetch_dlt.py')], required=False)
    # 5/8：把浏览器抓下来的 500 数据页文本解析成 intel500.json（本地没有抓取目录就跳过）
    step('5/8 解析 500 情报', [os.path.join('scripts', 'parse_intel500.py')], required=False)
    # 5b：按归档真实赛果把每场分析从一句扩成多段（排名/校准/翻车/联赛平局/近况/交锋/伤停/结论）
    step('5/8 分析增强（归档实算）', [os.path.join('scripts', 'enrich_ana.py')], required=False)
    # 5a：任九 14 场逐场分析（原本只有竞彩 8 场有分析，任九是 0/14）
    step('5a/8 任九逐场分析', [os.path.join('scripts', 'enrich_sfc.py')], required=False)
    step('5/6 生成单页', ['make_live.py'], cwd=os.path.join(BASE, 'engine'))
    step('6/6 后处理（文案/布局修正）', [os.path.join('scripts', 'postfix.py')])
    # 7/7：模板里「今日竞彩 / 今日北单 / 2串1」是写死的旧快照，必须用当天抓到的真实数据覆盖
    step('7/7 今日数据覆盖（竞彩/北单/2串1）', [os.path.join('scripts', 'fix_today.py')])

    p = os.path.join(BASE, 'index.html')
    if not os.path.exists(p):
        print('[build] 没有产出 index.html')
        return 1
    print('\n[build] 完成 → index.html · %.1f KB' % (os.path.getsize(p) / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
