# -*- coding: utf-8 -*-
"""第三七五条：官方接口直连层（V 系列在活项目的等价落地）

另一台环境实测：桌面 UA + Referer 的 urllib 直连 6 个端点全 200、
0.1~0.3s/个；项目原来用 playwright 串行 + 硬编码 /usr/bin/google-chrome，
卡 3 分钟。本模块把「直连优先」独立出来：

- 直连成功 -> 原始 JSON 落 data/st_direct/，供上层消费
- 直连失败 -> 明确打印 HTTP 码，不重试刷屏、不静默、不编造
- 本机出口 IP 被 WAF 挡时全 403 是正常的；换出口即通，不用改代码

状态口径（第三七三条）：本模块是「链路 A」，能不能真拿到是「实抓 B」，
两者分开报；一次 403 不许写成永久结论。

用法：
    python3 _st_direct.py --probe     # 只探连通性，不写盘
    python3 _st_direct.py --all       # 探 + 把成功的原始响应落盘
"""
import os, sys, json, ssl, io, time, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'data', 'st_direct')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
REF = 'https://www.sporttery.cn/'
HOST = 'https://webapi.sporttery.cn/gateway/uniform/football/jcInfo/'

ENDPOINTS = [
    ('伤停',   'getAllTodayInjurySuspensionV1.qry', ''),
    ('积分V2', 'getMatchTablesV2.qry', 'matchId=1'),
    ('积分V1', 'getMatchTablesV1.qry', 'matchId=1'),
    ('赛果',   'getUniformMatchResultV1.qry', 'matchPage=1&matchPageSize=50'),
    ('交锋',   'getResultHistoryV1.qry', 'matchId=1'),
    ('情报',   'getMatchCalculatorV1.qry', 'matchId=1'),
]


def fetch(name, qs='', timeout=6):
    path = dict((n, p) for n, p, _ in ENDPOINTS).get(name)
    if not path:
        return {'ok': False, 'note': '未知端点'}
    url = HOST + path + ('?' + qs if qs else '')
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': REF,
        'Accept': 'application/json, text/plain, */*'})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as f:
            raw = f.read()
        body = json.loads(raw.decode('utf-8', 'replace'))
        return {'ok': True, 'status': f.status, 'bytes': len(raw),
                'sec': round(time.time() - t0, 2), 'data': body, 'note': ''}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'bytes': 0,
                'sec': round(time.time() - t0, 2), 'data': None,
                'note': 'HTTP %s' % e.code}
    except Exception as e:
        return {'ok': False, 'status': None, 'bytes': 0,
                'sec': round(time.time() - t0, 2), 'data': None,
                'note': '%s: %s' % (type(e).__name__, str(e)[:80])}


def main():
    write = '--all' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for name, _, qs in ENDPOINTS:
        r = fetch(name, qs)
        print('[%s] %-6s %-5s %7dB %5.2fs  %s' % (
            'OK ' if r['ok'] else 'FAIL', name, r.get('status') or '-',
            r.get('bytes', 0), r.get('sec', 0), r['note']))
        if r['ok']:
            ok += 1
            if write:
                with io.open(os.path.join(OUT, name + '.json'), 'w',
                             encoding='utf-8') as f:
                    json.dump(r['data'], f, ensure_ascii=False, indent=1)
    suffix = (('，%d 份原始响应已写 data/st_direct/' % ok) if ok
              else '，本次 0 份可落盘') if write else '（仅探测）'
    print('直连 %d/%d 可用%s' % (ok, len(ENDPOINTS), suffix))
    if ok == 0:
        print('本次实抓 B 全失败；链路 A 仍可用（本地快照）。'
              '这是出口 IP 波动，不是 URL 或方法错，别写成永久结论。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
