# TASKS.md — Arachne-OS 实时作战进度看板

> 当前状态：**Phase 0 前期筹划与架构加固已完成**，等待用户检阅确认后点火进入 Milestone 1。

## Phase 0：前期筹划与五大工程暗礁加固 `[DONE ✅]`
- [x] 审阅原始蓝图并识别 5 大实战工程暗礁（局部回滚双库撕裂、擂台冷启动与格式误杀、串行推理卡顿、企微协议适配、本机 CLI 环境排雷）
- [x] 初始化 `/Users/Apple/Desktop/公司/arachne-os` Git 仓库与前后端标准目录骨架
- [x] 落盘加固版五大宪法与规范：`AGENTS.md`、`ARCHITECTURE_SPEC.md`、`PROTOCOLS_AND_PROMPTS.md`、`ROADMAP.md`、`ANTI_LAZY_GATES.md`
- [x] 落盘 `.env.example`、`.gitignore`、`backend/requirements.txt`

## Milestone 1：钢铁底座 —— WORM 黑匣子与三级模型网关 `[PENDING ⏳]`
- [ ] 创建 `backend/.venv` 虚拟环境并安装 `requirements.txt` 依赖
- [ ] 实现 `backend/config.py`、`backend/database.py`、`backend/core/schemas.py`
- [ ] 实现 `backend/core/llm_gateway.py`（L1正则硬脱敏 + L2/L3 OpenAI/DeepSeek 路由 + 高拟真离线确定性引擎）
- [ ] 实现 `backend/core/blackbox_vault.py`（SHA-256 哈希链、子树快照封存、`ROLLBACK_SEAL`、`verify_chain_integrity`）
- [ ] 通过 `backend/tests/test_m1_vault_and_gateway.py`

## Milestone 2：基本粒子 —— 权能小球、单元容器、人机黑盒与商务跟单部种子 `[PENDING ⏳]`
- [ ] 实现 `backend/core/particles.py`（四类小球打标、标签检索、容器权限锁与红线拦截器）
- [ ] 实现 `backend/core/containers.py`（`UnitSlot`、TTL 跨岗借球、A/B 双面反推简历库）
- [ ] 实现 `backend/core/human_tool.py`（`InputMinimizer` 最小输入裁剪 + `OutputValidator` 发票强校验）
- [ ] 实现 `backend/seed_demo/commerce_dept_seed.py`（5角色、容器、红线底价球、12+条历史运费/折扣黄金流水）
- [ ] 通过 `backend/tests/test_m2_particles_and_slots.py`

## Milestone 3：活体蛛网 —— 异步脉搏、裂变垫层、门禁与边缘审查哨所 `[PENDING ⏳]`
- [ ] 实现 `backend/swarm/pulse_bus.py`（主旁路异步解耦与 WebSocket 广播总线）
- [ ] 实现 `backend/swarm/spider_network.py`（存算分离工单、不入网不认账门禁、横向共现分面、纵向 `MAX_SPAN` 自动垫层、闲置脱水与唤醒）
- [ ] 实现 `backend/swarm/edge_audit_relay.py`（回传脱敏浓缩、矛盾核查、高压线转交组长、子树级隔离 `LOCAL_ROLLBACK`）
- [ ] 通过 `backend/tests/test_m3_spider_and_relay.py`

## Milestone 4：达尔文进化 —— 双层沙箱、归一化擂台、反向算分与并发盲评董事会 `[PENDING ⏳]`
- [ ] 实现 `backend/swarm/evolution_arena.py`（工匠造球 + `sandbox_ast_guard` + `python -I` 净室子进程 + 历史/冷启动双源归一化擂台）
- [ ] 实现 `backend/swarm/scoring_engine.py`（静默影子陪跑、岗位可替代分、员工反向创新绩效分、领导偏好动态校准）
- [ ] 实现 `backend/swarm/board_of_directors.py`（铁三角 + 动态业务域董事 `asyncio.gather` 并发盲评 + 安全一票否决）
- [ ] 通过 `backend/tests/test_m4_evolution_and_board.py`

## Milestone 5：三体合一 —— 可插拔企微网关、物理脱敏 API 与 React Flow 大屏 `[PENDING ⏳]`
- [ ] 实现 `backend/surfaces/wecom_gateway.py`、`backend/surfaces/api_routes.py`、`backend/main.py`
- [ ] 初始化并实现 `frontend/`（5角色一键切换、企微聊天+三大门面号+右侧伴生边栏、React Flow 活体蛛网大屏、擂台与董事会拍板台）
- [ ] 执行 Iron Auditor 红队全量审计与浏览器端到端 6+5 关卡验收
