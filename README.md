# 多航段运价组合培训台（虚构数据，不接真实订座/出票）

一个用于机票服务培训的全栈演示：讲清**多航段票价不是逐段公布价简单相加**，
而是由一个或多个**运价组件（fare component）**组合而成；停留、转机、
最短/最长停留、联程组合限制按**规则表达式**逐条判定；时间以
**UTC 物理时刻 + 机场当地日历**双重校验。

- 后端：Django 5.2 + Django REST Framework，金额全程 `Decimal`
- 存储：PostgreSQL（`docker-compose.yml`）；本地无 PG 时回退 SQLite
- 前端：Vue 3 + Vite，金额用 `decimal.js`，API 金额字段一律 JSON 字符串
- 规则：自研受限表达式 DSL（Python `ast` 白名单遍历，**非 `eval`**），
  规则带**版本**，试算结果回链版本主键
- 边界：只做报价/改签**试算**，不生成真实购票、出票、换开、退款指令

## 一、培训要点与实现位置

| 培训概念 | 实现 |
| --- | --- |
| 票价 = 运价组件之和，RT 一个价覆盖去+回 | `backend/pricing/engine.py`：`_enumerate_blocks` 穷举 OW(1段)/RT(2段) 切分 |
| 单段便宜但不能组合 | 特价 Q 舱 `COMBINABILITY: components_count == 1` |
| 转机 / 中途停留 | `timeutils.STOPOVER_HOURS=24`；两段来回程接续点标为 `TURNAROUND_STAY`（受最短/最长停留约束，不计入禁止性中途停留） |
| 最短 / 最长停留日 | 规则 `stay_days >= 3`、`stay_days <= 14`；`stay_days` 取折返点**当地日历**日差 |
| 跨日不能只减字符串日期 | `timeutils.local_date_diff` 用 `zoneinfo` 换算当地日期；接续点同时返回 `local_calendar_diff_days` 与 `utc_date_diff_days` |
| 联程组合限制 | 规则 DSL，见 `pricing/rules_lang.py`；上下文见 `engine.quote` |
| 改签先查票联状态 | `engine._check_coupons`：非 OPEN 在计价前终止 |
| 再算价差/手续费 | `engine.rebook`：新行程重算 → 现行规则版本判手续费 |
| 税项分别列示 | `TaxDefinition` 按舱等逐段计收，响应里按 CN/YQ/XT 分行 |
| 试算可追到规则版本 | `FareRuleVersion` + `Rule.version`，命中结果带 `version_id/version_number` |
| 不出真实指令 | 仅 `quote`/`rebook` 两个只读试算接口；订单/票联不被试算修改（有测试锁定） |

## 二、内置虚构案例（前端一键载入）

1. **来回程 4 天**：YRT 净价 3200 < 两个 YOW 相加 4200，组件组合更便宜
2. **最短停留失败**：次日即回，当地停 1 天 < 3 天
3. **跨时区当日回**：SHA 23:00(+08)→URC，当地凌晨到、上午走，当地日历差 **0 天**，
   UTC 裸日期差 **1 天**（演示不能用 UTC/字符串日期直接减）
4. **Q 特价单段便宜但不能拼**：去 Q(450) + 回 Y，COMBINABILITY 拒绝
5. **三角程 SHA-PEK-URC-SHA**：1 转机 + 1 中途停留，三个 OW 组件
6. **某段舱位不可用**：MU5107 的 Q 舱库存 0，前置校验拦截
7. **跨日期最长停留**：停 19 天 > 14 天，MAX_STAY 失败

改签案例：`TST101`（正常）、`TST202`（首张票联 USED，被拦）、
`TST303`（出票冻结规则 v1，改签按现行 v2 计费，300→500）。

## 三、启动

### 方式 A：Docker Compose（PostgreSQL + 后端 + 前端）

```bash
docker compose up --build
# 后端 http://localhost:8000/api/  前端 http://localhost:5173
```

首次启动自动 `migrate` + `seed_demo`（灌入虚构航班/舱位/运价/规则/客票）。

### 方式 B：本地裸跑（无 Docker，SQLite 回退）

```bash
# 后端
python3 -m venv .venv --without-pip   # 若系统无 ensurepip，先 bootstrap pip
.venv/bin/pip install -r backend/requirements.txt
cd backend
DB_ENGINE=sqlite ../.venv/bin/python manage.py migrate
DB_ENGINE=sqlite ../.venv/bin/python manage.py seed_demo
DB_ENGINE=sqlite ../.venv/bin/python manage.py runserver

# 前端（另开终端）
cd frontend
npm install
npm run dev    # http://localhost:5173 ，/api 代理到 8000
```

连接本机 PostgreSQL 时设环境变量：`DB_ENGINE=postgres DB_HOST=... DB_USER=...
DB_PASSWORD=... DB_NAME=...`。

## 四、接口

| 方法 & 路径 | 说明 |
| --- | --- |
| `GET /api/airports/` | 虚构机场（含 IANA 时区） |
| `GET /api/flights/?origin=&destination=&date=` | 虚构航班，返回 UTC 与当地双时刻、舱位余位 |
| `GET /api/fares/` | 运价 |
| `GET /api/fares/{id}/versions/` | 运价的历史/当前规则版本与表达式 |
| `POST /api/quote/` | `{"segments":[{flight_id,rbd}, ...]}` 穷举组件组合并回传命中明细 |
| `POST /api/rebook/` | `{"pnr","changes":[{coupon_seq,new_flight_id,new_rbd}]}` 票联→规则→价差/手续费/税 |

金额字段在 JSON 中全部为字符串（如 `"3700.00"`），避免 JS 浮点。

## 五、规则表达式示例（受限 DSL）

```text
same_carrier and component.rbd in ["Y", "B"]
stopovers <= 1 and transfers <= 2
stay_days == None or stay_days >= 3
components_count == 1
days_before_departure >= 7 and same_cabin
```

上下文变量：`n_segments / stopovers / transfers / stay_days / same_carrier /
all_rbds / all_carriers / components_count / components / component`（当前组件）；
改签手续费另含 `changed_segments / same_cabin / days_before_departure`。
允许：布尔/比较/算术运算、常量、列表、属性/下标、`len/min/max/any/all/abs`。
禁止：属性逃逸、导入、任意调用、推导式（测试中有安全用例锁定）。

## 六、测试

```bash
cd backend
DB_ENGINE=sqlite ../.venv/bin/python manage.py test pricing
```

覆盖：DSL 安全与语义、时区/当地日历、7 个报价案例、改签三条链路、API 序列化、
“试算不修改票联状态”。
