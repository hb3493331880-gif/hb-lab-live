# -*- coding: utf-8 -*-
"""赛果历史快照：把今天的 full.json / _bj_latest_full.json / sfc_pick.json 存一份带日期的副本。

为什么必须有这一步：full.json 每天被覆盖，隔天就查不到昨天的比分，
2串1 的注单第二天再判命中时永远拿不到赛果 —— 复盘就一直空着。
副本落在 engine/data/history/，fix_today 的赛果索引会把它们并进来。
"""
import io, json, os, shutil, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'engine', 'data')
HIS = os.path.join(DATA, 'history')

SRC = ['full.json', '_bj_latest_full.json', 'sfc_pick.json', 'results_index.json']


def main():
    if not os.path.isdir(HIS):
        os.makedirs(HIS)
    stamp = time.strftime('%Y%m%d')
    n = 0
    for name in SRC:
        p = os.path.join(DATA, name)
        if not os.path.isfile(p):
            continue
        stem = os.path.splitext(name)[0].lstrip('_')
        dst = os.path.join(HIS, '%s_%s.json' % (stem, stamp))
        try:
            shutil.copyfile(p, dst)
            n += 1
        except Exception as e:
            print('  [history] %s 失败 %s' % (name, e))
    # 只留最近 60 天，避免仓库无限膨胀
    files = sorted(os.listdir(HIS))
    if len(files) > 240:
        for f in files[:len(files) - 240]:
            os.remove(os.path.join(HIS, f))
    print('  [history] 快照 %d 个文件 → %s' % (n, stamp))


if __name__ == '__main__':
    main()
