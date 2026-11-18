#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 public/ 打包成 zip，直接走 Netlify 部署 API 上线（不需要 netlify-cli、不需要 git 集成）。

用法：
    NF_TOKEN=xxx NF_SITE_ID=yyy python scripts/deploy_netlify.py
退出码：0 = 部署已提交并完成；非 0 = 失败（并打印 Netlify 返回的原因）。
"""
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, 'public')
API = 'https://api.netlify.com/api/v1'


def api(method, path, token, data=None, ctype='application/json'):
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token,
        'User-Agent': 'hb-lab-deploy',
        'Content-Type': ctype})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8') or '{}')


def main():
    token = os.environ.get('NF_TOKEN', '').strip()
    site = os.environ.get('NF_SITE_ID', '').strip()
    if not token or not site:
        print('[失败] 缺 NF_TOKEN 或 NF_SITE_ID')
        return 2
    if not os.path.isfile(os.path.join(PUB, 'index.html')):
        print('[失败] public/index.html 不存在，不部署残站')
        return 1

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(PUB)):
            full = os.path.join(PUB, fn)
            if os.path.isfile(full):
                z.write(full, fn)
    blob = buf.getvalue()
    print('[打包] public/ → %d B zip' % len(blob))

    dep = api('POST', '/sites/%s/deploys' % site, token, data=blob,
              ctype='application/zip')
    did = dep.get('id')
    print('[提交] deploy id=%s' % did)
    for _ in range(40):
        d = api('GET', '/deploys/%s' % did, token)
        if d.get('state') in ('ready', 'current'):
            print('[完成] state=%s url=%s' % (d.get('state'), d.get('ssl_url') or d.get('deploy_ssl_url')))
            return 0
        if d.get('state') in ('error', 'failed', 'rejected'):
            print('[失败] state=%s %s' % (d.get('state'), d.get('error_message')))
            return 1
        time.sleep(3)
    print('[超时] 部署仍在进行，稍后到 Netlify 面板看结果')
    return 0


if __name__ == '__main__':
    sys.exit(main())
