#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ 第三六八条：审计修复后的真机回归验证（Playwright + Chromium）。"""
import os
import json
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
URL = 'file://' + os.path.join(BASE, 'index_live.html')
OUT = {}


def main():
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, executable_path='/usr/bin/google-chrome',
                              args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = br.new_page(viewport={'width': 390, 'height': 780})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:220]))
        pg.goto(URL, wait_until='load', timeout=90000)
        pg.wait_for_timeout(2200)

        OUT['pageerror'] = errs
        OUT['js'] = pg.evaluate("""() => {
          const o = {};
          o.escQuote = (typeof esc==='function') ? esc("'") : 'NO_ESC';
          o.cd = (document.getElementById('cd')||{}).textContent || '';
          o.deadlineRaw = (typeof SFC!=='undefined' && SFC) ? String(SFC._截止||'') : 'NO_SFC';
          try{
            const r = (typeof r9Unified==='function') ? r9Unified({apply:false}) : [];
            const k={}; r.forEach(x=>{ k[x.best.kind]=(k[x.best.kind]||0)+1; });
            o.kinds=k; o.unifiedN=r.length;
          }catch(e){ o.errUnified=String(e); }
          try{
            if(typeof r9Plans==='function') r9Plans();
            const sig=(window.__R9_PLANS||[]).map(P=>P.picks.map(q=>q.no+':'+q.idx).join(','));
            o.planSigs=sig; o.planUnique=new Set(sig).size; o.planN=sig.length;
          }catch(e){ o.errPlans=String(e); }
          o.pickFn=typeof __pickR9; o.syncFn=typeof __syncR9;
          return o;
        }""")

        # P0-0 真机复现路径：手动选 3 场 → 触发重绘 → 不应被清空
        try:
            OUT['p0_0'] = pg.evaluate("""() => {
              try{
                __R9_SEL={}; sfc={};
                __pickR9('01',1); __pickR9('02',1); __pickR9('03',1);
                const before=Object.keys(sfc).length;
                __syncR9();
                const after=Object.keys(sfc).length;
                return {before, after, selN:Object.keys(__R9_SEL).length};
              }catch(e){ return {err:String(e)}; }
            }""")
        except Exception as e:
            OUT['p0_0'] = {'err': str(e)}

        # 9 tab 扫描：undefined / NaN / [object
        tabs = pg.evaluate("""() => Array.from(document.querySelectorAll('[data-v],[data-tab],.navbtn,.tabbtn'))
                    .map(e=>e.getAttribute('data-v')||e.getAttribute('data-tab')||e.textContent.trim())
                    .filter(x=>x&&x.length<12).slice(0,20)""")
        OUT['tabsFound'] = tabs
        bad = []
        for t in tabs:
            try:
                pg.evaluate("(t)=>{ try{ if(typeof go==='function') go(t); }catch(e){} }", t)
                pg.wait_for_timeout(180)
                txt = pg.evaluate("() => document.body.innerText")
                for k in ['undefined', 'NaN', '[object Object]']:
                    if k in txt:
                        bad.append('%s:%s' % (t, k))
            except Exception:
                pass
        OUT['tabBad'] = bad
        OUT['pageerrorFinal'] = errs
        br.close()

    print(json.dumps(OUT, ensure_ascii=False, indent=1))
    ok = (len(OUT['pageerror']) == 0
          and OUT['js'].get('escQuote') == '&#39;'
          and OUT['js'].get('kinds', {}).get('爆冷', 0) > 0
          and OUT['js'].get('planUnique') == OUT['js'].get('planN')
          and OUT['p0_0'].get('after') == 3
          and not OUT['tabBad'])
    print('\n==== 回归结论:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
