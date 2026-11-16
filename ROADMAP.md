# ROADMAP.md — Arachne-OS 分阶段开发与内生双核验收路线图（加固版 v2.0）

本项目严格按 **Phase 0（前期筹划与架构加固）+ 5 大工程里程碑（Milestone 1~5）** 稳扎稳打推进。每个里程碑完成后必须跑通对应的 `pytest` 套件与红队关卡，实时勾选更新 `TASKS.md`。

## Phase 0：架构排雷与工程筹划 `[已完成 ✅]`
- [x] 完成五大工程暗礁排雷（子树隔离回滚封条、双层沙箱与归一化擂台、主旁路异步脉搏解耦、可插拔企微传输网关、物理级 RBAC 字段脱敏）。
- [x] 初始化 Git 仓库与前后端标准目录骨架，落盘 5 份加固版最高规范文档、`TASKS.md`、`.env.example` 与 Python 3.13 依赖清单。

## Milestone 1：钢铁底座 —— WORM 哈希链黑匣子、子树快照与三级模型路由网关 `[已完成 ✅]`
- [x] 初始化 `backend/.venv` 虚拟环境并安装依赖；实现 `config.py`、`database.py` 与 `core/schemas.py` 全局强类型数据模型。
- [x] 实现 `core/llm_gateway.py`：支持 `.env` 配置 DeepSeek / OpenAI 兼容接口（L1 本地正则脱敏 / L2 快速路由 / L3 深度推理），并内置高拟真确定性语义与代码合成回退引擎。
- [x] 实现 `core/blackbox_vault.py`：SHA-256 哈希链 Append-Only 账本、只读子树快照封存（`SNAPSHOT_SEALED`）、追加式回滚封条（`ROLLBACK_SEAL`）、历史黄金测试集读取与全链防篡改校验 `verify_chain_integrity()`。
- [x] 编写并通过 `tests/test_m1_vault_and_gateway.py`（验证无删改方法反射断言、单字节篡改定位断言、子树快照回读与 L1 脱敏断言）。

## Milestone 2：基本粒子 —— 权能小球、岗位单元容器、人机黑盒契约与种子沙盘 `[已完成 ✅]`
- [x] 实现 `core/particles.py`：四类权能小球（`DATA / SKILL / AUTHORITY / REDLINE`）自动打标、标签检索、容器访问控制锁与红线拦截触发器。
- [x] 实现 `core/containers.py` 与 `core/human_tool.py`：`UnitSlot` 容器管理、带 TTL 自动过期回收的跨岗借球（`borrowed_balls`）、A/B 双面反推简历库隔离更新、以及 `HumanBlackBoxTool`（最小输入裁剪器 `InputMinimizer` + 发票格式/金额强校验器 `OutputValidator`）。
- [x] 实现 `seed_demo/commerce_dept_seed.py`：注入【商务跟单与客户运营部】5 大典型角色、岗位容器、初始小球、工厂绝密底价红线球，并向 `BlackBoxVault` 预封存 12+ 条真实历史运费与折扣手工结算黄金样本。
- [x] 编写并通过 `tests/test_m2_particles_and_slots.py`。

## Milestone 3：活体蛛网 —— 主旁路异步脉搏、自适应裂变、不入网不认账与边缘审查哨所 `[已完成 ✅]`
- [x] 实现 `swarm/pulse_bus.py` 与 `swarm/spider_network.py`：`WorkTicket` 存算分离、门禁拦截（无依据追问）、横向标签共现聚类自动分面（`Aspect`）、纵向超限（`MAX_SPAN=5`）自动分裂插入 `RELAY_NODE`、闲置节点脱水休眠（`DEHYDRATED`）与秒级唤醒。
- [x] 实现 `swarm/edge_audit_relay.py`：回传链路隐私剥离与摘要浓缩、红线与前后矛盾核查、涉钱/赔偿/法务高压线强制挂起转交基层组长审批、以及**子树级局部倒退（`LOCAL_ROLLBACK`）**——仅重置异常子树而不污染正常兄弟分支与全局违规记录。
- [x] 编写并通过 `tests/test_m3_spider_and_relay.py`。

## Milestone 4：达尔文进化 —— 双层隔离沙箱、归一化影子擂台、反向算分与并发盲评董事会 `[已完成 ✅]`
- [x] 实现 `swarm/evolution_arena.py`：接收员工自然语言提效建议 → `ArtisanAgent` 生成标准 `execute_skill` 脚本 → `sandbox_ast_guard`（含双下划线魔术属性拦截）+ `python -I` 净空环境子进程超时沙箱 → 历史黄金集/冷启动基准回放 + `Decimal` 归一化比对 → `ACTIVE` 晋升上线与创新加分结算。
- [x] 实现 `swarm/scoring_engine.py` 与 `swarm/board_of_directors.py`：异步后台影子陪跑计算岗位 `replaceability_score`、员工反向博弈 `performance_score`、`PreferenceCalibrator` 领导偏好权重动态学习、以及铁三角 + 动态业务域董事 `asyncio.gather` 并发独立盲评与一票否决机制。
- [x] 编写并通过 `tests/test_m4_evolution_and_board.py`。

## Milestone 5：三体合一 —— 可插拔企微网关、物理脱敏 API 总线与 React Flow 全真控制台 `[已完成 ✅]`
- [x] 实现 `surfaces/wecom_gateway.py`（`LocalSimulatorAdapter` + `WeComBotWSAdapter` + `WeComWebhookCallbackAdapter`）与 `surfaces/api_routes.py`、`backend/main.py`（严格执行按角色物理剥离敏感字段的 RBAC 响应投影）。
- [x] 开发 `frontend/`（React 18 + TypeScript + TailwindCSS + `@xyflow/react`）：
  1. 顶部 5 角色一键切换台（普通跟单员小陈 / 基层组长老李 / 财务黑盒王姐 / 部门主管张经理 / 顶层老板林总）与哈希链实时校验灯；
  2. 左侧企微聊天主窗（`#1 业务副驾`、`#2 进化与风控官`、`#3 董事会内参`）+ 原生伴生右侧边栏（工位小球透视、微信私聊记录公私剥离导单、口述痛点造工具球、待办审批/黑盒开票卡）；
  3. 右侧千人千面蛛网管理大屏（React Flow 动态生长/垫层/脱水/回滚拓扑图、影子擂台成绩单、可替代分与绩效双榜、自适应董事会开会与师徒反转一键拍板）。
- [x] **终极红队审计与端到端实测**：全库静态黑名单扫描 0 命中，执行 `ANTI_LAZY_GATES.md` 全部 6 大业务关卡 + 5 大加固专项断言（14/14 pytest 全绿），前端 `tsc -b && vite build` 零报错通过。
