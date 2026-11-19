#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机自动循环：抓官方数据 → 重建页面 → 推送 GitHub → 部署 Netlify

为什么要本机跑：
  GitHub 的机器在境外，访问体彩官方接口会 567、访问澳客会 405（地域拦截），
  所以「竞彩 + 任九 + 北单 + 澳客情报」只能在国内这台机器上抓。
  云端 Actions 保留（跑得通的部分照跑），本机这个循环负责把数据补齐。

用法（由 Windows 计划任务每 30 分钟调一次）：
  python scripts/local_cycle.py
"""
import io
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC = os.environ.get('HB_SECRETS', r'C:\Users\MACHENIKE\Doubao\chats\2026-11-18\new-chat-7\_work\secrets.json')
LOG = os.path.join(BASE, 'raw', 'local_cycle.log')


def log(msg):
    line = '[%s] %s' % (time.strftime('%m-%d %H:%M'), msg)
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def run(args, env=None, tail=600):
    r = subprocess.run([sys.executable] + args, cwd=BASE, capture_output=True, text=True,
                       encoding='utf-8', errors='ignore', env=env)
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    return r.returncode, out[-tail:]


def main():
    sec = json.load(io.open(SEC, encoding='utf-8'))
    log('=== 本轮开始 ===')
    rc, out = run(['scripts/build.py'])
    log('构建 rc=%d' % rc)
    if rc != 0:
        log(out)
        return 1
    # 构建产物同步到 public/（本机 build.py 不会自己复制）
    with io.open(os.path.join(BASE, 'index.html'), 'rb') as f:
        data = f.read()
    with io.open(os.path.join(BASE, 'public', 'index.html'), 'wb') as f:
        f.write(data)
    env = dict(os.environ)
    env.update({'GH_TOKEN': sec['gh'], 'GH_REPO': 'hb3493331880-gif/hb-lab-live',
                'GH_DIR': BASE, 'NF_TOKEN': sec.get('nf', ''),
                'NF_SITE_ID': '7876d565-90fe-4236-afd7-61a3bacba8a0'})
    rc1, out1 = run(['scripts/push_fast.py'], env=env, tail=200)
    log('推送 rc=%d · %s' % (rc1, out1.replace('\n', ' | ')[-160:]))
    rc2, out2 = run(['scripts/deploy_netlify.py'], env=env, tail=200)
    log('部署 rc=%d · %s' % (rc2, out2.replace('\n', ' | ')[-160:]))
    return 0 if (rc1 == 0 and rc2 == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
