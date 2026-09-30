# 多航段运价组合培训沙箱

> ⚠️ **纯培训系统**：所有航班、舱位、运价、票号（`TRN-` 前缀）均为虚构。
> 系统**不连接任何真实订座（PNR/GDS）、出票、支付或退款系统**，
> "出票 / 改签 / 补收 / 退还"都只是沙箱 PostgreSQL 里的状态与数字。

用于讲解一个核心概念：**多航段行程的票价来自"运价组件（fare component）"，
一个组件可以覆盖多个航段，票价不是逐段单段价简单相加。**

## 技术栈

- 后端：Django + Django REST Framework，金额全程 `decimal.Decimal`
  （`ROUND_HALF_UP`，精确到分；百分比税不用 float）
- 存储：PostgreSQL（虚构航班 / 舱位库存 / 运价 / 规则版本 / 规则 / 税 /
  培训票 / 票联 / 试算与命中记录）
- 前端：Vue 3（`<script setup>`）+ Vite，无额外 UI 框架
- 规则：沙箱表达式语言（**不是** `eval`），AST 白名单求值，
  禁止属性访问 / 函数调用 / import / lambda

## 教学点如何落地

| 教学点 | 实现 |
| --- | --- |
| 票价不是逐段相加 | 引擎枚举 N 段的全部 `2^(N-1)` 种连续切分；一个运价组件通过 `FareRouteLeg` 覆盖多段，按组件价 + 分列税计价，选含税最低的合法组合 |
| 停留 / 转机 | 衔接 `>=24h` 为停留，否则转机；转机时长只统计转机点，停留点不参与转机时限 |
| 最短 / 最长停留日 | 往返行程按去程出发地与折返点的**本地日历日期差**算 `stay_days` |
| 联程组合限制 | 多组件拼接时，任一运价 `end_on_end_allowed=False` 即淘汰；另有 `scope=BOUNDARY/BOTH` 的规则对组件间衔接点求值 |
| 时间双重校验 | 内部统一存 UTC；"跨日"按中转机场 IANA 时区观察本地日历判定，绝不减日期字符串 |
| 规则表达式 | `min_layover_minutes >= 45 and max_layover_minutes < 1440`、`stopover_count <= 1`、`stay_days >= 3 and stay_days <= 14`、`date_change_count == 0`、`booking_class in ['M','H']`、`has_saturday_night == true` |
| 舱位不可用 | `HARD-AVAILABILITY` 硬规则在表达式之前执行，余座 0 / CLOSED 直接淘汰 |
| 税项分列 | 民航发展基金（按段）/ 燃油附加（按组件）/ 增值税（按基数 %）分别入 `QuoteTax`，前端逐项展示 |
| 改签顺序 | ① 先查剩余票联（`OPEN` 才可改，`USED/EXCHANGED` 在计价前阻断）→ ② 新行程重新试算 → ③ 价差 + 手续费；正数模拟补收、负数模拟退还 |
| 结果可追规则版本 | 每次试算固定到一个 `RuleVersion`（报价单、每条 `RuleHit` 都带版本号 + 表达式 + 取值现场） |

## 内置案例（前端"试算实验室"一键载入）

| 案例 | 行程 | 预期 |
| --- | --- | --- |
| A | CA1201 + MU2317，M 舱 | 联程运价 `PEKKWL-MX`（¥700）一个组件覆盖两段，中选；逐段拼 ¥780 更贵 |
| A2 | CA1209 + MU2325，Q 舱 | 单段各 ¥300/¥320 看似最便宜，但 `PEKXIY-Q` **禁止 end-on-end**，无法组合，整体无可用报价 |
| B (v2) | CA1211 23:30 到 XIY → MU2319 次日 00:50 飞 | 80 分钟是转机但跨过 XIY **本地日期**；v2 新增 `DATE-01/DATE-CC` 拒绝（红眼中转） |
| B' (v1) | 同上，选 `RULE-2026-Q4-v1` | 旧版无跨午夜规则，放行并出 ¥820.20 —— 同一行程不同规则版本结果不同 |
| C | 同 B 但选 Q 舱 | 两段 Q 舱均 `CLOSED / 0 座`，被舱位硬规则淘汰 |
| D | CA1201 + MU2331 | 西安停留 25.5 小时（≥24h 计停留），`stopover_count <= 1` 放行 |
| RT | 10/20 去、10/25 回 | 停留 5 天（≥3、≤14）且含周六过夜，往返运价成立 |
| RT' | 10/22 即回 | 停留 2 天 + 无周六过夜，最短停留与周六过夜规则同时拒绝 |

改签演练：对 A 的培训票改到 10/21 早班（CA1203+MU2318），票联全 OPEN 时
算出价差 0 + 手续费 ¥100；执行"培训换开"后旧票联全部 `EXCHANGED`，
再次改签会在**计价之前**被票联状态检查拦下（HTTP 409）。

## API 速览

| 方法/路径 | 说明 |
| --- | --- |
| `GET /api/flights/` | 虚构航班 + 舱位库存（含 UTC/当地时间） |
| `GET /api/fares/` | 运价、路由腿、规则表达式、版本 |
| `GET /api/rule-versions/` | 规则版本 |
| `GET /api/taxes/` | 分列税项 |
| `POST /api/quotes/price/` | 试算：`{flight_ids, booking_classes, booking_date, rule_version?}`；返回组件、税、全部候选切分与规则命中轨迹 |
| `POST /api/quotes/{id}/issue_training/` | 生成 `TRN-` 培训票（沙箱） |
| `GET /api/tickets/` | 培训票与票联状态 |
| `POST /api/changes/quote/` | 改签试算（先票联、后计价） |
| `POST /api/changes/{id}/commit/` | 培训换开（只改沙箱票联状态） |

## 本地运行

需要 Python 3.11+、Node 18+ 与一个可连接的 PostgreSQL。

```bash
# 后端
pip install django djangorestframework psycopg2-binary
# 数据库连接见 fare_pricing/settings.py（默认 /tmp:55432, 库 farebook, 用户 fareuser）
python manage.py migrate
python manage.py seed            # 载入虚构航班/运价/规则/税
python manage.py runserver 0.0.0.0:8000

# 前端（开发，带 /api 代理）
cd frontend
npm install
npm run dev                      # http://localhost:5173

# 或构建后由 Django 直接托管
npm run build                    # 产物到 frontend/dist，访问 http://localhost:8000/
```

## 关键目录

```
pricing/
  models.py                  # Airport/Flight/CabinInventory/Fare/Rule/
                             # RuleVersion/TaxRule/Quote/RuleHit/
                             # TrainingTicket/Coupon/ChangeQuote
  engine/
    rules_expr.py            # AST 白名单表达式求值器
    timeutils.py             # UTC ↔ 机场本地时间、跨本地日期、停留日、周六过夜
    pricing.py               # 组合枚举 + 规则判定 + Decimal 计价 + 命中落库
    rebooking.py             # 票联前置检查 → 价差/手续费 → 培训换开
  management/commands/seed.py# 虚构数据与全部教学案例
frontend/src/
  views/PriceLab.vue         # 场景、行程时间轴、候选组合、规则命中轨迹
  views/RuleBook.vue         # 规则版本与表达式
  views/Tickets.vue          # 培训票 + 改签四步
```

## 明确不做的事

- 不调用任何航司 / GDS / OTA 接口，不占座、不出真实票号
- 不生成真实支付、扣款、退款指令；页面上的补收/退还均为模拟数字
- 规则表达式不具备通用代码执行能力（白名单 AST，无属性/调用/导入）
