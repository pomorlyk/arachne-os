# PROTOCOLS_AND_PROMPTS.md — 智能体推理契约、双层沙箱模具与前后端通信协议（加固版 v2.0）

> 所有后端核心模块与前端组件必须严格遵循本文档定义的 JSON Schema、AST 安全规则、REST 路径及 WebSocket 事件电报码，严禁私自更改字段名！

---

## 1. 四大核心智能体集群推理契约（`llm_gateway.py` 统一结构化路由）

所有智能体决策均通过 `LLMGateway.complete_json(tier, system_prompt, user_payload, response_model, fallback_fn)` 发起：
- 当 `.env` 配置了有效 `LLM_API_KEY` 时，向兼容 OpenAI 格式的模型接口发起真实 JSON 推理，并用 Pydantic 模型强校验输出；
- 当未配置 `LLM_API_KEY`（或处于离线 CI 测试模式）时，自动路由至高拟真确定性语义分析器（非死板固定字符串，而是基于实体提取、规则图谱与动态 AST 代码合成的真实可执行逻辑），确保离线状态下所有状态机、代码生成、沙箱执行与算分 100% 真实运转。

### 1.1 潜伏打标与门禁蜘蛛（`ExplorerSpider` — Tier L2）
- **输入上下文**：脱敏后的消息文本、聊天类型（`SINGLE | GROUP`）、是否有外部转发依据、发送者所属 `UnitSlot` 持有的小球摘要及当前系统红线球列表。
- **强制输出 JSON 结构（`ExplorerDecision`）**：
```json
{
  "context_complete": true,
  "missing_context_prompt": "若不入网不认账触发（如无前置订单依据直接要求发货/开票），此处填写向员工追问的一句话",
  "high_voltage_triggered": false,
  "high_voltage_category": "NONE | PRICE_OVERRIDE | COMPENSATION | LEGAL_COMMITMENT | HR_CHANGE",
  "high_voltage_reason": "若触发高压线，说明具体涉钱/赔偿/法务原因以挂起工单转交基层组长老李",
  "redline_violated": false,
  "violated_redline_ball_id": null,
  "extracted_balls": [
    {
      "ball_type": "DATA | SKILL | AUTHORITY | REDLINE",
      "title": "提取出的知识/规则标题",
      "domain_tags": ["报价", "物流"],
      "sensitivity_level": 2,
      "content": "结构化提炼后的干净业务内容"
    }
  ],
  "structured_order_draft": null,
  "reply_to_user": "面向当前角色得体、精准的回复内容"
}
```

### 1.2 偏远边缘审查哨所（`EdgeAuditRelay` — Tier L1 + L2）
- **强制两步流水线**：
  1. **L1 确定性硬脱敏（`sanitize_l1_text`）**：
     - 11 位中国大陆手机号 → `[REDACTED_PHONE]`
     - 18 位身份证号 → `[REDACTED_ID]`
     - 16~19 位银行卡号 → `[REDACTED_CARD]`
     - 私人寒暄与非业务闲聊语句（如周末聚餐、私人八卦、家庭琐事）→ 在提取业务摘要时自动剥离并记录 `stripped_private_segments_count`。
  2. **L2 语义与红线复核输出 JSON（`RelayAuditResult`）**：
```json
{
  "sanitized_summary": "剥离隐私与废话后的结构化业务结论（供上层节点消费）",
  "stripped_private_count": 2,
  "redacted_pii_count": 1,
  "contradiction_detected": false,
  "redline_breach": false,
  "verdict": "PASS | ESCALATE_SUPERVISOR | LOCAL_ROLLBACK",
  "rollback_reason": "若触发 LOCAL_ROLLBACK，详细记录写入 BlackBoxVault ROLLBACK_SEAL 的异常原因"
}
```

### 1.3 自我进化造球工匠（`ArtisanAgent` — Tier L3）与双层沙箱 AST 铁律
当员工口述提效逻辑（如阶梯运费、批量包装换算、账期滞纳金核算）时，`ArtisanAgent` 生成的 Python 代码**必须且只能**遵循以下标准模具：
```python
# 仅允许导入白名单标准库：math, json, re, datetime, decimal, collections, statistics
from decimal import Decimal, ROUND_HALF_UP

def execute_skill(payload: dict) -> dict:
    """
    payload: 输入业务参数字典（例如 {"weight_kg": 5.0, "order_amount": 320.0}）
    return: {"status": "ok", "result": <数值或结构化字典>}
    """
    return {"status": "ok", "result": 0}
```
- **第一层：`sandbox_ast_guard(source_code: str)` 静态语法树安检规则**：
  - 使用 `ast.parse()` 解析语法树并校验必须包含顶层函数定义 `execute_skill`；
  - `ast.Import` / `ast.ImportFrom`：模块根名必须严格属于 `{"math", "json", "re", "datetime", "decimal", "collections", "statistics"}`，其余（如 `os`, `sys`, `subprocess`, `shutil`, `socket`, `pathlib`, `urllib`, `http`, `ctypes`, `builtins`）一律抛出 `SandboxSecurityViolation`；
  - 禁止调用的危险名称集合：`{"eval", "exec", "open", "compile", "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir", "breakpoint", "input", "memoryview"}`；
  - 禁止访问任何以 `__` 开头的属性（`ast.Attribute.attr.startswith("__")` 全部拦截，彻底阻断 `().__class__.__bases__[0].__subclasses__()` 原型链逃逸）。
- **第二层：净室子进程执行与归一化影子擂台**：
  - 将受检代码写入 `sandbox_workspace/skill_{candidate_id}.py`，通过独立子进程 `python -I`（隔离模式）执行，清空宿主 `os.environ`（仅保留 `LC_ALL=C.UTF-8`），硬超时 `timeout=3.0` 秒；
  - 对 `BlackBoxVault` 抽取的基准测试集逐条回放，经 `NormalizedResultComparator`（支持 `Decimal` 数值容差 `±0.01` 与货币符号剥离）比对，仅当 `success_rate == 1.0` 且 `match_rate >= 0.98` 时晋升为 `ACTIVE`！

### 1.4 顶层自适应董事会并发盲评协议（`BoardOfDirectors` — Tier L3）
召开董事会（`convene_board`）时，**严禁在单次请求中让同一模型扮演所有董事**！必须构造相互独立且立场对立的董事 Agent 实例，通过 `asyncio.gather(*director_tasks)` 并发盲评：
- `SecurityDirector`（安全红线官）：审查数据泄露、红线破坏与合规风险，可投 `APPROVE | CONDITIONAL | VETO`（若 `VETO`，议案直接一票否决）；
- `EvolutionDirector`（进化效率官）：评估自动化提效幅度与岗位可替代成熟度，输出 `score (0~100)` 与改革建议；
- `CostDirector`（算力成本官）：评估 Token ROI 与闲置节点脱水率，输出 `score (0~100)` 与降本意见；
- `DomainDirector[k]`（动态业务域董事，随横向聚类出的活跃业务域自动列席）：从一线履约连续性角度打分；
- 最终得分按 `PreferenceCalibrator` 动态学习的领导偏好权重加权合成 `BoardResolution`，推送至 `#3 董事会内参` 供老板拍板。

---

## 2. 前后端严丝合缝通信契约（REST + WebSocket）

- **后端服务基准地址**：`http://localhost:8000`
- **前端开发服务地址**：`http://localhost:5173`

### 2.1 核心 REST API 接口清单

| 方法 | 路径 | 用途说明 | 关键权限/行为约束 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/state/overview` | 查询当前全局/个人状态快照（参数：`role_view`, `user_id`） | **物理级 RBAC 裁剪**：`role_view=employee` 时响应 JSON 严禁包含 `replaceability_score`、`management_view`、`boundary_probes` 及绝密底价内容；`role_view=finance_tool` 时仅返回脱敏开票待办 |
| `POST` | `/api/v1/chat/message` | 向三大门面号发送聊天或转发外部私聊记录 | 请求体：`{sender_id, role_view, facade_bot: "COPILOT"\|"GOVERNANCE"\|"BOARD_INSIDER", chat_type: "SINGLE"\|"GROUP", content, raw_wechat_forward?: string[]}`；主链路秒回并触发后台 `PulseBus` |
| `POST` | `/api/v1/human-tool/submit` | 基层组长审批高压线卡片 / 财务王姐提交黑盒开票结果 | 组长审批驱动挂起工单流转至财务黑盒或驳回；财务提交发票号与金额时强制过 `OutputValidator`，格式错误当场返回 `422` 校验失败详情并要求重填 |
| `POST` | `/api/v1/evolution/propose` | 员工提交自然语言提效规则 → 工匠造球 → 沙箱影子擂台 | 返回生成代码、AST 安检报告、历史/冷启动样本回放成绩单、是否晋升 `ACTIVE`、以及员工实时获得的创新绩效加分 |
| `POST` | `/api/v1/swarm/inject-burst` | 压力与故障演练接口（支持批量注入并发子工单或模拟边缘节点异常幻觉） | 用于直观触发并验证 `MAX_SPAN` 纵向自动垫层（生成 `RELAY_NODE`）及边缘哨所拦截与子树局部倒退（`LOCAL_ROLLBACK`） |
| `POST` | `/api/v1/board/convene` | 召开顶层自适应董事会并发盲评 | 返回铁三角 + 动态业务域董事独立投票详情、加权总分及岗位接管提案 |
| `POST` | `/api/v1/board/approve-transition` | 老板拍板批准/驳回提案（如将岗位切换为 `HYBRID_TRANSITION`） | 同步更新 `UnitSlot.occupant_type` 并驱动 `PreferenceCalibrator` 微调老板偏好权重向量 |
| `POST` | `/api/v1/vault/rollback` | 手动触发局部子树回滚或老板级全局黑匣子紧急回滚 | 请求体：`{scope: "LOCAL"\|"GLOBAL", subtree_root_id?, snapshot_hash?, reason}`；严格追加 `ROLLBACK_SEAL` 并校验哈希链完整性 |
| `GET` | `/api/v1/vault/verify` | 实时校验 `BlackBoxVault` 全链 SHA-256 完整性 | 返回 `{intact: bool, total_records: int, head_hash: str, broken_at_seq: int\|null}` |

### 2.2 WebSocket 实时蛛网脉搏总线（`ws://localhost:8000/ws/events`）
后端状态发生任何演化时，通过 `PulseBus` 实时广播以下标准 JSON 帧：
```json
{
  "event_id": "evt_uuid",
  "event_type": "BALL_MINTED | ASPECT_CLUSTERED | LAYER_PADDED | NODE_DEHYDRATED | NODE_REHYDRATED | RELAY_INTERCEPTED | LOCAL_ROLLBACK | GLOBAL_ROLLBACK | ARENA_RESULT | SCORE_UPDATED | BOARD_PROPOSAL | SLOT_TRANSITIONED",
  "timestamp": "2026-11-12T08:00:00Z",
  "node_id": "node_commerce_quote",
  "subtree_root_id": "subtree_quote",
  "severity": "INFO | SUCCESS | WARNING | CRITICAL",
  "summary": "用于在前端实时战报流展示的一句话中文简报",
  "payload": {}
}
```
