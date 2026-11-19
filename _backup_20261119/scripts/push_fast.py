# -*- coding: utf-8 -*-
"""多线程把工作目录整个推到 GitHub（Git Data API），不依赖本机 git。

修正了 hb-lab 原 push_github.py 的两个问题：
  1. `'/git/ref/' + ref % (...)` 运算符优先级 bug → TypeError，最后一步必崩；
  2. 串行建 blob，268 个文件要 11 分钟 → 改 8 线程并发，约 1-2 分钟。
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = 'https://api.github.com'
SKIP = {'.git', '__pycache__', '.venv', 'node_modules'}
SKIP_EXT = ('.pyc', '.zip', '.log')


def api(method, path, tok, payload=None):
    req = urllib.request.Request(API + path,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 method=method,
                                 headers={'Authorization': 'Bearer ' + tok,
                                          'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'hb-lab-push',
                                          'Content-Type': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode() or '{}')
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')[:200]
            if e.code in (502, 503, 504) and attempt < 3:
                time.sleep(2)
                continue
            raise RuntimeError('%s %s → %s %s' % (method, path, e.code, body))


def main():
    tok = os.environ['GH_TOKEN']
    repo = os.environ['GH_REPO']
    branch = os.environ.get('GH_BRANCH', 'main')
    root = os.path.abspath(os.environ.get('GH_DIR', '.'))
    owner, name = repo.split('/')

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if fn.endswith(SKIP_EXT):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            files.append((full, rel))
    total = sum(os.path.getsize(f) for f, _ in files)
    print('[push] %s → %s/%s · %d 文件 · %.1f MB' % (root, owner, name, len(files), total / 1048576))

    def mk(item):
        full, rel = item
        for attempt in range(3):
            try:
                data = open(full, 'rb').read()
                r = api('POST', '/repos/%s/%s/git/blobs' % (owner, name), tok,
                        {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
                return rel, r['sha'], None
            except Exception as e:
                if attempt == 2:
                    return rel, None, str(e)[:160]
                time.sleep(2 + attempt * 3)

    t0 = time.time()
    entries = []
    fails = []
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rel, sha, err in ex.map(mk, files):
            done += 1
            if sha:
                mode = '100755' if rel.endswith('.sh') else '100644'
                entries.append({'path': rel, 'mode': mode, 'type': 'blob', 'sha': sha})
            else:
                fails.append((rel, err))
            if done % 40 == 0:
                print('   %d/%d · %.0fs' % (done, len(files), time.time() - t0))
    print('   blob 完成 %.0fs · 成功 %d · 失败 %d' % (time.time() - t0, len(entries), len(fails)))
    for rel, err in fails[:5]:
        print('   [失败]', rel, err)
    if fails and len(fails) > 5:
        print('   ... 其余 %d 个' % (len(fails) - 5))

    tree = api('POST', '/repos/%s/%s/git/trees' % (owner, name), tok,
               {'tree': entries})  # 不带 base_tree：整仓以本次上传为准

    parent = None
    try:
        ref = api('GET', '/repos/%s/%s/git/ref/heads/%s' % (owner, name, branch), tok)
        parent = ref['object']['sha']
    except RuntimeError as e:
        if '409' not in str(e) and '404' not in str(e):
            raise
        print('[push] 目前没有 %s 分支，本次为首次提交' % branch)

    commit = api('POST', '/repos/%s/%s/git/commits' % (owner, name), tok, {
        'message': 'deploy: 自动更新站点源码（引擎/脚本/数据/页面）%s' % time.strftime('%F %H:%M'),
        'tree': tree['sha'],
        **({'parents': [parent]} if parent else {})})

    if parent:
        api('PATCH', '/repos/%s/%s/git/refs/heads/%s' % (owner, name, branch), tok,
            {'sha': commit['sha'], 'force': True})
    else:
        api('POST', '/repos/%s/%s/git/refs' % (owner, name), tok,
            {'ref': 'refs/heads/' + branch, 'sha': commit['sha']})

    print('[push] 完成 · commit %s · 用时 %.0fs' % (commit['sha'][:8], time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
