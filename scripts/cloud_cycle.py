# -*- coding: utf-8 -*-
"""云端（GitHub Actions）一轮更新：只用云端能访问的源（澳客 m 站 200），
跳过被地域拦截的体彩(567)/500(403)步骤，产出 index.html 并做质量门禁。

在 runner 上运行；本机不改用它（本机走 local_cycle.py 全量）。
退出码 0 = 可提交；2 = 门禁不通过（放弃本次，保留线上旧版）。
"""
import io
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def step(title, args, cwd=None):
    print('\n=== %s ===' % title)
    t0 = time.time()
    r = subprocess.run([PY] + args, cwd=cwd or BASE, capture_output=True, text=True,
                       encoding='utf-8', errors='ignore')
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    for ln in out.splitlines()[-8:]:
        print('  ' + ln)
    print('  (%.1fs, rc=%d)' % (time.time() - t0, r.returncode))
    return r.returncode


def gate():
    p = os.path.join(BASE, 'index.html')
    if not os.path.exists(p):
        print('[gate] 没有 index.html')
        return False
    t = io.open(p, encoding='utf-8').read()
    size = os.path.getsize(p)
    checks = {
        '体积>1MB': size > 1048576,
        '任九定价明细≥10段': t.count('定价明细') >= 10,
        '同档校准': '【同档校准·已开】' in t,
        '北单今日': 'window.__BJ_TODAY__' in t,
        '立即更新按钮': 'hbRefreshBtn' in t,
        '任九逐场情报': t.count('【情报·近况】') >= 6,
    }
    print('[gate] %d bytes · ' % size + ' · '.join('%s=%s' % (k, v) for k, v in checks.items()))
    print('[gate] 定价明细=%d 加厚=%d 竞彩覆盖=%d' % (t.count('定价明细'), t.count('加厚'), t.count('竞彩赔率云端覆盖')))
    return all(checks.values())


def main():
    # 云端可达：澳客 m 站（期次页/北单/赛果/变盘）
    # 顺序很重要：先抓赛程（会写 0 赔率），再补赔率，否则赔率被覆盖成空
    step('B 任九期次与赛程（澳客 m）', ['scripts/fetch_sfc.py'])
    step('A 任九 14 场赔率（澳客 m）', ['scripts/fetch_sfc_okooo.py'])
    step('C 任九变盘', ['scripts/sfc_delta.py'])
    step('C2 任九逐场情报（澳客近况/交锋/伤停/阵容/积分）', ['scripts/fetch_sfc_intel.py'])
    step('D 北单在售（澳客 m）', ['scripts/fetch_bj_mobile.py'])
    step('E 全量赛果回填（澳客）', ['scripts/fetch_results_all.py'])
    # 竞彩：体彩 webapi 在云端 567 被锁，改走澳客页面（云端可达），产出 jc_okooo_page.json
    step('E2 竞彩赔率（澳客页）', ['scripts/fetch_okooo_lottery.py'])
    step('F 竞彩变盘', ['scripts/odds_delta.py'])
    step('G 生成单页', ['make_live.py'], cwd=os.path.join(BASE, 'engine'))
    step('H 后处理', ['scripts/postfix.py'])
    step('I 今日数据覆盖', ['scripts/fix_today.py'])
    return 0 if gate() else 2


if __name__ == '__main__':
    sys.exit(main())
