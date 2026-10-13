# 美术侧资产项目管理系统 Implementation Plan

> **For agentic workers:** REQUIRED: Use `superpowers:subagent-driven-development` (if subagents are available) or `superpowers:executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在新域名上构建一个与现有“时装投放管理台”功能等价、但面向美术资产生产管理的系统，并可靠打通 Redmine、工程目录/P4、UE 配置、截图产物和权限链路。

**Architecture:** 保留“前端只依赖同源业务接口”的访问模型。前端通过 `asset-pm-api` 读取统一读模型；后端通过 `RedmineAdapter`、`EngineeringScanAdapter`、`ArtifactStore` 访问外部系统；同步任务将外部数据转换为带来源和版本的快照，再由读模型服务页面。所有写入操作经过权限、幂等键和审计记录。

**Tech Stack:** React + TypeScript；Python 3.11 + FastAPI；PostgreSQL；后台任务使用进程内 worker 或 Redis 队列；产物存储使用内部对象存储或受控 NAS；HTTPS 反向代理；OpenAPI、Pytest、Playwright。

---

## 0. 范围、前置条件和不可假设项

### 目标范围

- 第一版先实现只读功能：投放日历、制作进度、制作分析、外观/资产查询。
- 第二版再开放资产登记、Redmine 更新、评论、产物回写等写操作。
- 新域名独立部署，不修改当前域名的服务和数据。
- 保留当前接口的兼容层，使现有页面或迁移脚本可以继续读取 `/api/state`、`/api/status`、`/api/redmine-workbench` 等快照。

### 开始接入真实数据前必须拿到的输入

- 新域名、HTTPS 证书和反向代理位置属于部署阶段输入，当前本地开发和数据链路设计不等待它们。
- 新系统使用的 Redmine 项目 ID，或确认继续读取 C7 项目。
- Redmine 只读账号；写入账号在第二阶段单独申请。
- 工程目录、P4 workspace/client、UE 配置目录和截图目录的访问方式。
- 运行环境：Windows 服务、容器平台或 Linux 服务；不能继续依赖当前 `SimpleHTTP/0.6` 静态服务作为生产入口。
- 用户角色：美术、制作人、程序、审核人、管理员，以及各自可见和可写范围。

### 必须标成未知、不能猜测的部分

- 当前后端究竟通过 Redmine REST API、页面抓取还是内部脚本读取 Redmine。
- P4 是由服务端直接执行命令、读取已有 workspace，还是读取定时生成的中间文件。
- 截图生成器和产物目录的实际进程边界。
- 当前 `/api` 是否由静态服务器代理到另一个端口。

如果暂时拿不到这些信息，按“黑盒兼容路径”执行：先导入当前快照和固定测试夹具，使用新的适配器替换真实数据源，不能把黑盒推断写成事实。

### 没有新域名和 HTTPS 时的开发入口

- API 固定使用 `http://127.0.0.1:8000`，前端开发服务器使用 `http://127.0.0.1:5173`。
- 前端开发服务器把 `/api` 代理到 API，页面代码永远只请求相对路径，不把端口、域名或 Redmine 地址写死。
- 没有真实数据访问权限时，使用脱敏快照夹具和 `scripts/import_snapshot.py` 导入；这条路径必须和真实同步后的读模型使用同一套接口。
- 如需同网段临时验收，只允许绑定开发机内网地址并限制访问来源；不把临时端口当作生产入口，不把 HTTP 方案固化到部署配置。
- 未来拿到域名和证书后，只增加反向代理和认证配置，前端、API、数据模型和同步 worker 不改。

---

## 1. 目标仓库结构和模块接口

新系统建议使用独立仓库 `asset-pm/`，目录职责固定如下：

```text
asset-pm/
├─ apps/web/
│  ├─ src/pages/                 # 日历、进度、分析、查询页面
│  ├─ src/features/assets/       # 资产查询和资产详情
│  ├─ src/features/tasks/        # Redmine 任务和阶段视图
│  ├─ src/features/calendar/     # 投放日历和行列映射
│  ├─ src/api/client.ts           # 唯一前端接口入口
│  └─ tests/
├─ services/api/app/
│  ├─ domain/                     # Asset、Task、Stage、Artifact、SyncRun
│  ├─ api/routes/                 # HTTP 路由，只处理鉴权和参数
│  ├─ application/                # 查询、同步、登记用例
│  ├─ ingestion/                  # 原始快照、来源版本和导入状态
│  ├─ read_models/                # 日历、进度、分析、目录读模型
│  ├─ adapters/redmine.py         # RedmineAdapter 的具体实现
│  ├─ adapters/engineering_scan.py# 工程目录/P4/UE 扫描实现
│  ├─ adapters/artifact_store.py  # 图片和文件产物实现
│  ├─ repositories/               # 数据库和快照读写
│  └─ workers/                    # Redmine、工程扫描、产物同步任务
├─ migrations/
├─ config/source-map.yaml         # 来源、字段、同步顺序和刷新周期
├─ scripts/import_snapshot.py     # 无真实数据权限时导入脱敏快照
├─ tests/contract/                # API 契约和数据夹具
├─ tests/integration/             # 外部适配器模拟测试
├─ deploy/                        # 反向代理、服务、环境变量模板
└─ docs/                          # 数据字典、运行手册、回滚手册
```

### 外部接口的深模块设计

前端只学习以下少量接口；复杂的认证、分页、重试、字段映射和异常处理都收进适配器：

```text
RedmineAdapter
  list_issues(project_id, cursor, filters) -> IssuePage
  get_issue(issue_id) -> Issue
  get_issue_cost(issue_ids) -> CostMap
  update_issue(issue_id, patch, idempotency_key) -> Issue

EngineeringScanAdapter
  scan(scope, revision) -> AssetSnapshot

ArtifactStore
  put(content, metadata) -> ArtifactRef
  get_url(artifact_id) -> SignedOrInternalUrl
```

这三个接口是替换真实实现的 seam。测试使用内存 adapter；生产环境使用 Redmine、P4/工程目录和对象存储 adapter。

### 现有页面已确认的数据链路

以下结论来自当前页面、前端 bundle 和只读响应。`observed` 表示已从页面或接口看到，`inferred` 表示根据字段关系推断，`unknown` 表示必须取得后端源码或部署配置才能确认。

| 页面/能力 | 当前读入口 | 已观察到的数据 | 新系统的目标读模型 | 当前来源结论 |
|---|---|---|---|---|
| 投放日历 | `/api/state`、`/cloud-state.json` | `calendar.rows`、`calendarRowOverrides`、`calendarAppendedRows`、`customAssets`、`assetResults`、`configResults`、`runtimeStatus` | `calendar_view`、`asset_progress_view`、`sync_health_view` | 日历与人工覆盖已确认；原始表格/文件来源 `unknown` |
| 制作进度 | `/api/state`、`/production-progress.json`、必要时 `/api/assets` | 资产、男/女变体、阶段、截图状态、Redmine 任务号；页面显示约 222 个资产和 9 个阶段 | `production_progress_view` | 资产结果、配置结果、产物状态已确认；页面的最终拼装位置需在 Task 1 固化 |
| 制作分析 | `/api/redmine-workbench`、`/redmine-workbench.json` | 约 1697 个子任务、18 个分组、7 个专业、状态、负责人、甘特日期、完成历史和运行状态 | `redmine_workbench_view`、`completion_history_view` | 响应声明来源为 Redmine；实际采集方式 `unknown` |
| 外观查询 | `/api/appearance-catalog?...` | 外观表行、`fashionId`、`itemId`、男女关联、子类型、版本、注册状态、fingerprint、套装配对 | `appearance_catalog_view`、`registration_view` | Fashion/挂载/角色编辑器/展厅等来源在页面中有说明；实际文件入口 `unknown` |
| 截图和产物 | `/production-outputs.json`、`assetResults` | 截图路径、男/女状态、capture fingerprint、解析结果；现有完整 JSON 约 38 MB | `artifact_view` | 产物文件引用已确认；生成进程和存储目录 `unknown` |
| 人工覆盖和登记 | `/api/state`、前端写接口 | aliases、custom assets、删除 ID、行覆盖、登记批次、评论/输出写入入口 | `user_override`、`catalog_registration`、`audit_log` | 写接口路由可见，不能据此推断后端持久化实现 |

### 统一数据链路

新系统所有页面都沿用下面的单向链路，页面不自行跨源拼数据：

```text
外部来源
  ├─ Redmine：任务、负责人、状态、计划日期、完成记录
  ├─ 日历/投放表：投放行、版本、周次、人工覆盖
  ├─ 工程目录/P4/UE：FashionID、ItemID、MeshID、资源路径、配置关系
  ├─ 截图/产物目录：图片、视频、文件、capture 状态和 hash
  └─ 人工操作：别名、登记、覆盖、评论、关联修正
        ↓
1. SourceSnapshot：保存原始响应/文件 hash、来源 revision、抓取时间、解析器版本
        ↓
2. Normalize：统一日期、状态、性别、版本、路径和 ID 格式
        ↓
3. IdentityResolve：按稳定 ID 和 fingerprint 建立资产、任务、变体、套装关系
        ↓
4. Join：将日历行、资产配置、Redmine 任务、截图产物关联起来
        ↓
5. ReadModel：原子生成 calendar/progress/analysis/catalog 四类读模型
        ↓
6. API：返回 data、source、readAt、generation、stale、errors
        ↓
7. 页面：只负责筛选、排序、分页、展示和跳转
```

### 数据关联规则

- 首选显式外键：`redmine_issue_id`、`fashion_id`、`item_id`、`mesh_id`、`artifact_id`、日历行稳定 ID。
- 第二选择是稳定复合键：`source + source_sheet + source_row`、`suit_pair_key`、来源文件 hash。
- `fingerprint` 只用于判断内容是否变化、去重和登记幂等，不替代业务主键。
- 名称、显示文本和负责人姓名只能用于搜索或人工候选，不能作为自动关联主键。
- 男女外观/套装关系先按 `anotherGenderId`、`suitPairKey` 和 FashionID 双向校验；任一侧不一致时进入人工待确认，不强行合并。
- 一个来源失败时不能删除其他来源的最后成功数据；只更新该来源的 `stale` 和错误信息。

### 同步顺序和失败边界

1. Redmine、日历表、工程扫描和产物导入可以并行建立各自 `SourceSnapshot`。
2. 只有来源快照成功落盘后，才进入标准化和身份解析。
3. 读模型刷新等待依赖来源的 generation；生成成功后一次性切换当前 generation。
4. 页面读取当前成功 generation；任何单源失败都返回上一次可用数据，并在对应区域显示数据过期时间。
5. 同步任务使用 `run_id` 和幂等键；重复执行不能产生重复任务、重复事件或重复产物。
6. 真实刷新周期通过 `config/source-map.yaml` 配置：Redmine 增量短周期、工程扫描按变更或定时、产物导入高频轮询、全量校验低频运行；在确认现有调度器前不把具体分钟数当成事实。

### 无域名阶段的本地数据链路

```text
脱敏快照/开发夹具
  → scripts/import_snapshot.py
  → 本地 SnapshotRepository
  → 本地 ReadModelBuilder
  → 127.0.0.1:8000/api
  → 127.0.0.1:5173 页面
```

真实数据权限拿到后，只替换输入侧：

```text
RedmineAdapter / EngineeringScanAdapter / ArtifactStore
  → SourceSnapshotRepository
  → Normalize + IdentityResolve + Join
  → ReadModelBuilder
  → 同一套 API 和前端
```

因此，域名和 HTTPS 不属于当前数据链路开发的阻塞条件；它们只影响最后的入口、认证、证书和反向代理。

---

## 2. Task 1：冻结现有系统的黑盒证据

**目标：** 把当前域名的行为记录成可回归的证据，而不是只凭页面印象重写。

**Files:**

- Create: `docs/reverse/endpoint-catalog.md`
- Create: `docs/reverse/data-dictionary.md`
- Create: `docs/reverse/current-page-data-map.md`
- Create: `docs/reverse/observed-response-samples/*.json`
- Create: `tests/fixtures/current-system/*.json`
- Create: `tests/fixtures/current-system/README.md`

- [ ] 记录首页、四个页面、所有只读接口的 URL、方法、状态码、响应大小、更新时间和认证头。
- [ ] 记录 `/api/state`、`/api/status`、`/api/redmine-workbench`、`/api/appearance-catalog` 的字段和数组关系。
- [ ] 对四个页面逐一记录“页面字段 → 当前接口字段 → 新读模型字段 → 来源状态”，并标出 observed/inferred/unknown。
- [ ] 记录静态 fallback：`/cloud-state.json`、`/redmine-workbench.json`、`/production-progress.json`、`/production-comments.json`、`/production-outputs.json`，明确它们是兼容输入，不是新系统的长期接口。
- [ ] 记录页面实际显示的数量、筛选项、阶段列、更新时间和错误提示，形成 UI 回归基线。
- [ ] 用脱敏夹具保存 3 类数据：一个日历行、一个资产、一个 Redmine 子任务、一个外观配置。
- [ ] 只检查写接口的路由和请求格式，不调用 `/api/redmine-workbench/refresh`、`/api/appearance-catalog/register`、`/api/service/restart` 等写入或重启接口。
- [ ] 如果能取得服务端部署文件，确认静态前端、API 进程、定时任务和文件目录；如果不能，给每条结论标注 `observed`、`inferred` 或 `unknown`。
- [ ] 验收：任何开发者只阅读本目录，就能知道页面依赖哪些数据和哪些字段不能丢失。

### Task 1A：固化来源快照和字段血缘

**Files:**

- Create: `docs/domain/source-contracts.md`
- Create: `docs/domain/page-lineage.md`
- Create: `config/source-map.yaml`
- Create: `services/api/app/ingestion/source_contracts.py`
- Create: `services/api/app/ingestion/snapshot_envelope.py`
- Create: `services/api/app/application/resolve_identity.py`
- Create: `services/api/app/application/join_sources.py`
- Create: `services/api/app/read_models/build_views.py`
- Create: `tests/contract/test_lineage.py`

- [ ] 为 `calendar`、`redmine`、`engineering`、`artifact`、`manual` 建立 source registry，声明输入格式、刷新方式、主键、可用字段和失败策略。
- [ ] 统一原始快照信封：`source_type`、`source_locator`、`source_revision`、`fetched_at`、`content_hash`、`parser_version`、`status`、`error_count`。
- [ ] 为每个页面字段保存最小血缘：源快照 ID、源字段、转换规则、关联 ID、最终读模型字段。
- [ ] 实现显式外键优先、复合键其次、fingerprint 去重、名称仅候选的关联算法。
- [ ] 为资产详情提供 lineage 查询，使用户能看到资产来自哪一条日历行、哪个 Redmine 任务、哪个工程文件和哪个产物。
- [ ] 验收：至少用一条日历资产、一条 Redmine 任务、一条男女配对外观和一张截图跑通完整血缘；任一来源失败时不会误删其他来源数据。

---

## 3. Task 2：建立领域模型、数据来源和兼容契约

**目标：** 将当前扁平 JSON 快照拆成可追踪的领域数据。

**Files:**

- Create: `docs/domain/data-lineage.md`
- Create: `docs/domain/status-mapping.md`
- Create: `docs/domain/page-read-models.md`
- Create: `docs/api/openapi.yaml`
- Create: `services/api/app/domain/models.py`
- Create: `services/api/app/domain/identifiers.py`
- Create: `tests/contract/test_current_snapshot_contract.py`

- [ ] 定义稳定标识：`redmine_issue_id`、`source + source_sheet + source_row`、`fashion_id`、`item_id`、`mesh_id`、`fingerprint`。
- [ ] 定义实体：`Project`、`Asset`、`AssetVariant`、`ProductionTask`、`StageEvent`、`Artifact`、`SyncRun`、`SourceSnapshot`、`UserOverride`、`AuditLog`。
- [ ] 建立来源矩阵：Redmine 负责任务、负责人、状态、计划时间；日历/投放表负责投放行和计划字段；工程扫描负责资产、Mesh、UE 路径和配置解析；产物存储负责截图和文件；人工覆盖只存差异和操作者。
- [ ] 为四个读模型分别列出字段来源、关联键、刷新依赖、允许为空的原因和过期展示规则。
- [ ] 定义状态映射：Redmine 状态 → 生产阶段 → 页面颜色/进度；缺失或过期数据必须能显示 `stale` 和来源时间。
- [ ] 定义兼容响应：`GET /api/state`、`GET /api/status`、`GET /api/redmine-workbench`、`GET /api/appearance-catalog`。
- [ ] 定义新版本接口：`/api/v1/assets`、`/api/v1/tasks`、`/api/v1/catalog`、`/api/v1/sync-runs`、`/api/v1/artifacts`。
- [ ] 验收：用当前快照夹具运行契约测试，字段缺失、状态未知、过期快照都有明确结果。

---

## 4. Task 3：搭建只读 API 和快照仓库

**目标：** 在没有接入真实 Redmine/P4 的情况下，先让新前端能稳定显示当前功能。

**Files:**

- Create: `services/api/app/main.py`
- Create: `services/api/app/api/routes/health.py`
- Create: `services/api/app/api/routes/assets.py`
- Create: `services/api/app/api/routes/tasks.py`
- Create: `services/api/app/api/routes/catalog.py`
- Create: `services/api/app/api/routes/compatibility.py`
- Create: `services/api/app/repositories/snapshot_repository.py`
- Create: `services/api/app/application/read_model.py`
- Create: `services/api/app/ingestion/local_snapshot_loader.py`
- Create: `scripts/import_snapshot.py`
- Create: `apps/web/vite.config.ts`
- Create: `deploy/local/docker-compose.dev.yml`
- Create: `tests/contract/test_read_api.py`
- Create: `tests/unit/test_read_model.py`

- [ ] 写 `/health`，只返回版本、依赖状态和最近同步时间，不暴露本机磁盘路径、凭据或完整异常。
- [ ] 实现快照仓库，从脱敏夹具读取数据，并支持按来源时间和 generation 查询。
- [ ] 实现 `scripts/import_snapshot.py`，把当前系统的脱敏响应或静态 fallback 转成统一 `SourceSnapshot`，不让页面直接读取 JSON 文件。
- [ ] 实现四个读模型查询：`calendar_view`、`production_progress_view`、`redmine_workbench_view`、`appearance_catalog_view`；日历、资产、任务和产物的 join 只能发生在服务端。
- [ ] 对大字段做分页和字段裁剪，禁止把当前约 38 MB 的 base64 产物 JSON 作为普通列表响应。
- [ ] 加入 `source`、`readAt`、`generation`、`stale`、`errors` 元数据。
- [ ] 提供本地启动路径：API 在 `127.0.0.1:8000`，前端在 `127.0.0.1:5173`，开发代理将 `/api` 转发到 API。
- [ ] 将 API base URL、来源路径、刷新周期和鉴权开关全部放进环境配置，不写死新域名或 HTTPS。
- [ ] 先用内存/文件 adapter 跑通，再接 PostgreSQL；数据库迁移不改变领域接口。
- [ ] 验收：在没有域名和 HTTPS 的情况下，执行 `python scripts/import_snapshot.py` 后访问 `http://127.0.0.1:5173` 可以看到四个页面；契约测试全部通过；同一快照多次读取结果一致；读取失败时页面得到可解释的降级状态。

---

## 5. Task 4：实现前端只读 MVP

**目标：** 新域名先提供与当前系统四个页面等价的只读能力。

**Design reference:** `docs/superpowers/specs/2026-10-10-amnisstudio-frontend-visualization-and-links-design.md`

**Files:**

- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/pages/CalendarPage.tsx`
- Create: `apps/web/src/pages/ProgressPage.tsx`
- Create: `apps/web/src/pages/AnalysisPage.tsx`
- Create: `apps/web/src/pages/AppearanceCatalogPage.tsx`
- Create: `apps/web/src/components/SyncStatus.tsx`
- Create: `apps/web/src/components/StaleDataBanner.tsx`
- Create: `apps/web/tests/pages/*.spec.ts`

- [ ] 只允许 `src/api/client.ts` 发请求，页面不直接拼接 Redmine URL 或访问工程盘。
- [ ] 页面只读取对应读模型；禁止在 React 组件中把日历、Redmine 和工程扫描结果再次交叉拼接。
- [ ] 先复刻现有四个功能面的信息结构：投放日历、制作进度、制作分析、外观查询。
- [ ] 对 222 个资产、9 个阶段、1697 个子任务、外观配置分页使用虚拟列表或服务端分页。
- [ ] 保留 Redmine 跳转链接，但链接只指向任务详情，不把 Redmine 凭据交给前端。
- [ ] 显示数据来源、同步时间、失败提示和快照过期提示。
- [ ] 写 Playwright 验收：页面加载、筛选、分页、详情跳转、后端不可用时的降级。
- [ ] 验收：在相同快照下，核心计数、任务状态、阶段名称和外观配置数量与现有系统一致。

---

## 6. Task 5：实现 Redmine 只读同步

**目标：** 把 Redmine 从页面快照来源变成可重复运行的后端同步任务。

**Files:**

- Create: `services/api/app/adapters/redmine.py`
- Create: `services/api/app/workers/redmine_sync.py`
- Create: `services/api/app/application/sync_redmine.py`
- Create: `services/api/app/repositories/issue_repository.py`
- Create: `tests/integration/test_redmine_adapter.py`
- Create: `tests/fixtures/redmine/*.json`

- [ ] 先确认认证方式：优先使用正式 Redmine API/service account；不能把浏览器 SSO cookie 或页面抓取作为长期接口。
- [ ] 实现分页、限流、超时、重试、失败续跑和响应缓存。
- [ ] 按 `redmine_issue_id` 幂等 upsert，不以任务标题或负责人姓名作为主键。
- [ ] 保存原始响应的 hash、抓取时间、Redmine 更新时间和解析错误。
- [ ] 将任务、负责人、tracker、状态、开始/结束日期、版本、父任务和完成记录转换为统一模型。
- [ ] 同步完成后只发布 `redmine` source generation；由 read-model worker 负责把任务映射到资产和阶段，Redmine adapter 不直接改页面字段。
- [ ] 先只读运行，生成对账报告：总数、状态分布、负责人数量、逾期数量、缺失字段数量。
- [ ] 验收：对同一个 Redmine 项目连续同步两次不会产生重复数据；接口中断时保留上一次可用快照并标记过期。

---

## 7. Task 6：实现工程目录/P4/UE 配置扫描

**目标：** 将当前资产和配置解析链路变成可测试、可替换的扫描 adapter。

**Files:**

- Create: `services/api/app/adapters/engineering_scan.py`
- Create: `services/api/app/application/scan_assets.py`
- Create: `services/api/app/workers/engineering_scan.py`
- Create: `services/api/app/parsers/fashion_table.py`
- Create: `services/api/app/parsers/ue_config.py`
- Create: `services/api/app/parsers/asset_composition.py`
- Create: `tests/fixtures/engineering/*.json`
- Create: `tests/integration/test_engineering_scan.py`

- [ ] 先确认扫描入口：P4 workspace、只读导出目录或预生成 JSON；服务账号只授予所需目录和 P4 读取权限。
- [ ] 解析 Fashion/外观表、角色编辑器配置、MeshID、材质/特效、UE 路径和车辆/挂载配置。
- [ ] 为每个源文件记录 `source_path`、修改时间、P4 change number、文件 hash 和解析器版本。
- [ ] 输出 `AssetSnapshot`，不直接修改工程文件，不执行 P4 submit、sync 或 checkout。
- [ ] 对同一 `fashion_id` 的男女配对、套装关联和异性外观关联进行确定性归并。
- [ ] 将 `actualChannel`、`actualRelease`、`actualGoodsIds`、`actualShopIds`、`actualReferencedItemIds` 等配置结果归入配置视图，不把原始工程路径直接暴露给前端。
- [ ] 扫描完成后只发布 `engineering` source generation；资产关联和页面阶段由统一 join/read-model 流程完成。
- [ ] 解析失败时保留部分结果和错误明细，不覆盖上一次完整快照。
- [ ] 验收：用一组男/女时装、配饰、角色部件和 UE 配置夹具，得到稳定的资产关系和来源路径；重复扫描 hash 不变化时不生成无意义变更。

---

## 8. Task 7：实现截图和其他产物存储

**目标：** 将截图从大 JSON/base64 响应改为可追踪产物引用。

**Files:**

- Create: `services/api/app/adapters/artifact_store.py`
- Create: `services/api/app/application/artifacts.py`
- Create: `services/api/app/api/routes/artifacts.py`
- Create: `services/api/app/workers/capture_import.py`
- Create: `tests/unit/test_artifact_store.py`

- [ ] 产物以文件或对象存储保存，数据库只保存 `artifact_id`、hash、mime、尺寸、来源、版本和权限信息。
- [ ] 按内容 hash 去重；同一截图不能因为同步重复产生多个文件。
- [ ] 使用内部 URL 或短时签名 URL，禁止把工程盘路径直接返回给浏览器。
- [ ] 保留男/女、阶段、资产、任务和截图批次的关联。
- [ ] 将当前 `assetResults` 中的 capture 状态、capture fingerprint、图片路径转换为 `Artifact` 和 `ArtifactLink`，页面只拿 artifact ID/URL。
- [ ] 产物导入只更新 `artifact` generation；不能因为一张截图导入失败而回滚 Redmine 或工程扫描数据。
- [ ] 处理丢失文件、损坏图片、权限失败和超大文件。
- [ ] 验收：列表响应不包含 base64；缩略图、原图、过期产物和删除标记都有明确行为。

---

## 9. Task 8：建立历史、分析和读模型刷新

**目标：** 让“制作分析”和“进度变化”不再依赖覆盖式 JSON。

**Files:**

- Create: `services/api/app/application/build_read_model.py`
- Create: `services/api/app/workers/read_model_refresh.py`
- Create: `services/api/app/repositories/history_repository.py`
- Create: `apps/web/src/pages/AnalysisPage.tsx`
- Create: `tests/integration/test_read_model_refresh.py`

- [ ] 每次同步生成 `SyncRun`，保存开始时间、结束时间、来源 revision、成功/失败计数和错误。
- [ ] 任务状态变化写入 `StageEvent`，不通过覆盖当前状态来丢失历史。
- [ ] 计算完成率、逾期率、各阶段耗时、负责人分布和数据新鲜度。
- [ ] 只有所有必需来源的 join 完成后才发布新的 read-model generation；非必需来源缺失时发布部分结果并标记具体区域 `stale`。
- [ ] 同步和读模型刷新分离：外部系统暂时不可用时，页面仍返回最近成功读模型。
- [ ] 验收：用两组时间序列夹具验证阶段变化、回退、补数据和重复同步不会产生重复事件。

---

## 10. Task 9：实现写入能力和审计

**目标：** 在只读 MVP 稳定后，再开放资产登记和 Redmine 写回。

**Files:**

- Create: `services/api/app/api/routes/mutations.py`
- Create: `services/api/app/application/register_asset.py`
- Create: `services/api/app/application/update_task.py`
- Create: `services/api/app/security/authorization.py`
- Create: `services/api/app/repositories/audit_repository.py`
- Create: `tests/integration/test_mutations.py`

- [ ] 所有写接口要求角色授权、二次确认或审批状态，并强制携带 `idempotency_key`。
- [ ] 资产登记先写本地申请记录，再由 worker 执行外部写入；外部成功前不能显示为已完成。
- [ ] Redmine 写回只通过 `RedmineAdapter.update_issue`，不让前端提交任意 Redmine URL 或原始字段。
- [ ] 保存操作者、旧值、新值、来源、请求号、外部响应和失败原因。
- [ ] 为写操作增加 dry-run、回滚/补偿和人工重试状态。
- [ ] 验收：重复提交只产生一次外部变更；权限不足、外部超时、部分成功和重试都能审计和恢复。

---

## 11. Task 10：认证、安全和新域名部署

**Files:**

- Create: `deploy/reverse-proxy/asset-pm.conf`
- Create: `deploy/service/asset-pm-api.service.example`
- Create: `deploy/env/asset-pm.env.example`
- Create: `docs/operations/deploy.md`
- Create: `docs/operations/rollback.md`
- Create: `tests/security/test_authorization.py`

- [ ] 通过公司 SSO/统一认证获取用户身份；后端根据用户组映射角色和项目权限。
- [ ] 在没有域名和 HTTPS 时，先使用本机回环地址和开发账号完成功能验收；不把临时明文入口、开发密钥或浏览器 session 方案带入生产。
- [ ] 前端和 API 使用 HTTPS；API 默认 same-origin，禁止宽松 CORS。
- [ ] Redmine/P4/对象存储凭据只存在服务端密钥管理中，不进入 bundle、JSON、日志或浏览器 storage。
- [ ] 健康检查只返回脱敏依赖状态；不暴露 `H:\...`、内部盘符、完整命令行和 token。
- [ ] 限制产物下载、列表接口、同步触发和写入接口的权限与频率。
- [ ] 新域名先部署在独立路径，使用灰度账号访问；确认日志、监控、备份和告警后再切换。
- [ ] 域名和 HTTPS 到位后，只新增 DNS、证书、反向代理和 SSO 配置；不能改动 API 响应模型、同步逻辑和数据主键。
- [ ] 验收：未登录、跨项目、只读角色、写角色、管理员五类账号均通过权限测试；HTTPS、证书、反向代理和服务重启可重复执行。

---

## 12. Task 11：灰度、对账和切换

**目标：** 在不影响当前系统的前提下切换到新域名。

- [ ] 新系统以 shadow mode 运行，只读同步，不执行任何外部写入。
- [ ] 在域名和 HTTPS 未提供前，使用本机/开发机 URL 完成 shadow mode；域名切换只改变入口，不重新导入或重建数据。
- [ ] 对比旧系统和新系统的关键指标：日历行数、资产数、阶段数、Redmine 任务数、负责人数、逾期数、外观配置数。
- [ ] 对差异分类：数据时间差、字段映射差、过滤条件差、旧系统人工覆盖、真实错误。
- [ ] 连续至少两个完整同步周期无高优先级差异后，邀请业务用户验收四个页面。
- [ ] 先让少量用户使用新域名，旧域名保持只读和可回退。
- [ ] 切换前冻结写入规则，切换后继续保留旧系统快照和回退 DNS/反向代理配置。
- [ ] 验收：回滚只需要切换入口，不删除数据；新旧系统都能定位同一个资产、任务和产物。

---

## 13. 验证命令和交付标准

每个实现任务都必须在提交前运行最窄的验证，再运行全量验证：

```text
pytest tests/unit -q
pytest tests/contract -q
pytest tests/integration -q
pytest tests/security -q
npm run typecheck
npm run test:e2e
```

交付必须包含：

- OpenAPI 和数据字典。
- 新旧字段映射和数据来源矩阵。
- Redmine、工程扫描、产物存储的运行配置说明。
- 同步失败、数据过期、权限不足和外部系统不可用的处理方式。
- 部署、回滚、备份、日志和告警手册。
- 一份对账报告，证明核心数量和状态映射与现有系统一致。

## 建议实施顺序和时间边界

- 第 0 阶段：权限、来源和部署信息确认，约 0.5–1 天。
- 第 1 阶段：黑盒证据、契约和快照夹具，约 1–2 天。
- 第 2 阶段：只读 API、前端四页和本地快照，约 3–5 天。
- 第 3 阶段：Redmine 同步、工程扫描和产物存储，约 4–7 天。
- 第 4 阶段：历史分析、权限、写入和部署灰度，约 4–7 天。

因此，第一版只读 MVP 预计 5–8 个工作日；完整可写系统预计 10–17 个工作日，不包含等待 Redmine/P4 权限和部署审批的时间。

## 第一执行批次（不等待域名和 HTTPS）

真正开始编码前，只需要先完成以下 5 件事：

1. 确认使用 `127.0.0.1:5173` + `127.0.0.1:8000` 作为当前开发入口；域名和 HTTPS 延后到部署阶段。
2. 确认 Redmine 项目范围及只读访问方式；在权限未到位前先使用脱敏快照。
3. 提供服务端代码或部署目录；如果没有，确认走黑盒兼容路径。
4. 确认工程/P4/UE 目录的只读访问方式；在权限未到位前先使用工程夹具。
5. 确认第一版只做只读 MVP。

这五项确认后，先执行 Task 1 和 Task 1A，产出当前页面数据地图、来源契约和字段血缘；随后执行 Task 2 固化领域模型与 OpenAPI；契约通过后开始 Task 3 的本地 API/前端，不直接在未知链路上写外部同步或写回代码。
