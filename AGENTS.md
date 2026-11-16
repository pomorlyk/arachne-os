# AGENTS.md — Arachne-OS 工程宪法与内生双核制衡规范（加固版 v2.0）

## 1. 项目定位
本项目 **Arachne-OS (Mini MVP)** 是一个面向企业的“蜘蛛织网式”自适应、自繁衍、自进化多智能体操作系统。
以 **企业微信三体合一套件（聊天窗口 + 原生伴生右侧边栏 + 3大职能门面智能体 + 工作台千人千面视图）** 为交互载体，默认内置最具泛用性的 **【商务跟单与客户运营部】** 全链路业务沙盘，支持“本地全真仿真器模式（`LocalSimulatorAdapter`）”与“真实企业微信接入模式（`WeComBotWSAdapter` / `WeComWebhookCallbackAdapter`）”一键无缝切换。

## 2. 内生多智能体双核制衡开发协议（Antigravity Native Orchestration）
针对当前工作环境，本项目不依赖外部失效 CLI 联动，采用 **Antigravity 主控总架构师 + 原生专职子智能体（Subagents）** 上下文隔离与红队交叉制衡开发模式：

- **👑 主控总架构师（Master Architect & Full-Stack Integrator）**
  - 职责：统管全局架构契约、维护 `TASKS.md` 作战进度板、协调前后端接口一致性、构建 `surfaces/` 网关总线与 `frontend/` 全套可视化大屏（企微三体合一仿真器 + React Flow 活体蛛网动态拓扑热力图 + 5角色千人千面控制台），并启动真实服务完成端到端全关卡验收。

- **⚙️ 核心引擎专员（Core Engine Specialist Subagent）**
  - 职责：在受控任务边界内专注攻坚 `backend/core/` 与 `backend/swarm/` 下的高密度核心引擎（WORM 只追写哈希链黑匣子、子树隔离快照回滚、权能小球打标与容器锁、蛛网自适应裂变/脱水状态机、边缘审查哨所、双层隔离沙箱影子擂台、反向创新算分与并发盲评董事会），并编写高覆盖率 `pytest` 自动化测试套件。

- **🛡️ 铁面红队审计员（Iron Auditor Subagent — 独立只读上下文）**
  - 职责：在里程碑合入及最终交付前，以独立挑刺视角对照 `ANTI_LAZY_GATES.md` 执行静态与动态审计——扫描全库空壳占位符、验证 `BlackBoxVault` 无篡改接口、执行 AST 沙箱逃逸渗透测试、核验普通员工视角 API 响应体字节级零敏感信息泄露。

## 3. 系统不可逾越的五大工程铁律（Iron Laws）

1. **黑匣子只追写与子树隔离回滚铁律（WORM + Subtree Rollback Seal）**
   - `core/blackbox_vault.py` 存储区对系统内所有组件仅开放 `READ`（快照读取与完整性校验）与 `APPEND`（事件追加与快照封存）接口；**物理与代码层面严禁实现任何 `UPDATE`、`DELETE`、`TRUNCATE` 或覆盖写方法**。
   - 发生边缘异常需要局部倒退（`LOCAL_ROLLBACK`）时，必须在账本**追加**一条 `ROLLBACK_SEAL` 封条记录，并在热状态库（SQLite）中严格按 `subtree_root_id` 分区仅重置目标异常子树，**绝不冲毁正常兄弟分支工单，也绝不抹除已记录的员工越界违规计数**。

2. **双层物理隔离沙箱铁律（AST Guard + Clean-Env Subprocess）**
   - AI 工匠（`ArtisanAgent`）生成的任何 Python 技能脚本，在运行前必须先通过 `sandbox_ast_guard` 静态语法树白名单审查（严禁非白名单模块导入、严禁危险内置函数、严禁 `__` 双下划线魔术属性链式逃逸）。
   - 执行阶段必须在独立的 `sandbox_workspace/` 工作目录下，使用 `python -I` 隔离模式及清空宿主敏感环境变量（剥离 `LLM_API_KEY` 等密钥）的子进程运行，硬超时上限 `3.0 秒`。

3. **人机同构与黑盒契约铁律（UnitSlot & HumanBlackBoxTool）**
   - 工作记忆与四类权能小球（`DATA` / `SKILL` / `AUTHORITY` / `REDLINE`）永久绑定在 `UnitSlot`（岗位单元容器）上，不绑定具体自然人；支持带过期时间戳（TTL）的跨岗借球（`borrowed_balls`）。
   - 涉及物理隔离设备（如财务加密税控盘）或线下动作时，必须将真人封装为 `HumanBlackBoxTool`，严格执行 `InputMinimizer`（仅投喂最小必要字段，剥离商业谈判上下文）与 `OutputValidator`（输出格式与金额强校验，不合格自动打回重填）。

4. **高压线强制人工拍板与物理级 RBAC 脱敏铁律**
   - 凡涉及【资金金额变动、超权限折扣、对外法律承诺、客户赔偿、人事任免】的决策，任何 Agent 严禁自行放行，必须挂起 `WorkTicket` 并路由至基层组长/主管节点审批。
   - 前后端通信严格执行**后端物理级序列化裁剪**：普通员工视角的 HTTP/WS 响应负载中，物理上严禁出现 `replaceability_score`（岗位 AI 可替代分）、`management_view`（B面管理画像）及绝密底价明文。

5. **模型网关解耦、三级算力漏斗与主旁路异步隔离铁律**
   - 所有大模型调用统一经过 `core/llm_gateway.py`（兼容 OpenAI / DeepSeek / 本地 Ollama 接口，且未配置 API Key 时自动启用高拟真确定性语义规则回退引擎，确保离线 100% 跑通全部测试与演示剧本）：
     - **L1（本地零成本确定性层）**：正则与规则脚本完成私聊寒暄剥离、手机号/身份证/银行卡硬脱敏（`[REDACTED]`）、重复日志去重；
     - **L2（节点轻量快速层）**：负责主链路门禁核查、日常问答与权能小球提取；
     - **L3（董事会深度推理层）**：按需唤醒，负责工匠代码生成、冷启动边界基准合成、董事会并发独立盲评。
   - **主旁路解耦**：主聊天请求仅执行 L1 + 红线/门禁 + 即时响应以保证丝滑交互；耗时的“后台影子陪跑试做、AI 可替代分重算、标签共现聚类裂变、闲置节点脱水巡检”统一交由后台异步脉搏总线（`BackgroundSwarmPulse`）执行，并通过 WebSocket 实时推送到前端蛛网大屏。

## 4. Python 与前端依赖管理准则
- Python 后端统一使用项目内虚拟环境（`backend/.venv` + `backend/requirements.txt`），**严禁全局执行 `pip install`**。
- 前端统一在 `frontend/` 下使用 `npm` 管理依赖，确保 TypeScript 严格模式编译零错误。

