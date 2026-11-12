# ARCHITECTURE_SPEC.md — Arachne-OS 系统工程规格说明书（加固版 v2.0）

## 1. 技术栈选型（轻量化、零外部重运维依赖、兼容 Python 3.13 & Node 22）
- **后端**：Python 3.11+（本机实测 Python 3.13.2），`FastAPI`, `uvicorn`, `websockets`, `pydantic>=2.10`, `SQLAlchemy>=2.0` + `aiosqlite`（热业务状态库，支持子树级分区回滚）, 本地轻量向量与标签共现检索（`numpy` 余弦相似度 + 共现矩阵 + SQLite 持久化）, `openai>=1.50` SDK（统一模型路由网关）, `pytest` + `pytest-asyncio` + `httpx`。
- **前端（企微三体合一工作台 + 全真仿真器）**：`React 18` + `TypeScript` + `Vite` + `TailwindCSS` + `@xyflow/react`（React Flow 渲染实时生长/呼吸/裂变/垫层/脱水的蛛网拓扑与热力图）+ `lucide-react`。

## 2. 标准目录结构
```text
arachne-os/
├── AGENTS.md                     # 工程最高宪法与内生双核制衡规范
├── ARCHITECTURE_SPEC.md          # 全系统架构、数据模型与5大加固补丁规格书
├── PROTOCOLS_AND_PROMPTS.md      # 四大智能体推理契约、双层沙箱模具与前后端API/WS协议
├── ROADMAP.md                    # 五阶段开发与检查点路线图
├── ANTI_LAZY_GATES.md            # 零妥协质量红线与6+5自动化实测关卡
├── TASKS.md                      # 精细到文件与测试套件的实时任务看板
├── .env.example                  # 模型网关、沙箱限制与企微通道环境变量模板
├── .gitignore
├── backend/
│   ├── requirements.txt          # Python 依赖锁文件（配合 backend/.venv 使用）
│   ├── main.py                   # FastAPI 入口 + 生命周期管理 + WebSocket 实时脉搏总线
│   ├── config.py                 # 环境配置加载与全局阈值（MAX_SPAN, 擂台阈值, 脱水TTL等）
│   ├── database.py               # SQLAlchemy AsyncEngine + 子树分区状态管理
│   ├── core/
│   │   ├── schemas.py            # 全局 Pydantic V2 核心数据契约与按角色裁剪的投影视图模型
│   │   ├── llm_gateway.py        # L1正则脱敏 / L2轻量模型 / L3深度推理 路由网关（含离线高拟真回退）
│   │   ├── blackbox_vault.py     # WORM 只追写 SHA-256 哈希链账本 + 子树快照封存 + ROLLBACK_SEAL
│   │   ├── particles.py          # 四类权能小球自动打标、检索与容器级权限/红线拦截器
│   │   ├── containers.py         # 标准单元容器(UnitSlot)、TTL临时借球、双面反推简历库(A/B面隔离)
│   │   └── human_tool.py         # 人即黑盒 API 封装器（InputMinimizer 裁剪 + OutputValidator 强验）
│   ├── swarm/
│   │   ├── pulse_bus.py          # 异步事件脉搏总线（主链路与后台陪跑/聚类/算分异步解耦 + WS广播）
│   │   ├── spider_network.py     # WorkTicket 存算分离、门禁拦截、横向共现聚类分面、纵向超限垫层、脱水唤醒
│   │   ├── edge_audit_relay.py   # 偏远边缘审查哨所：回传脱敏浓缩、矛盾与红线核查、子树级局部倒退(Local Rollback)
│   │   ├── evolution_arena.py    # 自我进化中心：工匠造球 + AST/子进程双层沙箱 + 归一化影子擂台 + 冷启动基准
│   │   ├── scoring_engine.py     # 后台静默影子陪跑 + 岗位AI可替代分 + 反向创新绩效分 + 领导偏好动态校准器
│   │   └── board_of_directors.py # 顶层自适应董事会（铁三角独立并发盲评 + 动态业务域董事席位 + 一票否决制）
│   ├── surfaces/
│   │   ├── wecom_gateway.py      # 可插拔企微网关（LocalSimulatorAdapter + WeComBotWSAdapter + Webhook预留）
│   │   └── api_routes.py         # REST & WebSocket 接口层（内置物理级 RBAC 角色字段剥离器）
│   ├── seed_demo/
│   │   └── commerce_dept_seed.py # 【商务跟单与客户运营部】人事、容器、小球、红线底价与12+条历史黄金流水种子
│   └── tests/                    # 全套单元、集成与红队安全回归测试
├── sandbox_workspace/            # 物理隔离的 AI 自造 Python 技能球运行沙箱目录
├── vault_storage/                # Append-Only 哈希链账本(ledger.jsonl)与只读快照物理目录(snapshots/)
└── frontend/                     # React + TS + Tailwind + React Flow 单屏双区三体合一控制台
```

---

## 3. 核心数据模型与五大加固机制规范

### 3.1 权能小球（`CapabilityBall`）
探索蜘蛛消化原始聊天、文档、表格或工匠锻造后生成的最小原子颗粒：
- `ball_id`: `str`（如 `BALL_DATA_STOCK_A`、`BALL_REDLINE_FLOOR_PRICE`、`BALL_SKILL_FREIGHT_V1`）
- `ball_type`: `Literal["DATA", "SKILL", "AUTHORITY", "REDLINE"]`
  - `DATA`（资料球）：产品目录、公开报价表、常规库存表、客户档案、脱敏历史上下文引用；
  - `SKILL`（技能球）：标准 SOP 模板，或挂载在 `sandbox_workspace/` 下通过影子擂台认证的可执行 Python 脚本；
  - `AUTHORITY`（权力球）：折扣审批额度（如基层组长 85 折内审批权）、跨节点派单权；
  - `REDLINE`（红线球）：绝密工厂拿货底价隔离墙、客户隐私脱敏规则、涉钱/赔偿/法务高压线触发器。
- `title`: `str`
- `domain_tags`: `list[str]`（用于横向共现矩阵聚类，如 `["报价", "折扣"]`、`["物流", "运费"]`、`["财务", "开票"]`）
- `sensitivity_level`: `int`（`1~5`，`5` 为绝密红线级）
- `owner_slot_ids`: `list[str]`（允许访问该小球的容器白名单）
- `executable_code_path`: `Optional[str]`（仅 `SKILL` 脚本球持有，指向沙箱内受检脚本）
- `version`: `int` & `status`: `Literal["CANDIDATE", "ACTIVE", "DEPRECATED"]`

### 3.2 标准单元容器（`UnitSlot`）与双面反推简历库（`DualEmployeeProfile`）
- **岗位单元容器（`UnitSlot`）**：
  - `slot_id`: `str`（如 `SLOT_FOLLOWUP_01` 跟单岗、`SLOT_LEADER_01` 基层组长岗、`SLOT_FINANCE_BOX` 财务开票黑盒岗）
  - `ball_ids`: `list[str]`（永久驻留该岗位的权能小球集合）
  - `borrowed_balls`: `list[BorrowedBallLease]`（跨岗支援临时借球：`{ball_id, from_slot, borrowed_at, expires_at}`，访问时自动校验惰性过期回收）
  - `occupant_type`: `Literal["HUMAN", "HYBRID_TRANSITION", "AGENT"]`
    - `HYBRID_TRANSITION`（师徒反转过渡期）：由 AI Agent 主导生成业务输出，原岗位真人仅做异常抽检签字；
  - `occupant_id`: `str`（当前驻守员工 ID 或 Agent ID）
  - `replaceability_score`: `float`（`0.0 ~ 100.0`，**机密管理指标，严禁下发给 `employee` 角色接口**）

- **双面反推简历库（`DualEmployeeProfile`）**：
  - `employee_view`（A 面公开给本人）：`skill_tags`（能力成长标签）、`saved_hours`（累计由 AI 提效节省工时）、`evolution_contributions`（口述痛点孵化上线的新技能球列表）、`innovation_bonus`（进化架构师累计加分）。
  - `management_view`（B 面仅主管/老板可见）：`avg_latency_ms`、`rework_rate`（被黑盒校验或哨所驳回重做率）、`boundary_probes`（越界刺探无权限底价/机密球次数，**不受业务回滚抹除**）、`performance_score`（反向博弈综合绩效分）。

### 3.3 【加固补丁 1】WORM 黑匣子与子树分区回滚一致性协议（`BlackBoxVault` + Subtree State）
为彻底消除“JSONL 只追写账本”与“SQLite 热业务库”在局部回滚时的状态撕裂：
1. **严格只追写账本（`vault_storage/ledger.jsonl`）**：
   - 每行记录包含 `seq`, `timestamp`, `event_kind`, `subtree_root_id`, `actor_slot_id`, `payload`, `prev_hash`, `record_hash`（基于 `sort_keys=True` 规范化 JSON 的 SHA-256）。
   - `BlackBoxVault` 类仅允许 `append_event`、`seal_snapshot`、`read_snapshot`、`list_golden_benchmarks`、`verify_chain_integrity`，物理上无任何删除或覆写方法。
2. **子树分区快照与追加式回滚封条（`ROLLBACK_SEAL`）**：
   - 蛛网中每个业务域分支（如询价分支 `subtree_quote`、履约发货分支 `subtree_fulfill`）在每次合法里程碑节点自动封存子树状态快照（`SNAPSHOT_SEALED`，存储于 `vault_storage/snapshots/{snapshot_hash}.json`，文件设为只读权限 `0o444`）。
   - 当边缘审查哨所触发 `LOCAL_ROLLBACK` 时：
     - **Step 1（账本留痕不断链）**：向 `ledger.jsonl` 追加一条 `ROLLBACK_SEAL` 事件，指向该子树最近一次合法 `target_snapshot_hash`；
     - **Step 2（热库按子树精准外科手术）**：SQLite 事务仅筛选 `subtree_root_id == target_subtree_id` 的活跃 `WorkTicket`、节点局部缓冲与临时借球状态，将其原子恢复至快照状态；其他兄弟子树的进行中工单与全局审计违规计数 **100% 零干扰**。

### 3.4 【加固补丁 2】活体蛛网、主旁路异步解耦与偏远边缘审查哨所
- **主旁路双通道架构（`PulseBus`）**：
  - **同步主通道**：接收消息 → L1 正则硬脱敏（剥离私人闲聊/手机号/身份证/银行卡）→ 容器红线球拦截 → L2 `ExplorerSpider` 门禁判定（`Gatekeeper` 不入网不认账挂起 / 高压线涉钱涉赔偿转交基层组长 / 正常回复）→ 立即返回前端聊天窗。
  - **异步旁路脉搏（`asyncio.create_task`）**：后台执行小球落库、标签共现矩阵更新与横向自动分面（新簇内聚度达标即分裂新业务域 `AspectNode` 并通知董事会增设领域董事）、纵向超限自动垫层（单父节点活跃子流 `> MAX_SPAN=5` 时自动插入 `RELAY_NODE` 审查哨所）、后台影子陪跑试做算分、闲置节点脱水休眠（`DEHYDRATED`），全过程通过 `ws://localhost:8000/ws/events` 实时广播动画事件。
- **边缘审查哨所（`EdgeAuditRelay`）**：
  - 所有 `RELAY_NODE` 对下属节点回传负载强制执行 `relay_inspect(payload)`：
    1. **回传途中脱敏浓缩**：剔除底层啰嗦过程与残余敏感词，提炼结构化结论供高层消费；
    2. **红线与逻辑矛盾核验**：检测前后金额不一致、幻觉承诺或越权底价泄露；
    3. **三级裁决**：`PASS`（放行）| `ESCALATE_SUPERVISOR`（涉钱/赔偿/法务高压线转交组长审批卡）| `LOCAL_ROLLBACK`（子节点异常/幻觉，立即触发子树级局部回滚）。

### 3.5 【加固补丁 3】双层隔离沙箱、归一化影子擂台与冷启动基准（`EvolutionArena`）
1. **代码锻造模具**：`ArtisanAgent` 仅生成标准签名的 `def execute_skill(payload: dict) -> dict` 纯函数。
2. **双层安全防线**：
   - **L1 静态 AST 守卫（`sandbox_ast_guard`）**：仅放行白名单标准库（`math`, `json`, `re`, `datetime`, `decimal`, `collections`, `statistics`）；拦截 `eval/exec/open/compile/__import__/getattr/setattr/globals/locals` 及任何非 `__init__` 的双下划线魔术属性访问（彻底封死 Python 对象链逃逸）。
   - **L2 净室子进程执行**：在 `sandbox_workspace/` 下以 `python -I` 隔离标志 + 净空环境变量（`env={"LC_ALL": "C.UTF-8"}`）运行，超时阈值 `3.0s`。
3. **双源基准与归一化断言（解决冷启动与格式误杀）**：
   - **历史黄金集**：`commerce_dept_seed.py` 预封存 12+ 条真实历史手工核算样本（含阶梯运费首重、续重、满 500 免运费边界等）至 `BlackBoxVault`；
   - **冷启动合成集**：若全新品类在 Vault 中历史样本 `< 5` 条，自动调用 L3 生成 6 组含边界条件的基准样本并在战报标记 `SYNTHETIC_COLD_START`；
   - **数值归一化比对器（`NormalizedResultComparator`）**：自动剥离 `"元"`、`"¥"`、`"RMB"` 等单位符号并统一转换为 `Decimal`（精度容差 `±0.01`），当 `执行成功率 == 100%` 且 `归一化吻合率 >= 98%` 时晋升为 `ACTIVE` 技能球，并立即为提议员工结算高额 **进化架构师创新加分**！

### 3.6 量化算分体系与顶层自适应董事会（`ScoringEngine` & `BoardOfDirectors`）
1. **岗位【AI 可替代分】（`replaceability_score`: `0~100`）**：
   $$\text{Replaceability} = \text{clamp}_{[0,100]}\big(0.4 \times \text{RuleRepetitionRatio} + 0.6 \times \text{ShadowAgreementRate}\big)$$
2. **员工【反向创新综合绩效分】（`performance_score`: `0~100`）**：
   $$\text{Performance} = \text{clamp}_{[0,100]}\big(\text{BaseFulfillment} - \alpha \cdot \text{Replaceability} + \text{EvolutionArchitectBonus} - \beta \cdot \text{BoundaryProbes}\big)$$
   （默认机械依赖惩罚系数 $\alpha = 0.35$，单次越界试探扣分 $\beta = 8.0$，成功孵化上线 1 颗通过擂台的技能球奖励 $+18.0$ 分）。
3. **领导偏好动态磨合器（`PreferenceCalibrator`）**：
   维护四维权重向量 `[speed, zero_error, cost_saving, automation_aggressiveness]`（初始各 `0.25` 并保持和为 `1.0`），每次管理层批准/驳回提案时按反馈方向自适应更新权重并持久化。
4. **顶层自适应董事会（`BoardOfDirectors`）**：
   - **永恒铁三角**：`SecurityDirector`（安全红线官，拥有 `VETO` 一票否决权）、`EvolutionDirector`（进化效率官）、`CostDirector`（算力成本官）；
   - **动态业务域席位**：随蛛网横向聚类出的业务域（如【询价签约域】、【物流履约域】、【财税结算域】）自动增设 `DomainDirector`；
   - **并发独立盲评**：通过 `asyncio.gather` 并发独立发起各董事推理（严禁单次 Prompt 扮演多人），汇总加权得分呈报老板拍板是否将高可替代分岗位（`>= 90`）切换为 `HYBRID_TRANSITION`（师徒反转过渡期）。

### 3.7 【加固补丁 4】企微三体合一交互层与可插拔传输适配器（`WeComTransportAdapter`）
- **后端适配器抽象**：`wecom_gateway.py` 提供 `LocalSimulatorAdapter`（默认开箱即用，支持单聊/群聊、外部微信聊天记录转发导入、交互式审批卡片、伴生侧边栏联动）、`WeComBotWSAdapter`（企微智能机器人长连接）与 `WeComWebhookCallbackAdapter`（标准回调预留）。
- **前端单屏双区五视角演练台**：
  - 顶部全局栏：**5 种角色一键切换**（`普通跟单员-小陈` / `基层组长-老李` / `财务专员-王姐[黑盒节点]` / `部门中层主管-张经理` / `公司顶层老板-林总`）+ WebSocket 脉搏状态灯 + 账本哈希链健康徽章。
  - 左侧区域：**企微聊天主窗**（3 大门面智能体：`#1 业务副驾`、`#2 进化与风控官`、`#3 董事会内参`）+ **紧贴右侧的原生伴生边栏**（当前工位权能小球透视、一键导入微信私聊记录公私剥离建单、自然语言口述痛点造工具球赚绩效、待办黑盒/高压线卡片）。
  - 右侧区域：**企业微信工作台千人千面蛛网管理大屏**（依角色权限严格渲染：普通员工仅见个人 A 面成长卡与公开 SOP；主管与老板可见 React Flow 实时动态拓扑图、节点垫层/分裂/脱水动画、边缘哨所局部回滚演练台、影子擂台实时战报、岗位 AI 可替代分与员工绩效双榜、自适应董事会开会与师徒反转拍板台）。
