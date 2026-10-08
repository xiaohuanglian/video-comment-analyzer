# 交付 E：前后端对接方案（Stage B 实施计划）

## 1. 现有接口可直接复用（零改动）

| 接口/模块 | 用于 |
|---|---|
| `POST /agent/run_async` + `GET /agent/sessions/{id}` + `/summary` + `/stop` | 工作台任务运行与摘要 |
| `GET/POST briefs` + `/briefs/{id}/review` | 任务书审批流 |
| `GET/POST opportunities / experiments / learnings / signals` | 业务对象读写 |
| `GET /products/{pid}/export` | 复盘页指标（暂无专用 GET observations，export 可替代） |
| `GET /import_batches` | 数据溯源展示 |
| Orchestrator 预算/取消/审计、工具注册表 L1-L3 | 原样 |
| `_extract_refs` 审计引用 | 结果归属（需小修，见下） |

## 2. 需要修复的数据问题（优先级 P0，复杂度低）

1. **重复对象**（实证 bug）：`create_opportunity` / `create_content_brief` 增加幂等——同产品内按 problem/title 归一化查重，命中则返回已有 id 并标注 `deduped=true`；语义归并由 AI 建议但人工确认，保留原始证据。
2. **任务归属**：创建类工具统一注入 `created_by_session=ctx.session_id`（模型加字段，默认值兼容旧数据）；视图/卡片按会话过滤。
3. **审计 refs 漏 `brief_id`**：`_extract_refs` 补上（1 行）。
4. **机会/任务书缺 data_nature 标记**：与 learnings 对齐，mock 会话产出打 mock，正式列表默认过滤。
5. **存量 youvibe_demo 重复数据**：写一次性清理脚本（保留 1 份+标记），不动真实 youvibe。

## 3. 需要调整的 Agent 编排（P0，中复杂度）

1. **意图分类前置**（user_research / content_plan / review / asset_query / general）：系统提示词分支 + 工具白名单。user_research 不暴露任务书创建工具。
2. **user_research 输出结构**：新增 `UserSegmentReport`（群体/需求/证据/平台/匹配度+理由/触达方式/确定性），配套 `create_segment_report` 工具（L1）。这是"找潜在用户≠做选题"的落点。
3. **task_update 意图**："只保留第一个"→ 更新既有对象状态 + 同会话继续，禁止新建重复对象；会话加 `parent_session` 引用与任务摘要（≤500 token）。
4. **机会详情九要素**：mock 不贪多，重点是真实模型提示词把"为什么带来产品相关用户/预期行动/验证方式"列为必填；`evaluate.py` 校验这几项非空。

## 4. 需要新增的最小接口（小）

| 接口 | 理由 | 复杂度 |
|---|---|---|
| `GET /products/{pid}/observations` | 复盘页不必拖全量 export | 低 |
| `GET /products/{pid}/segments` + `POST` | UserSegmentReport 存取 | 低 |
| 会话 `POST /agent/sessions/{id}/followup` | 连续对话入口（带 parent 引用） | 中 |

## 5. 暂不需要开发

自动发布、私信触达、归因模型、多 Agent、TrainMind 专属功能、视频渲染、前端框架迁移（原型证明原生 JS 足够）。

## 6. 实施顺序与验收

1. **修数据**（§2，半天）→ 重复对象测试 + 存量清理。
2. **改编排**（§3.1–3.2，1–2 天）→ 验收测试 1（"找潜在用户"不再怪入选题）。
3. **连续对话**（§3.3 + followup 接口，1 天）→ 验收测试 3。
4. **界面切换**：原型打磨后替换 `/growth`（保留旧页 30 天可回退），浏览器验收 6 个场景。
5. **真实模型验收**（需 Key，半天）：function calling 兼容 + 三个场景质量评估 → 人工评分表。

## 7. 主要风险

- 真实 function calling 兼容性（DeepSeek）仍未实测 → 所有 Agent 编排编排改动完成后第一时间做。
- 语义归并误合并真实不同需求 → 规则只做候选，合并需保留双证据链。
- 原生 JS 页面复杂度上升 → 若 Stage B 后交互继续膨胀再评估轻量框架，不在本轮。
