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
    step('3/6 抓取北单在售', [os.path.join('scripts', 'fetch_bjdc.py')], required=False)
    step('4/6 抓取大乐透开奖 + 选号', [os.path.join('scripts', 'fetch_dlt.py')], required=False)
    step('5/6 生成单页', ['make_live.py'], cwd=os.path.join(BASE, 'engine'))
    step('6/6 后处理（文案/布局修正）', [os.path.join('scripts', 'postfix.py')])

    p = os.path.join(BASE, 'index.html')
    if not os.path.exists(p):
        print('[build] 没有产出 index.html')
        return 1
    print('\n[build] 完成 → index.html · %.1f KB' % (os.path.getsize(p) / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
