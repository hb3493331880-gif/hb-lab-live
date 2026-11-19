# -*- coding: utf-8 -*-
"""只推指定文件的轻量推送（Git Data API + base_tree），3~5 个文件约 10 秒。

用法：GH_TOKEN=... GH_REPO=... GH_DIR=... python scripts/push_sel.py index.html .github/workflows/daily.yml
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = 'https://api.github.com'


def api(method, path, tok, payload=None):
    req = urllib.request.Request(API + path,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 method=method,
                                 headers={'Authorization': 'Bearer ' + tok,
                                          'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'hb-lab-push',
                                          'Content-Type': 'application/json'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode() or '{}')
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')[:300]
            if e.code in (502, 503, 504) and attempt < 4:
                time.sleep(2 + attempt * 2)
                continue
            raise RuntimeError('%s %s → %s %s' % (method, path, e.code, body))


def main(argv):
    tok = os.environ['GH_TOKEN']
    repo = os.environ['GH_REPO']
    branch = os.environ.get('GH_BRANCH', 'main')
    root = os.path.abspath(os.environ.get('GH_DIR', '.'))
    owner, name = repo.split('/')
    rels = argv[1:]
    if not rels:
        print('[sel] 没有指定文件')
        return 2

    t0 = time.time()
    entries = []
    for rel in rels:
        full = os.path.join(root, rel.replace('/', os.sep))
        if not os.path.exists(full):
            print('[sel] 跳过（不存在）', rel)
            continue
        data = open(full, 'rb').read()
        blob = api('POST', '/repos/%s/%s/git/blobs' % (owner, name), tok,
                   {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
        entries.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print('   blob %s · %d B · %s' % (rel, len(data), blob['sha'][:8]))

    ref = api('GET', '/repos/%s/%s/git/ref/heads/%s' % (owner, name, branch), tok)
    parent = ref['object']['sha']
    base = api('GET', '/repos/%s/%s/git/commits/%s' % (owner, name, parent), tok)['tree']['sha']
    tree = api('POST', '/repos/%s/%s/git/trees' % (owner, name), tok,
               {'base_tree': base, 'tree': entries})
    commit = api('POST', '/repos/%s/%s/git/commits' % (owner, name), tok, {
        'message': 'deploy: 页面加「立即更新」按钮 + 发布器改 push 触发（%s）' % time.strftime('%F %H:%M'),
        'tree': tree['sha'], 'parents': [parent]})
    api('PATCH', '/repos/%s/%s/git/refs/heads/%s' % (owner, name, branch), tok,
        {'sha': commit['sha'], 'force': True})
    print('[sel] 完成 · commit %s · 用时 %.0fs' % (commit['sha'][:8], time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
