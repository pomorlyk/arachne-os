# TASKS.md — Arachne-OS 实时作战进度看板

> 当前状态：**2026-11-15 本轮组合修复验收完成：后端 264 项、前端 21 项通过，TypeScript 与生产构建通过。下方早期里程碑为开发记录，不代表真实业务、真实模型与外部系统已经验收。**

## 2026-11-15 交接与恢复组合修复

- [x] 创世重部署仅延续有效在岗管理员凭证，优先使用认证请求人；严格模式下来源不明确则拒绝重置，离职前任和休假隔离岗不参与兜底。
- [x] 快照恢复不取消离职停用状态；必要时保留现任管理员自己的身份与凭证作为恢复入口，多管理员保持各自凭证。退休记录经过企业重部署仍参与恢复判断。
- [x] 休假人员、实际代班人和返岗凭证独立于业务快照恢复；完整恢复的第二次运行状态加载也保持交接关系。
- [x] 下属关系与待审批申请随岗位转交；恢复快照后重新匹配有效代班主管。合法返岗经过原岗位、代班人与空隔离槽核验。
- [x] 新接岗者仅继承岗位业务字段，不复制前任个人企微映射；合法返岗保留本人的身份信息。
- [x] 外部回调在同一并发锁内先校验任务、签名、派发来源、工单和幂等条件，失败时不执行全库快照与恢复；合法业务失败仍完整回滚。
- [x] 补强 M29：使用旧账号真实密码及原会话验证离职失效，实际验证登出不触发快照；增加 M30–M33 组合回归。
- [x] 最终全量回归与独立复审通过；本轮新增 47 个后端回归用例，并补强原有断言。

最终验证：

- 后端完整测试：`python -m pytest -q -p no:cacheprovider --tb=short`，264 passed，119.46 秒。
- 前端：`npm test`，21 passed；`npm run build`，TypeScript 与 Vite 构建通过，存在原有单包体积提示。
- 88 个 Python 文件语法解析通过，后端未定义名称检查通过。
- 最初复现流程复测：现任密码 200、前任密码 401；恢复后离职账号保持停用，现任账号 200；主管管理原下属 200，休假返岗 200；无签名回调 401 且 capture/restore 次数均为 0。
- 独立 sol/high 复审的 6 个 API/同步恢复边界用例全部通过，审查范围内没有仍可复现的 P1/P2。
- 原有数据库、WAL 和账本文件的大小与修改时间均保持不变。

验证使用离线临时 SQLite、账本、沙箱和模拟传输；没有调用真实 ERP、企微或模型，也没有重启当前业务服务。

## 2026-11-14 结构性修复

- [x] 默认启用登录鉴权，清除隐式固定密码，绑定实际操作者、岗位与审批对象；重置和重启不复活旧会话。
- [x] 将审批卡和董事会决议改为可校验的终态流程；阻止自批、重复副作用、错误金额及缺少订单依据的发货。
- [x] 增加运行状态事务、私有恢复日志、写入实例锁、后台任务提交边界与异常退出恢复；快照同时恢复相关业务状态。
- [x] 隔离日程演练与兵棋推演的数据库、账本、文件、审批和连接器；保存运行标识与检查点。
- [x] DAG、评分、擂台与红蓝测试按实际结果报告；缺少独立证据的能力保留为候选，不虚构业务完成或防御收益。
- [x] 接通企微文本回调、持久化去重和当前身份检查；增加签名与工单绑定、提交后投递和失败重试记录。
- [x] 前端统一携带认证、区分无权访问与掉线、展示真实演练状态，并提供独立输出复核和候选技能审核入口。
- [x] 修复导入资料的保密底价归属与可见性；模型技能路由只接收输入字段，避免夹带源码、默认值和内部台账。
- [x] 复合技能改为未挂载候选，明确标注模板来源与未完成语义验证；独立审核通过后才发布，沙箱预览须主动选择。
- [x] 修复页面空闲后丢失实时更新、重复归档破坏恢复、缺少金额时补造运费计算参数等集成缺陷。
- [x] 完成最终完整回归与独立复审：后端 214 项、前端 21 项通过，TypeScript 与生产构建通过。

最终验证记录：

- 后端完整测试：`python -m pytest -q -p no:cacheprovider --tb=short`，214 passed，87.49 秒；显式使用离线临时数据库、账本与沙箱。
- 前端：`npm test`，21 passed；`npm run build`，TypeScript 与 Vite 构建通过。仍有单包体积超过 500 kB 的非阻断提示。
- 83 个 Python 文件语法解析通过；后端未定义名称静态检查通过。
- 独立 sol/high 复审发现的问题已完成修复和再次验证，最终 42 项针对性检查通过，审查范围内未发现仍可复现的 P1/P2。
- 原有业务数据库、WAL 与账本文件的大小、修改时间保持不变；未进行真实模型、ERP 或企微账号调用。

当前行为与运行约束：

- 新数据库默认要求配置 `BOOTSTRAP_PASSWORD`；已有账号保留当前凭据。模板见 `.env.example`。
- 每个 SQLite 数据库仅支持一个后端写入进程；第二个写入实例会明确拒绝启动。
- 默认日程演练在缺少订单/金额/审批依据时会停在 `PENDING_REVIEW`，不能把推进到终点作为验收标准。
- 离线规则、合成样本和模板推演均不构成真实模型或真实业务效果的证据。
- 复合技能目前支持明确的内置算术模板；源模块仅作为资料引用，尚不支持任意源码的自动组合。新企业缺少预设引用的真实模块时会拒绝生成。
- 企微长连接支持文本回调与应答；主动交互审批卡尚不支持，保持 `PENDING_EXTERNAL_DELIVERY`，不计作远端已送达。
- 账本采用应用层哈希链与校验点；尚未接入外部不可变存储或独立签名锚点，不能等同物理 WORM 存储。
- 当前验证使用临时离线工作区；真实 ERP、企微账号、模型效果仍须单独验收。当前环境监听本地端口返回 EPERM，未完成浏览器完整走查。

## Phase 0：前期筹划与五大工程暗礁加固 `[DONE ✅]`
- [x] 审阅原始蓝图并识别 5 大实战工程暗礁（局部回滚双库撕裂、擂台冷启动与格式误杀、串行推理卡顿、企微协议适配、本机 CLI 环境排雷）
- [x] 初始化 `/Users/Apple/Desktop/公司/arachne-os` Git 仓库与前后端标准目录骨架
- [x] 落盘加固版五大宪法与规范：`AGENTS.md`、`ARCHITECTURE_SPEC.md`、`PROTOCOLS_AND_PROMPTS.md`、`ROADMAP.md`、`ANTI_LAZY_GATES.md`
- [x] 落盘 `.env.example`、`.gitignore`、`backend/requirements.txt`

## Milestone 1：钢铁底座 —— WORM 黑匣子与三级模型网关 `[DONE ✅]`
- [x] 创建 `backend/.venv` 虚拟环境并安装 `requirements.txt` 依赖
- [x] 实现 `backend/config.py`、`backend/database.py`、`backend/core/schemas.py`
- [x] 实现 `backend/core/llm_gateway.py`（L1正则硬脱敏 + L2/L3 OpenAI/DeepSeek 路由 + 高拟真离线确定性引擎）
- [x] 实现 `backend/core/blackbox_vault.py`（SHA-256 哈希链、子树快照封存、`ROLLBACK_SEAL`、`verify_chain_integrity`）
- [x] 通过 `backend/tests/test_m1_vault_and_gateway.py`

## Milestone 2：基本粒子 —— 权能小球、单元容器、人机黑盒与商务跟单部种子 `[DONE ✅]`
- [x] 实现 `backend/core/particles.py`（四类小球打标、标签检索、容器权限锁与红线拦截器）
- [x] 实现 `backend/core/containers.py`（`UnitSlot`、TTL 跨岗借球、A/B 双面反推简历库）
- [x] 实现 `backend/core/human_tool.py`（`InputMinimizer` 最小输入裁剪 + `OutputValidator` 发票强校验）
- [x] 实现 `backend/seed_demo/commerce_dept_seed.py`（5角色、容器、红线底价球、12+条历史运费/折扣黄金流水）
- [x] 通过 `backend/tests/test_m2_particles_and_slots.py`

## Milestone 3：活体蛛网 —— 异步脉搏、裂变垫层、门禁与边缘审查哨所 `[DONE ✅]`
- [x] 实现 `backend/swarm/pulse_bus.py`（主旁路异步解耦与 WebSocket 广播总线）
- [x] 实现 `backend/swarm/spider_network.py`（存算分离工单、不入网不认账门禁、横向共现分面、纵向 `MAX_SPAN` 自动垫层、闲置脱水与唤醒）
- [x] 实现 `backend/swarm/edge_audit_relay.py`（回传脱敏浓缩、矛盾核查、高压线转交组长、子树级隔离 `LOCAL_ROLLBACK`）
- [x] 通过 `backend/tests/test_m3_spider_and_relay.py`

## Milestone 4：达尔文进化 —— 双层沙箱、归一化擂台、反向算分与并发盲评董事会 `[DONE ✅]`
- [x] 实现 `backend/swarm/evolution_arena.py`（工匠造球 + `sandbox_ast_guard` + `python -I` 净室子进程 + 历史/冷启动双源归一化擂台）
- [x] 实现 `backend/swarm/scoring_engine.py`（静默影子陪跑、岗位可替代分、员工反向创新绩效分、领导偏好动态校准）
- [x] 实现 `backend/swarm/board_of_directors.py`（铁三角 + 动态业务域董事 `asyncio.gather` 并发盲评 + 安全一票否决）
- [x] 通过 `backend/tests/test_m4_evolution_and_board.py`

## Milestone 5：三体合一 —— 可插拔企微网关、物理脱敏 API 与 React Flow 大屏 `[DONE ✅]`
- [x] 实现 `backend/surfaces/wecom_gateway.py`、`backend/surfaces/api_routes.py`、`backend/main.py`
- [x] 初始化并实现 `frontend/`（5角色一键切换、企微聊天+三大门面号+右侧伴生边栏、React Flow 活体蛛网大屏、擂台与董事会拍板台）
- [x] 执行 Iron Auditor 红队全量审计与端到端 6+5 关卡验收（14/14 pytest 全绿 + `vite build` 零报错）
