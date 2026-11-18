# -*- coding: utf-8 -*-
"""把本目录推送到 GitHub —— 不依赖本机 git，直接走 REST API。

    python scripts/push_github.py --token ghp_xxx --repo hb-football-lab
    python scripts/push_github.py --token ghp_xxx --repo hb-football-lab --private true

参数：
    --token    GitHub Personal Access Token（需要 repo 权限；fine-grained 勾 Contents: Read and write）
    --repo     仓库名（默认 hb-football-lab）
    --private  true/false（默认 false，Pages 免费版要 public）
    --owner    用户名，省略则用 token 所属账号
    --branch   默认 main
    --dry-run  只打印将要上传的文件清单，不发请求

流程：建仓库 → 建 blobs → 建 tree → 建 commit → 移动分支引用。
"""
import argparse, base64, json, os, sys, time, urllib.request, urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://api.github.com'
SKIP_DIRS = {'.git', '__pycache__', '.idea', '.vscode'}
SKIP_FILES = {'_check.png', '.DS_Store', 'Thumbs.db'}


def api(method, path, token, payload=None):
    url = path if path.startswith('http') else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'hb-lab-push',
        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')[:300]
        raise RuntimeError('%s %s → %s %s' % (method, path, e.code, body))


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace('\\', '/')
            yield rel, full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', required=True)
    ap.add_argument('--repo', default='hb-football-lab')
    ap.add_argument('--private', default='false')
    ap.add_argument('--owner', default='')
    ap.add_argument('--branch', default='main')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    files = list(walk(BASE))
    total = sum(os.path.getsize(f) for _, f in files)
    print('[push] 待上传 %d 个文件 · %.1f MB' % (len(files), total / 1024 / 1024))
    if a.dry_run:
        for rel, f in files[:15]:
            print('   %8.1f KB  %s' % (os.path.getsize(f) / 1024, rel))
        print('   ...')
        return 0

    me = api('GET', '/user', a.token)
    owner = a.owner or me['login']
    print('[push] 账号 %s' % owner)

    # 1) 建仓库（已存在就当更新）
    try:
        api('POST', '/user/repos', a.token, {
            'name': a.repo, 'private': a.private.lower() == 'true',
            'description': 'HB FOOTBALL LAB · 体彩每日自动抓取与建模',
            'auto_init': False})
        print('[push] 已新建仓库 %s/%s' % (owner, a.repo))
    except RuntimeError as e:
        if '422' in str(e):
            print('[push] 仓库已存在，按更新处理')
        else:
            raise

    # 2) 建 blobs
    tree = []
    t0 = time.time()
    for i, (rel, full) in enumerate(files, 1):
        blob = api('POST', '/repos/%s/%s/git/blobs' % (owner, a.repo), a.token, {
            'content': base64.b64encode(open(full, 'rb').read()).decode(),
            'encoding': 'base64'})
        tree.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        if i % 25 == 0 or i == len(files):
            print('   %d/%d · %.0fs' % (i, len(files), time.time() - t0))

    # 3) tree / commit / 分支
    t = api('POST', '/repos/%s/%s/git/trees' % (owner, a.repo), a.token,
            {'tree': tree})
    msg = 'init: HB FOOTBALL LAB 每日自动更新版 %s' % time.strftime('%Y-%m-%d %H:%M')
    ref = 'refs/heads/' + a.branch
    try:
        cur = api('GET', '/repos/%s/%s/git/ref/' + ref % (owner, a.repo), a.token)
        commit = api('POST', '/repos/%s/%s/git/commits' % (owner, a.repo), a.token,
                     {'message': msg, 'tree': t['sha'], 'parents': [cur['object']['sha']]})
        api('PATCH', '/repos/%s/%s/git/refs/' + ref % (owner, a.repo), a.token,
            {'sha': commit['sha'], 'force': True})
    except RuntimeError:
        commit = api('POST', '/repos/%s/%s/git/commits' % (owner, a.repo), a.token,
                     {'message': msg, 'tree': t['sha'], 'parents': []})
        api('POST', '/repos/%s/%s/git/refs' % (owner, a.repo), a.token,
            {'ref': ref, 'sha': commit['sha']})

    print('[push] 完成：https://github.com/%s/%s' % (owner, a.repo))
    print('[push] 下一步：Settings → Pages → Deploy from a branch → %s → / (root)' % a.branch)
    return 0


if __name__ == '__main__':
    sys.exit(main())
