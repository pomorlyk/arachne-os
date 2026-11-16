# Arachne-OS 模块化分区地图 (Partition Map)

> **防爆上下文铁律**：禁止在单次迭代中跨区通读大文件；每次只修改 **1~2 个小模块（单文件 ≤ 220 行）**，最后通过轻量级入口（`main.py` / `App.tsx`）归并挂载。

| 分区编号 | 分区职责 | 后端独立模块 (`backend/`) | 前端独立模块 (`frontend/src/`) |
| :--- | :--- | :--- | :--- |
| **Zone 1：账号鉴权与角色隔离** | 独立账号密码登录、Bearer Token 会话、每人仅见自己工位数据 | `core/auth_custody.py`<br>`surfaces/auth_custody_routes.py` | `components/LoginGateView.tsx` |
| **Zone 2：技能球分管与申请审批** | 头头分管球库、下属申请额外球（临时借用/常驻挂载）、领导派发/收回球 | `core/auth_custody.py`<br>`surfaces/auth_custody_routes.py` | `components/BallCustodyModal.tsx` |
| **Zone 3：对话流与内联契约** | 企微自然对话、L1 脱敏、工匠造球、0-Token 调球、内联审批卡 | `swarm/spider_network.py`<br>`swarm/evolution_arena.py` | `components/WeComSimulatorPane.tsx` |
| **Zone 4：拓扑画布与顶层治理** | 蛛网 React Flow、全天自动模拟、3+X 董事会、WORM 账本回滚 | `swarm/day_simulator.py`<br>`swarm/board_of_directors.py` | `components/SpiderTopologyFlow.tsx`<br>`components/ExecutiveControlDeck.tsx` |



---

## 🔥 Phase 3 (v5.0): 高密度 Token 消耗级多 Agent 协同作战、红蓝对抗自愈与企业全模态吞噬工程

为充分释放真实大模型（`DeepSeek-Chat`）的多轮深度推理潜能，将项目按无冲突文件边界切分为 **4 个重型并行子工程（Pillar 1 ~ Pillar 4）**：

### Pillar 1：多智能体跨部门 DAG 协同作战与博弈辩论引擎 (`Multi-Agent DAG & Debate`)
- **负责文件（严禁越界）**：
  - `backend/swarm/dag_mission_engine.py`（新建）
  - `backend/surfaces/dag_mission_routes.py`（新建）
  - `backend/tests/test_m9_dag_mission_and_debate.py`（新建）
- **API 契约（前缀 `/api/v1/missions`）**：
  - `GET /api/v1/missions/presets`：返回 4 个高复杂度跨部门联合作战任务预设（如：大客户跨国紧急锁价与账期特批、供应链断供紧急跨仓调拨与违约金核算、年度大促全渠道毛利保卫战、高危合规审计与越权清查）。
  - `POST /api/v1/missions/execute-dag`：
    - 请求：`{"mission_title": str, "mission_brief": str, "initiator_account_id": str | None, "max_debate_rounds": int = 2, "auto_execute_skills": bool = True}`
    - 响应：`{"mission_id": str, "mission_title": str, "status": "COMPLETED" | "BLOCKED_BY_REDLINE" | "ESCALATED", "dag_nodes": list[dict], "debate_transcript": list[dict], "skill_executions": list[dict], "consensus_resolution": dict, "token_telemetry": {"llm_calls": int, "estimated_tokens": int, "total_latency_ms": float, "mode": str}}`
  - `POST /api/v1/missions/adversarial-debate`：
    - 请求：`{"topic": str, "proposer_slot_id": str, "reviewer_slot_id": str, "arbiter_slot_id": str | None, "rounds": int = 3}`
    - 响应：`{"debate_id": str, "topic": str, "rounds": list[dict], "final_verdict": dict, "token_telemetry": dict}`
  - `GET /api/v1/missions/history`：返回已执行的 DAG 作战与跨部门辩论历史列表。

### Pillar 2：红蓝对抗自愈沙箱与红线穿刺靶场 (`Red-Blue Adversarial Crucible`)
- **负责文件（严禁越界）**：
  - `backend/swarm/red_blue_crucible.py`（新建）
  - `backend/surfaces/crucible_routes.py`（新建）
  - `backend/tests/test_m10_red_blue_crucible.py`（新建）
- **API 契约（前缀 `/api/v1/crucible`）**：
  - `POST /api/v1/crucible/stress-test-skill`：
    - 请求：`{"ball_id": str, "attack_intensity": "STANDARD" | "EXTREME" = "EXTREME", "auto_heal": bool = True, "max_generations": int = 3}`
    - 响应：`{"report_id": str, "ball_id": str, "ball_title": str, "initial_pass_rate": float, "final_pass_rate": float, "healed": bool, "generations": list[dict], "adversarial_vectors": list[dict], "final_code": str, "token_telemetry": dict}`
  - `POST /api/v1/crucible/redline-penetration`：
    - 请求：`{"target_slot_id": str, "attack_count": int = 4}`
    - 响应：`{"audit_id": str, "target_slot_id": str, "slot_title": str, "defense_score": float, "attacks": list[dict], "recommendations": list[str], "token_telemetry": dict}`
  - `GET /api/v1/crucible/reports`：返回历史红蓝对抗报告与穿刺审计报告。

### Pillar 3：企业全模态表格/合同深度吞噬器与持久化快照时间机器 (`Enterprise Ingestor & Snapshot Time-Machine`)
- **负责文件（严禁越界）**：
  - `backend/core/enterprise_ingestor.py`（新建）
  - `backend/core/snapshot_timemachine.py`（新建）
  - `backend/surfaces/ingest_snapshot_routes.py`（新建）
  - `backend/tests/test_m11_ingest_and_snapshots.py`（新建）
- **API 契约**：
  - `GET /api/v1/ingest/samples`：返回 3 份高保真企业原始数据样本（CSV 阶梯价格与库存台账、JSON ERP 采购与BOM清单、Markdown 经销商返利与风控合同）。
  - `POST /api/v1/ingest/document`：
    - 请求：`{"doc_title": str, "doc_format": "CSV" | "JSON" | "CONTRACT_MD" | "AUTO", "raw_content": str, "target_department": str, "target_slot_id": str | None, "auto_forge_query_skill": bool = True}`
    - 响应：`{"ingestion_id": str, "doc_title": str, "detected_format": str, "schema_profile": dict, "created_balls": list[dict], "mounted_to_slot_id": str | None, "sandbox_verification": dict, "summary": str}`
  - `GET /api/v1/snapshots/list`：返回所有磁盘快照列表（`snapshot_id`, `label`, `created_at`, `stats`, `head_hash`）。
  - `POST /api/v1/snapshots/save`：请求 `{"label": str, "note": str}` -> 保存当前全量集群状态到磁盘并返回快照元数据。
  - `POST /api/v1/snapshots/restore`：请求 `{"snapshot_id": str}` -> 恢复集群状态至指定快照时间点。

### Pillar 4：蜂群联合作战室、红蓝炼丹炉与企业吞噬时间机器前端工作台 (`Frontend v5.0 Studios`)
- **负责文件（严禁越界）**：
  - `frontend/src/components/SwarmWarRoomModal.tsx`（新建）
  - `frontend/src/components/RedBlueCrucibleModal.tsx`（新建）
  - `frontend/src/components/EnterpriseIngestSnapshotModal.tsx`（新建）
  - `frontend/src/components/ClusterOperationsBar.tsx`（升级挂载三大新控制台入口）
  - `frontend/src/api.ts` & `frontend/src/types.ts`（扩展 v5.0 接口与类型）
