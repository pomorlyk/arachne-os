# Arachne-OS 生产级全面升级与结构去耦合专项任务书（新对话交接执行版）

> **用途**：本任务书面向下一阶段全新开发对话，针对 **Arachne-OS** 在“深圳嘉立创科技集团股份有限公司（JLCPCB）”实测与源码深度审计中暴露出的全部遗留短板（状态重启易失、二线高阶模块仍含家具厂硬编码、外部系统真连接器缺失、前端缺少离职/替班交接 UI 与节点级联热唤醒、动态董事会席位膨胀、软技能评分粗糙及沙箱 OS 级资源隔离不足），提供按优先级排期的精确改造蓝图与验收标准。

---

## 一、开场即用：给新对话的复制指令（Copy-Paste Kickoff Prompt）

在新对话中直接复制以下内容即可启动：

```text
请先完整阅读 /Users/Apple/Desktop/公司/arachne-os/PRODUCTION_UPGRADE_TASK_SPEC.md，严格按照其中的七大专项任务清单（P0 -> P1 -> P2 分阶段）与验收标准开展工程改造。
环境约定：
- 后端 Python / Pytest 使用 /tmp/arachne-venv/bin/python 与 /tmp/arachne-venv/bin/pytest
- 前端目录在 /Users/Apple/Desktop/公司/arachne-os/frontend
- 每完成一个 Phase 后立刻运行后端 pytest 与前端 npm run build 校验，最后在真机 8000/5173 端口用非家具厂的真实企业验证并汇报。
```

---

## 二、当前已验证基线与环境约束

1. **项目路径**：`/Users/Apple/Desktop/公司/arachne-os`
   - 后端目录：`/Users/Apple/Desktop/公司/arachne-os/backend`（Python 虚拟环境：`/tmp/arachne-venv`）
   - 前端目录：`/Users/Apple/Desktop/公司/arachne-os/frontend`（React + Vite）
   - 热态 SQLite：`/Users/Apple/Desktop/公司/arachne-os/backend/arachne_hot_state.db`
   - WORM 不可篡改审计账本：`backend/vault_storage/`
2. **已完成前置基础（不要破坏）**：
   - `M16` 矿洞空壳冷启动 → 组织探路（`SCOUTED`）→ 逐岗点亮（`FULLY_LIT`）→ `Live DeepSeek` 编译沙箱算子。
   - **深圳嘉立创**六维实测与 49 项后端自动化测试（`/tmp/arachne-venv/bin/pytest -q` -> `49 passed`）已全绿通过；[auth_custody.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/auth_custody.py)、[auth_custody_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/auth_custody_routes.py)、[spider_network.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/spider_network.py)、[board_of_directors.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/board_of_directors.py) 已完成第一轮探网主流程适配。

---

## 三、七大专项改造任务清单（按优先级 P0 → P1 → P2）

### Task 1 [P0]：全量运行时状态持久化（解决重启后探网企业与岗位资产丢失问题）

* **当前核心痛点**：
  * 目前 `database.py`（`HotStateStore`）只持久化了 `spider_nodes`、`work_tickets`、`borrowed_leases` 与 `immutable_audit_counters` 4 张表。
  * **但关键的内存注册表未入库**：`ContainerRegistry`（`UnitSlot` 槽位与 `DualEmployeeProfile` 员工档案）、`ParticleRegistry`（`CapabilityBall` 权能球与动态合成的技能源码）、`AuthAndCustodyService`（动态生成的 `ACCOUNT_DIRECTORY`、`BallRequest` 审批单、会话 Token）以及 `CaveExplorer` 的企业探网元信息全部仅驻留在进程内存中。
  * 结果：后端服务（`uvicorn`）一旦重启，`create_arachne_runtime()` 又重新加载默认家具厂 `commerce_dept_seed`，刚才通过矿洞探网接入的“深圳嘉立创”及其自进化技能球、交接状态会瞬间与 `arachne_hot_state.db` 产生“数据库有节点、内存却回到家具厂”的精神分裂。
* **改造目标与涉及文件**：
  * [database.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/database.py)
  * [containers.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/containers.py)
  * [particles.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/particles.py)
  * [auth_custody.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/auth_custody.py)
  * [cave_explorer.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/cave_explorer.py)
  * [api_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/api_routes.py)（`create_arachne_runtime`）
* **具体要求**：
  1. 在 `database.py` 新增 ORM 持久化表：`unit_slots`、`employee_profiles`、`capability_balls`、`account_directory_entries`、`custody_requests`、`workspace_state_meta`（记录当前激活企业名称、探网模式 `DEMO_SEED / EMPTY_SHELL / EXPLORING / FULLY_LIT`）。
  2. 为 `ContainerRegistry`、`ParticleRegistry`、`AuthAndCustodyService`、`CaveExplorer` 提供异步/同步双写或写穿（write-through）落盘能力（凡调用 `empty-shell`、`scout`、`plant-torch`、`evolution/propose`、`custody/handover`、`custody/requests/*/decide`、`board/approve-transition` 等变更接口时同步持久化）。
  3. 改造 `create_arachne_runtime()` 启动逻辑：若 `arachne_hot_state.db` 中已有 `workspace_state_meta` 与非空 `unit_slots / capability_balls`，**自动从 SQLite 无损恢复上次的真实企业拓扑、自进化技能球与员工交接状态**；仅在数据库首次为空（或显式调用重置接口）时加载家具厂演示种子。
  4. 新增 `test_restart_persistence_across_app_recreation` 自动化测试：连续点亮新企业 → 铸造技能球 → 执行 `RESIGN_HANDOVER` → 重建全新 FastAPI `app` 实例 → 验证新企业、新员工登录、继承权能球与红线拦截均完好无损。

---

### Task 2 [P0]：二线高阶模块与前端“家具厂样板间硬编码”彻底清零

* **当前核心痛点**：
  * 全库静态扫描发现，除了主聊天与基础探网外，大量高阶模块和前端模拟器仍硬编码了家具厂 ID 与文案（命中分布：`dag_mission_engine.py` 38 处、`day_simulator.py` 21 处、`api_routes.py` 14 处、`enterprise_ingestor.py` 10 处、`skill_pipeline_composer.py` 9 处、`WeComSimulatorPane.tsx` 9 处、`monte_carlo_wargame.py` 8 处、`genesis_fission.py` 6 处，以及各路由默认值 `SLOT_FOLLOWUP_01`、`SLOT_LEADER_01`、`SLOT_FINANCE_BOX`、`emp_chen`、`BALL_AUTH_LEADER_HV_GATE`、`BALL_REDLINE_FACTORY_FLOOR_PRICE`、“人体工学椅”、底价 `480` 等）。
* **改造目标与涉及文件**：
  * 后端核心引擎：[dag_mission_engine.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/dag_mission_engine.py)、[day_simulator.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/day_simulator.py)、[skill_pipeline_composer.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/skill_pipeline_composer.py)、[monte_carlo_wargame.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/monte_carlo_wargame.py)、[genesis_fission.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/genesis_fission.py)、[red_blue_crucible.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/red_blue_crucible.py)、[scoring_engine.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/scoring_engine.py)、[cross_dept_router.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/cross_dept_router.py)、[enterprise_ingestor.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/enterprise_ingestor.py)。
  * 后端路由与网关：[api_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/api_routes.py)、[dag_mission_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/dag_mission_routes.py)、[lifecycle_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/lifecycle_routes.py)、[memory_distiller_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/memory_distiller_routes.py)、[skill_pipeline_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/skill_pipeline_routes.py)、[wecom_gateway.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/wecom_gateway.py)。
  * 前端组件：[WeComSimulatorPane.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/WeComSimulatorPane.tsx)、[LoginGateView.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/LoginGateView.tsx)、[SpiderTopologyFlow.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/SpiderTopologyFlow.tsx)、[SwarmWarRoomModal.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/SwarmWarRoomModal.tsx)、[RedBlueCrucibleModal.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/RedBlueCrucibleModal.tsx)、[AutonomousCommandStudioModal.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/AutonomousCommandStudioModal.tsx)、[EnterpriseIngestSnapshotModal.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/EnterpriseIngestSnapshotModal.tsx)、[api.ts](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/api.ts)。
* **具体要求**：
  1. **DAG 会战通用化（`dag_mission_engine.py`）**：
     * `get_mission_presets()` 与 `consensus_resolution` 严禁返回写死的“人体工学椅 / 480 元底价 / `BALL_AUTH_LEADER_HV_GATE`”；改由当前 `ContainerRegistry` + `ParticleRegistry` 动态抽取：取当前一线 `employee` 岗位的默认技能球、当前红线球 `REDLINE`、以及实际审批权球，并依据当前企业部门自动生成行业贴合的预设会战剧本。
     * `recommended_lease_grant`、`summary` 与 `approved_conditions` 必须引用当前实际命中的 `slot_id` 与 `ball_id`（不得假定必定存在华东仓调拨或固定 `30% -> 55%` 首付文案）。
  2. **高阶模拟与编排路由动态化（`day_simulator.py`、`monte_carlo_wargame.py`、`skill_pipeline_composer.py`、`genesis_fission.py`、`cross_dept_router.py`）**：
     * 所有 `default` 参数（如 `target_slot_id`、`proposer_slot_id`、`reviewer_slot_id`、`user_id`）全部改为 `Optional[str] = None`，运行期通过共享的拓扑解析辅助函数动态挑选当前企业的活跃岗位/红线球/账号。
     * `skill_pipeline_composer.py` 禁止在 fallback 计算中写死 `480.0`，改从当前槽位挂载的 `DATA / SKILL` 参数或请求上下文读取。
     * `day_simulator.py` 与 `monte_carlo_wargame.py` 根据当前企业实时探网生成的岗位与技能球，动态构造压测情景与异常探针，确保在任意新企业上均可零报错一键跑完“全天模拟”和“蒙特卡洛兵棋推演”。
  3. **前端默认选中与快捷示例完全动态化**：
     * 各 Modal（战争室、红蓝对抗、自治司令部、企业快照、拓扑图）不再写死默认选 `SLOT_FOLLOWUP_01 / emp_chen`，而是从 `/api/v1/auth/accounts` 或 `overview` 返回的真实列表自动选择首个对应角色槽位。
     * `WeComSimulatorPane.tsx` 彻底消除基于“是否含人体工学椅”的二分法，改为依据当前岗位挂载的 `accessible_balls` 自动生成适配该岗位技能与红线的快捷测试话术。

---

### Task 3 [P1]：真实外部系统连接器抽象与异步回调闭环（ERP / 金税 / 企微 Webhook）

* **当前核心痛点**：
  * 目前 `BLACKBOX_HUMAN`（如开具数电专票）与外部通知主要在本地工作台闭合（人工提交表单），`WeCom` 在无外网凭据时也仅停留在本地模拟流；缺乏标准的生产级连接器协议，导致无法直接接入真实 ERP、WMS 锁库、税控系统或第三方审批流。
* **改造目标与涉及文件**：
  * 新建 `backend/core/external_connectors.py`
  * 改造 [human_tool.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/human_tool.py)、[wecom_gateway.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/wecom_gateway.py)、[api_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/api_routes.py)、[config.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/config.py)
* **具体要求**：
  1. 定义统一连接器接口 `BaseExternalConnector` 及三种内置实现：
     * `LocalWorkbenchConnector`（兼容现有零配置演示工作台）
     * `HttpWebhookConnector`（面向真实 ERP / WMS / 金税接口：发出含 `minimized_payload` 与幂等 `idempotency_key` 的签名请求 `X-Arachne-Signature` HMAC-SHA256，支持指数退避重试）
     * `WeComGroupBotConnector`（打通企微群 Webhook 卡片推送与 `@` 提醒）
  2. 支持在 `ArachneSettings` 或企业岗位元数据中按槽位绑定连接器（例如 `BLACKBOX_HUMAN` 税务槽位可配置为异步 HTTP Webhook 模式）。
  3. 新增入站签名回调端点 `POST /api/v1/connectors/callback/{card_id}`：校验 HMAC 签名与幂等性后，自动完成对应 `HumanToolCard` 回填、触发上游工单收口并写入 WORM 加密账本。
  4. 补充单元测试覆盖：HMAC 签名校验拒绝篡改请求（`401/403`）、合法回调自动推进工作流至 `COMPLETED`。

---

### Task 4 [P1]：前端补齐“岗人分离交接/替班控制台” + 蜂群级联热唤醒可视化

* **当前核心痛点**：
  1. 后端虽已上线 `POST /api/v1/custody/handover`（支持 `LEAVE_DELEGATION` 休假代班与 `RESIGN_HANDOVER` 离职交接），但前端尚无操作界面，用户只能在界面上借用单个球，无法可视化完成“一键换人不丢球”。
  2. 蜂群在触发 `DEHYDRATE_IDLE` 后，虽然对单节点聊天可重新响应，但在跨部门协同/DAG 会战/领导审批流经处于 `DEHYDRATED` 状态的下游节点时，**缺少统一的自动级联热唤醒（Cascade Rehydration）机制与拓扑状态可视化区分**。
* **改造目标与涉及文件**：
  * 前端：[api.ts](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/api.ts)、[BallCustodyPanel.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/BallCustodyPanel.tsx)、[CapabilityCenterView.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/CapabilityCenterView.tsx)、[ExecutiveControlDeck.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/ExecutiveControlDeck.tsx)、[SpiderTopologyFlow.tsx](file:///Users/Apple/Desktop/公司/arachne-os/frontend/src/components/SpiderTopologyFlow.tsx)
  * 后端：[spider_network.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/spider_network.py)、[dag_mission_engine.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/dag_mission_engine.py)、[api_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/api_routes.py)
* **具体要求**：
  1. 在管理端（`ExecutiveControlDeck.tsx` / `BallCustodyPanel.tsx`）新增**「岗位交接与离职代班」弹窗/抽屉**：选择目标岗位槽位、填写或选择接班人 ID 与姓名、选择模式（`LEAVE_DELEGATION` / `RESIGN_HANDOVER`）与交接说明，调用 `POST /api/v1/custody/handover`，成功后刷新账号目录与拓扑展示（并即时展示继承的权能球列表与旧人隔离态）。
  2. 后端增加统一的 `rehydrate_slot_nodes(slot_ids)` 服务方法：在工单路由、人工工具卡派发、DAG 会战规划或跨岗借球涉及某个 `DEHYDRATED` 节点时，自动将其状态恢复为 `ACTIVE`、更新 `last_active_at` 并向 `PulseBus` 发布 `NODE_REHYDRATED` 脉冲事件。
  3. 在 `SpiderTopologyFlow.tsx` 中明确区分渲染 `ACTIVE`（高亮活跃）、`DEHYDRATED`（半透明休眠/冰晶标识）与 `HYBRID_TRANSITION`（师徒反转金边徽章），并提供一键“脱水/热唤醒”可视化交互。

---

### Task 5 [P1]：董事会动态席位上限收敛（≤ 7 席）与真实指标驱动的差异化盲评

* **当前核心痛点**：
  * 在嘉立创实测中，由于企业既有 4 个部门又有细分标签切面，`BoardOfDirectors.convene` 生成了 **14 席**董事（3 席铁三角 + 11 席动态领域董事），且全部 11 席动态领域董事给出了**完全一致的 `90.8` 分与一模一样的模板评价**，失去“独立异构盲评”的实质意义，也导致 Live 场景下 LLM 并发成本线性膨胀。
* **改造目标与涉及文件**：
  * [board_of_directors.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/board_of_directors.py)
  * [llm_gateway.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/llm_gateway.py)
* **具体要求**：
  1. **席位收敛策略**：固定 `3` 席铁三角（安全官 / 进化效率官 / 算力成本官）+ 最多 `4` 席主部门代表董事（总席位严格封顶 **`7` 席**）。筛选逻辑优先选取与目标岗位所在子树有真实协作连线（`cross_links`）或工单往来的顶层 `ASPECT_NODE` 主部门，过滤细碎标签衍生节点。
  2. **差异化上下文注入**：向每位部门代表董事注入该部门真实观测指标（部门积压工单数、跨部门红线拦截次数、局部回滚次数、是否含 `BLACKBOX_HUMAN` 合规敏感岗），使不同部门在确定性兜底与 Live LLM 模式下都能给出贴合自身视角的差异化评分与理由（严禁千篇一律固定打 `90.8`）。

---

### Task 6 [P2]：软技能主观边界三维校准评分 + 长期记忆蒸馏闭环验证

* **当前核心痛点**：
  * 当前 `ScoringEngine` 偏重数值可计算岗位与影子试炼累计分，缺乏“AI 草稿 vs 人类最终改写采纳率”的真实编辑距离指标，也缺少对高主观协商/客诉安抚类岗位的替代上限保护。
  * 记忆蒸馏器路由（[memory_distiller_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/memory_distiller_routes.py)）需确保在非家具厂的任意新探网企业中，积累多笔真实工单后能自动沉淀隐性经验为待审 `DATA` 权能球。
* **改造目标与涉及文件**：
  * [scoring_engine.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/scoring_engine.py)
  * [memory_distiller_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/memory_distiller_routes.py)（及其关联 distiller 模块）
  * [containers.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/core/containers.py)
* **具体要求**：
  1. 升级 `ScoringEngine` 的 `replaceability_score` 为三维可解释分解模型：
     * `skill_coverage`（可执行技能球覆盖率）
     * `shadow_adoption_rate`（影子草稿被真人低改动直接采纳的比率，支持记录 `human_final_text` 与 `ai_draft_text` 的相似度）
     * `exception_discipline_factor`（异常升级率/红线合规稳定性；对高主观协商类槽位设置安全人工兜底系数上限，不盲目推到 100 分）。
  2. 打通长周期记忆蒸馏在任意新企业槽位上的端到端闭环，并增加对应测试验证非家具厂槽位（如 `SLOT_CAVE_EMP_*`）可成功蒸馏出新 `DATA` 权能球并提交负责人审核挂载。

---

### Task 7 [P2]：净室子进程沙箱操作系统级资源限制与系统健康自检端点

* **当前核心痛点**：
  * [evolution_arena.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/evolution_arena.py) 中的 `_SUBPROCESS_RUNNER_HARNESS` 目前依赖 AST 白名单与 `timeout` 控制，但缺少进程内 OS 级资源限额（如递归爆栈、海量内存分配或超大标准输出泛洪）。
* **改造目标与涉及文件**：
  * [evolution_arena.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/swarm/evolution_arena.py)
  * [config.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/config.py)
  * [api_routes.py](file:///Users/Apple/Desktop/公司/arachne-os/backend/surfaces/api_routes.py)
* **具体要求**：
  1. 在 `_SUBPROCESS_RUNNER_HARNESS` 执行目标函数前加装 `resource.setrlimit` 防护（CPU 时间限制、堆/地址空间上限，兼容 macOS 与 Linux 环境差异并对输出体积做硬截断），并新增一条“内存炸弹/死循环恶意技能球”单元测试验证能在 `sandbox_timeout_seconds` 内安全阻断且不影响主进程。
  2. 新增 `GET /api/v1/system/health` 接口，一次性汇报：SQLite 持久化模式与当前活跃企业名称、WORM SHA-256 账本完整性、Live LLM 就绪状态与模型名、以及已注册外部连接器状态。

---

## 四、推荐分阶段执行路线图

1. **Phase 1（地基重构，必须最先完成）**：`Task 1`（全量 SQLite 持久化与重启无损恢复） → `Task 2`（彻底清理二线模块与前端的家具厂硬编码）。
   * *Phase 1 检查点*：重启后端服务不丢新探网企业；全库搜索关键词（除 `backend/seed_demo/` 与 `backend/tests/test_m1..m15` 旧演示测试外）生产代码 `backend/core/`、`backend/swarm/`、`backend/surfaces/`、`frontend/src/` 中的家具厂业务逻辑硬编码清零。
2. **Phase 2（治理体验闭环）**：`Task 4`（前端离职/替班交接 UI + 级联热唤醒与拓扑徽章） → `Task 5`（董事会 ≤ 7 席收敛与差异化盲评）。
3. **Phase 3（生产对接与安全加固）**：`Task 3`（外部连接器与 HMAC 回调） → `Task 6`（三维可替代分与跨企业记忆蒸馏） → `Task 7`（沙箱 OS `rlimit` 加固与 `/api/v1/system/health`）。

---

## 五、总验收标准（Definition of Done）

全部任务完成后，必须同时满足以下客观标准并给出实测命令与输出：

1. **后端自动化测试**：`/tmp/arachne-venv/bin/pytest -q` 全部通过（原 `49` 项 + 新增持久化重启、连接器签名回调、级联热唤醒、董事会 ≤7 席、沙箱资源炸弹拦截测试，0 失败、0 跳过）。
2. **静态洁净度校验**：在 `backend/core/`、`backend/swarm/`、`backend/surfaces/`、`frontend/src/` 内检索 `人体工学椅`、`480`（非 480 分钟时长常量）等家具业务硬编码残留为 `0`（或仅留存在 `seed_demo` 兼容层）。
3. **前端编译校验**：`cd /Users/Apple/Desktop/公司/arachne-os/frontend && npm run build` 零 TypeScript / Vite 编译错误。
4. **全新企业端到端实测**：使用完全不同于家具厂的新企业（如医院供应链、SaaS 客服或嘉立创），在真机 `8000 / 5173` 服务上跑通：**探网点亮 → 杀掉并重启 uvicorn → 状态无损恢复 → 跨部门 DAG → 级联热唤醒 → 外部回调闭环 → 前端 UI 岗位交接 → ≤7 席差异化董事会批准 `HYBRID_TRANSITION`**。

