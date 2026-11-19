# HB FOOTBALL LAB · 每日自动更新版

中国体彩 · 竞彩/任九/北单/大乐透 的单页分析站。整个站点是**一个自包含 HTML 文件**，
每天由 GitHub Actions 自动抓官方赔率、重算模型、重新生成，推到 GitHub Pages。

> 仅供自己看数据、复盘用。彩票是概率游戏，历史命中率不能预测未来，**理性购彩，量力而行**。

---

## 它每天做了什么

```
官方接口 webapi.sporttery.cn          GitHub Actions (北京时间 11:00)
        │                                      │
        ▼                                      ▼
 scripts/fetch.py  ──►  engine/data/full.json  ──►  engine/make_live.py
   欧赔去水 + 泊松反解 λ                        │
   主推/备选/双选/比分分布/大小球格局            ▼
                                        engine/index_live.html
                                                │
                                        scripts/postfix.py（文案与布局修正）
                                                │
                                                ▼
                                          index.html  → Pages
```

一条命令等价于上面整条流水线：

```bash
python scripts/build.py
```

---

## 目录

| 路径 | 作用 |
|---|---|
| `index.html` | **成品页**（Pages 入口，自动生成，别手改） |
| `scripts/fetch.py` | 抓官方竞彩 had 赔率 → `engine/data/full.json`；失败保留旧数据，不产生空白页 |
| `engine/make_live.py` | 把数据内联进 `engine/template.html`，产出单页（爆炸雷达、四档复盘、冷热、8 维因子都在模板里） |
| `scripts/postfix.py` | 生成后的文案/布局修补（22 条规则，幂等，集中管理） |
| `scripts/build.py` | 串起 1→2→3，CI 与本地都用它 |
| `.github/workflows/daily.yml` | 每天 UTC 03:00 定时跑 + 手动触发 |
| `engine/data/*.json` | 数据快照（任九推荐、北单复盘、大乐透、历史交锋库等） |
| `审计修复落地清单.md` | 原作者留下的审计记录，保留以追溯口径 |

---

## 自动化覆盖到哪一步（重要，别指望它自己变魔术）

| 板块 | 每天自动更新 | 说明 |
|---|---|---|
| 竞彩（胜平负） | ✅ 全自动 | 官方 JSON 接口，8 场左右的在售场次，含赔率、λ、概率、比分分布、主推/双选 |
| 比分 | ✅ 全自动 | 用的就是竞彩那份数据 |
| 爆炸风险雷达 | ⚠️ 数据在动，口径固定 | 用 1322 场历史校准表打分，换场次就会变，但校准表本身需要另行重算 |
| 任九（14 场） | ✅ 全自动 | `scripts/fetch_sfc.py` 抓 500 网任九页（GBK 表格），期号、14 场对阵、排名每天更新；**赔率开售后**才算模型（页面照实显示"赔率未公布 · 不编造"） |
| 北单 | ✅ 全自动 | `scripts/fetch_bjdc.py` 抓北单在售页：场次、赛事、欧赔、让球、去水概率、完赛比分（29 场左右） |
| 大乐透 | ✅ 全自动 | `scripts/fetch_dlt.py` 抓 500 网开奖历史（官方接口 WAF 返回 567，做不通），583 期入库 → 频率/近 60 期热度/遗漏三因子重算 → 三注选号 |

四个板块都不再依赖手工快照：每天跑 `scripts/build.py` 就全部重抓、重算、重生成。
`engine/data/sfc_pick.json`、`engine/data/_bj_latest_full.json`、`engine/dlt_pick.json` 现在都是**脚本产出**，别再手改（会被覆盖）。

**数据源与限制**（写清楚，避免误判"为什么数字变了"）：

| 板块 | 源 | 限制 |
|---|---|---|
| 竞彩/比分 | `webapi.sporttery.cn` getMatchCalculatorV1 | 只给在售场次；停售即消失 |
| 任九 | `trade.500.com/sfc/` | 赔率未开售时页面是 `-`，脚本只写对阵不算模型 |
| 北单 | `trade.500.com/bjdc/` | 欧赔为真实抓取；让球盘口文字原样保留，不折算成概率 |
| 大乐透 | `datachart.500.com` 开奖历史 | 只做年/日干支推算；**节气、月相、建除、卦象本版未接入**，玄学标签已降级为"玄学（简版）"，不冒充原版 |

**大乐透玄学层降级说明**：原项目那套四柱/纳音/月相/飞星/卦象需要一整套历法与卦象引擎，
本仓库只实现了年干支、日干支与五行取色（`WX_OF_GAN` + `day_gz()`，锚点 2026-11-16 甲午），
其余字段不再写死假值。评分主体（历史频率 40% + 近 60 期热度 35% + 遗漏 25%）与原口径一致。

---

## 8 维因子为什么都是"估算"

模板里的 8 维因子要靠临场情报（伤停、首发、战意、赛程密度等）喂数据。
本仓库只抓官方赔率，没有情报源，所以 8 维一律标记为 `est`（估算）——页面顶部那句
"8 维因子仅用于文字解释，未参与数值计算"就是这个意思。**宁可不给，也不编造。**

---

## 本地跑

```bash
python scripts/fetch.py     # 只抓数据
python scripts/build.py     # 抓+建页
start index.html            # Windows
```

无第三方依赖，纯标准库（Python 3.9+）。

## 部署到自己的 GitHub

1. 新建仓库（Public 才能用免费 Pages）。
2. 推送本目录到 `main`。
3. Settings → Pages → Source 选 **Deploy from a branch**，分支 `main`，目录 `/ (root)`。
4. 之后每天 Actions 自动跑；日志里能看到抓了几场。

没有本机 git 时，用仓库自带的推送脚本（走 GitHub API，不需要装 git）：

```bash
python scripts/push_github.py --token <你的PAT> --repo hb-football-lab --private false
```

PAT 只需要 `repo` 权限（fine-grained token 勾 Contents: Read and write 即可）。

## 数据来源与合规

- 赔率与赛程：中国体育彩票官方公开接口 `webapi.sporttery.cn`，仅作个人学习分析使用。
- 历史校准表、交锋库等快照来自原项目既有数据，未做二次分发。
- 请勿把本页用于商业转售或代购；不在页面上诱导投注。
