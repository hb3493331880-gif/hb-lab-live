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
    step('4/6 抓取大乐透开奖 + 选号', [os.path.join('scripts', 'fetch_dlt.py')], required=False)
    # 5/8：把浏览器抓下来的 500 数据页文本解析成 intel500.json（本地没有抓取目录就跳过）
    step('5/8 解析 500 情报', [os.path.join('scripts', 'parse_intel500.py')], required=False)
    # 5b：按归档真实赛果把每场分析从一句扩成多段（排名/校准/翻车/联赛平局/近况/交锋/伤停/结论）
    step('5/8 分析增强（归档实算）', [os.path.join('scripts', 'enrich_ana.py')], required=False)
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
