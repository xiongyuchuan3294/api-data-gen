# CLAUDE.md

本文档为 Claude Code（claude.ai/code）在此仓库中处理代码时提供指引。

## 项目概览

这是一个**API 测试数据生成工具**，通过分析接口追踪、表结构，并生成 SQL INSERT 语句来为 API 测试构造测试数据。它结合了本地数据库分析能力，以及可选的 AI 能力。

---

## 快速开始执行手册

### Step 1: 环境准备

```bash
# 安装依赖
pip install -e .

# 复制配置模板
cp .env.example .env
```

### Step 2: 配置 `.env` 文件

编辑 `.env` 文件，配置以下关键项：

```bash
# MySQL 连接信息
API_DATA_GEN_MYSQL_HOST=127.0.0.1
API_DATA_GEN_MYSQL_PORT=3306
API_DATA_GEN_MYSQL_USER=root
API_DATA_GEN_MYSQL_PASSWORD=

# 数据库 Schema
API_DATA_GEN_TRACE_SCHEMA=rrs_test_dev      # 接口追踪数据库
API_DATA_GEN_BUSINESS_SCHEMA=aml_new3        # 业务数据库
API_DATA_GEN_MYSQL_CHARSET=utf8mb4

# 系统设置
API_DATA_GEN_SYSTEM_BASE_URL=http://172.21.8.178:9982/aml/  # 注意：必须以 / 结尾
API_DATA_GEN_SYS_ID=aml_web

# AI 提供方（可选，使用 local 模式时不需要）
API_DATA_GEN_AI_PROVIDER=anthropic           # openai / anthropic / claude_code
API_DATA_GEN_AI_API_KEY=your_api_key
API_DATA_GEN_AI_BASE_URL=
API_DATA_GEN_AI_MODEL_NAME=

# 执行策略（可选）
API_DATA_GEN_AGENT_MODE=local                # local / direct / agent / agent_auto
```

### Step 3: 启动 MySQL 并初始化数据库

使用同仓库 `lineage-analysis` 提供的 PowerShell 脚本，自动启动独立的 MySQL 实例（数据目录位于 `D:\workspace\.mysql-api-data-gen`，无需系统服务）：

```bash
# 启动本地 MySQL（首次运行会自动初始化）
powershell -ExecutionPolicy Bypass -File D:\workspace\lineage-analysis\scripts\start_mysql_local.ps1 -Port 3306

# 停止本地 MySQL
powershell -ExecutionPolicy Bypass -File D:\workspace\lineage-analysis\scripts\stop_mysql_local.ps1 -Port 3306
```

启动后的环境变量（如使用本地 MySQL）：
- `API_DATA_GEN_MYSQL_HOST=127.0.0.1`
- `API_DATA_GEN_MYSQL_PORT=3306`
- `API_DATA_GEN_MYSQL_USER=root`
- `API_DATA_GEN_MYSQL_PASSWORD=`（无密码）

初始化数据库：
```bash
mysql --default-character-set=utf8mb4 -u root < sql/mysql/phase1_seed.sql
```

初始化后创建以下表：

| 数据库         | 表名                              | 用途          |
| -------------- | --------------------------------- | ------------- |
| `rrs_test_dev` | `t_request_info`                  | HTTP 请求追踪 |
| `rrs_test_dev` | `t_database_operation`            | SQL 操作记录  |
| `rrs_test_dev` | `field_match_relations`           | 跨表字段映射  |
| `rrs_test_dev` | `t_aml_sys_dict_info`             | 字典映射配置  |
| `aml_new3`     | `aml_f_wst_alert_cust_trans_info` | 业务表示例    |

### Step 4: 准备测试需求文件

创建需求文件 `./requirements/test_wst_alert.txt`：

```txt
# 测试需求：微闪贴预警客户交易信息查询

## 场景描述
查询客户号为 962020122711000002 的微闪贴预警交易信息

## 接口信息
- 接口路径：/aml/wst/custTransInfo
- 请求参数：custId=962020122711000002, caseDate=2020-12-27, modelNo=WSTY001

## 数据生成需求
1. 模型结果表（aml_f_tidb_model_result）：2条记录
2. 交易信息表（aml_f_wst_alert_cust_trans_info）：10条记录
3. 票据背书记录表（aml_f_wst_alert_cust_drft_record）：10条记录

## 约束条件
- cust_id 固定为 962020122711000002
- model_key 固定为 WSTY001
- alert_date 固定为 2020-12-20
```

### Step 5: 执行数据生成

> **重要提示**：
> - `--api` 参数格式为 `name=path`，其中 `path` 是相对于 `API_DATA_GEN_SYSTEM_BASE_URL` 的相对路径（不带前导 `/`）
> - 示例：`custTransInfo=wst/custTransInfo`（会拼接为 `http://172.21.8.178:9982/aml/wst/custTransInfo`）
> - `API_DATA_GEN_SYSTEM_BASE_URL` 必须以 `/` 结尾，否则 URL 拼接会出错
> - **输出默认保存到 `./output/` 文件夹**，包括 JSON 结果和 SQL 文件

#### `local` - 纯本地规则（无 AI，最快）

```bash
# Phase 2: 构建场景草稿
api-data-gen draft --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode local

# Phase 3: 生成 INSERT SQL
api-data-gen generate --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode local
```

#### `direct` - 直接调用 AI

```bash
# 使用 AI 生成场景
api-data-gen draft --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode direct --use-ai-scenarios

# 使用 AI 生成数据
api-data-gen generate --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode direct --use-ai-data
```

#### `agent_auto` - 混合 ReAct 模式

```bash
# AI 自主规划并执行
api-data-gen generate --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode agent_auto
```

#### `agent` - 提示词准备模式

```bash
# 返回 agent_bundle 供外部 AI 处理
api-data-gen generate --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --strategy-mode agent
```

**输出文件示例**：
```
output/
├── result_20260303_143022_local.json    # JSON 格式结果
├── insert_20260303_143022_local.sql     # SQL INSERT 脚本
├── result_20260303_143105_direct.json
└── insert_20260303_143105_direct.sql
```

### Step 6: 应用生成的 SQL

```bash
# 将生成的 SQL 应用到数据库（需要配置 --apply-sql）
api-data-gen generate --requirement-file ./requirements/test_wst_alert.txt --api "custTransInfo=wst/custTransInfo" --apply-sql --generation-tag RUN20260303
```

---

## 输出文件说明

所有执行策略的结果会自动保存到 `./output/` 文件夹：

| 模式 | JSON 输出 | SQL 输出 | 说明 |
|------|-----------|---------|------|
| `local` | ✓ | ✓ | 完整的结果和 SQL |
| `direct` | ✓ | ✓ | 完整的结果和 SQL |
| `agent_auto` | ✓ | ✗ | 只输出 JSON（agent_bundle） |
| `agent` | ✓ | ✗ | 只输出 JSON（agent_bundle） |

**文件命名格式**：
- JSON: `result_YYYYMMDD_HHMMSS_{mode}.json`
- SQL: `insert_YYYYMMDD_HHMMSS_{mode}.sql`

**自定义输出路径**：
```bash
# 指定 SQL 输出文件
api-data-gen generate ... --sql-output-file ./custom/output.sql
```

---

## 执行方式对比

| 模式 | 命令参数 | 场景数 | AI 参与 | 测试结果 | 特点 |
|------|----------|--------|---------|----------|------|
| `local` | `--strategy-mode local` | 3 | 无 | ✓ 通过 | 最快，适合简单场景 |
| `direct` + `--use-ai-scenarios` | `--strategy-mode direct --use-ai-scenarios` | 5 | 场景生成 | ✓ 通过 | 场景更全面（5 vs 3） |
| `direct` + `--use-ai-data` | `--strategy-mode direct --use-ai-data` | 3 | 数据生成 | ✓ 通过 | 数据更多样化 |
| `agent_auto` | `--strategy-mode agent_auto` | 3 | 全流程 | ✓ 通过 | 完全自动化 |
| `agent` | `--strategy-mode agent` | - | 外部 AI | - | 返回 agent_bundle |

---

## 常用 CLI 命令

### 接口与表分析
```bash
# 从接口追踪中提取 SQL / 表信息
api-data-gen interface --api-path /api/customer/query --api-name queryCustomer

# 读取表结构
api-data-gen schema --table t_customer

# 抽样表中的数据行
api-data-gen sample --table t_customer --limit 3
```

### 数据生成
```bash
# 构建场景草稿（Phase 2）
api-data-gen draft --requirement-file req.txt --api "query=/api/query"

# 生成测试数据（Phase 3）
api-data-gen generate --requirement-file req.txt --api "query=/api/query"
```

### 执行策略说明

通过 `--agent-mode` 或 `API_DATA_GEN_AGENT_MODE` 配置：

| 策略 | AI 参与度 | 工具调用 | 适用场景 |
|------|-----------|----------|----------|
| `agent` | 外部 AI | 无 | 需要人工审核提示词后手动执行 |
| `agent_auto` | 内置 AI | 是（ReAct 循环） | 完全自动化的复杂场景 |
| `local` | 无 | 无 | 快速生成，无需 AI |
| `direct` | 内置 AI | 否（固定流程） | 简单的 AI 辅助生成 |

### 运行测试
```bash
pytest tests/                          # 运行全部测试
pytest tests/test_skills_decorator.py  # 运行指定测试文件
```

---

## MCP Server（用于外部 AI 集成）

```bash
python -m api_data_gen.agents.mcp.server --port 8000 --init-skills
```

---

## 架构

### 分层结构

```text
cli/main.py          # 入口，负责参数解析与服务编排
       v
agents/              # AI agent 编排层
  |- orchestrator_service.py      # 主 agent 编排服务
  |- hybrid_orchestrator.py       # 混合式 AI + 本地执行（agent_auto 模式）
  |- executor/                    # ReAct 执行引擎
  |  |- react_executor.py         # 支持工具调用的 agent 实现
  |  `- base.py                   # 执行结果类型
  |- skills/                      # Skill 定义（基于装饰器）
  |  |- data_sampling.py          # 表数据抽样相关 skill
  |  |- scenario_skills.py        # 场景生成相关 skill
  |  |- data_generation.py        # 数据生成相关 skill
  |  `- interface_skills.py       # 接口 / SQL 提取相关 skill
  `- mcp/                         # MCP 协议集成
     `- server.py                 # 用于工具调用的 HTTP 服务
       v
services/            # 核心业务逻辑
  |- planning_service.py          # Phase 2：草稿规划
  |- data_generation_service.py   # Phase 3：SQL 生成
  |- ai_scenario_service.py       # AI 场景生成
  |- ai_data_generation_service.py
  |- ai_chat_client.py            # 多提供方 AI 客户端
  |- local_field_rule_service.py  # 业务字段本地规则
  |- field_match_*.py             # 跨表字段对齐
  |- sql_apply_service.py         # 将 SQL 应用到数据库
  `- sql_script_export_service.py
       v
infra/db/            # 数据库访问层
  |- mysql_client.py              # MySQL 连接
  |- schema_repository.py         # 表结构访问
  |- sample_repository.py         # 数据抽样
  |- trace_repository.py          # 接口追踪访问
  `- field_match_repository.py    # 跨表字段映射
       v
domain/models.py     # 数据类（TraceRequest、TableSchema 等）
```

### 数据流

1. **Phase 1** - Bootstrap：创建包含 trace 表和业务表的模拟 MySQL 数据库
2. **Phase 2** - Draft：分析需求和接口，生成场景 / 数据草稿
3. **Phase 3** - Generate：根据草稿生成 SQL INSERT 语句

### 关键设计模式

- **依赖注入**：服务通过构造函数接收依赖
- **策略模式**：支持多个 AI 提供方（OpenAI、Anthropic、Claude Code）
- **编排模式**：由 `AgentOrchestratorService` 协调多阶段执行
- **Skill 系统**：使用 `@skill` 装饰器把函数注册为 agent 可调用工具
- **混合执行**：同时支持固定流程和 AI 自主模式

---

## 执行策略详解

### `agent` - 提示词准备模式

**适用场景**：将本地上下文打包为结构化提示词，供外部 AI（如 Claude Code）处理。

**核心流程**：
```
外部资源 → 本地分析 → 提示词 Bundle → 🤖 外部 AI 执��� → 最终结果
```

**输出**：返回 `agent_bundle`（JSON 结构），包含：
- `system_prompt`：系统提示词
- `user_prompt`：整合了需求、接口信息、表结构的用户提示
- `available_tools`：可用工具列表
- `context`：表结构、样本数据、本地规则等上下文

---

### `agent_auto` - 混合 ReAct 模式

**适用场景**：AI 自主规划任务，通过 ReAct 循环调用本地工具完成执行。

**核心流程**：
```
外部资源 → 上下文准备 → 🤖 ReAct 循环（Think-Act-Observe） → 最终结果
```

**可用 Skills**：
- `generate_scenarios_ai` / `generate_scenarios_local`：场景生成
- `generate_table_rows_ai` / `generate_table_rows_local`：数据生成
- `sample_table_data`：从数据库表采样数据
- `get_table_schema`：获取表结构
- `render_insert_sql`：渲染 SQL

---

### `local` - 纯本地规则模式

**适用场景**：完全基于本地规则生成，不调用任何 AI 服务。

**核心流程**：
```
外部资源 → 本地规则引擎 → 直接输出
```

**本地规则来源**：
- 内置业务字段规则（如 `cust_id` 生成 18 位值、`transactionkey` 特定格式）
- 字典映射：从 `rrs_test_dev.t_aml_f_import_info` 获取码值
- 样本数据：从 `aml_new3` 业务表采样
- 条件值：从 `rrs_test_dev.t_database_operation.sql_text` 的 WHERE 条件中提取

---

### `direct` - 直接调用 AI 模式

**适用场景**：绕过 agent 编排层，直接调用 AI 服务完成生成。

**核心流程**：
```
外部资源 → 判断标志 → 🤖 AI 服务 / 本地服务 → 输出
```

| 条件 | 调用服务 | 输出 |
|------|----------|------|
| `--use-ai-scenarios` | AI 生成场景 | AI 生成的 scenarios |
| `--use-ai-data` | AI 生成数据 | AI 补全的字段值 + INSERT SQL |
| 未指定 | 本地规则生成 | 本地生成的 scenarios/SQL |

---

## 数据生成逻辑（Phase 3）

### 值来源规则

数据生成会按确定性的优先级应用列级计划：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | `condition` | 使用接口追踪中的固定 SQL 过滤值 |
| 2 | `dictionary` | 轮换使用字典 / 码表映射值 |
| 3 | `sample` | 轮换使用采样得到的业务数据 |
| 4 | `generated` | 生成确定性的主键风格值 |
| 5 | `default` | 落地为具体的本地兜底值 |
| 6 | `optional` | 对可空列输出 `NULL` |

### 主键处理

- 非自增主键始终使用生成值，除非条件中已固定该值
- 自增主键渲染为 `DEFAULT`
- 不会复用采样得到的主键值
- 当提供 `generation_tag` 时，生成的主键会包含基于 tag 的标识以避免冲突

### 跨表字段对齐

当 `field_match_relations` 包含 `target_table.target_field <- source_table.source_field` 时：
- 字段值会从已生成的源表记录中对齐过来
- 由条件推导出的字段不会被覆盖（冲突会在校验阶段报告）

当目标表既没有样本数据，也没有已定义关系时：
- 会自动触发字段匹配发现
- 候选源表会按行数排序
- 匹配优先使用相同列名，其次使用相同注释
- 发现的关系会持久化到 `rrs_test_dev.field_match_relations`

### 本地业务字段规则

在任何 AI 数据生成之前，先应用以下规则：

- 类似 `cust_id` 的字段：生成确定性的 18 位值（例如 `962020122711000002`）
- `transactionkey`：使用兼容 Java 的模式 `6008CYYYYMMDD...99996`
- `model_seq`：空字符串
- 由字典驱动的字段：优先在本地生成

### AI 数据补全（`--use-ai-data`）

启用后：
- 对于本地生成的字段，会先在采样记录中做掩码处理
- 可选的样本分析会先执行，并为每张表提供提示信息
- AI 只补全非本地字段；本地规则仍然优先

### 必填列兜底值

对于没有具体来源的必填列：
- 数值类型：`0`
- datetime / timestamp：`1970-01-01 00:00:00`
- date：`1970-01-01`
- 文本类：`column_name_N`

### Generation Tag

`generation_tag` 用于确保确定性主键在不同批次之间不发生冲突：
- 格式：`RUN20260302` 或基于时间戳的格式
- 会附加到生成的主键上，用于区分不同批次
- 当多次使用 `--apply-sql` 时必须提供

---

## 重要文件

- `src/api_data_gen/cli/main.py` - CLI 入口
- `src/api_data_gen/agents/hybrid_orchestrator.py` - 混合执行模式
- `src/api_data_gen/agents/executor/react_executor.py` - ReAct agent 实现
- `src/api_data_gen/agents/skills/decorator.py` - Skill 注册装饰器
- `src/api_data_gen/services/planning_service.py` - 核心规划逻辑
- `src/api_data_gen/services/data_generation_service.py` - 核心生成逻辑
- `src/api_data_gen/services/local_field_rule_service.py` - 业务字段规则
- `src/api_data_gen/domain/models.py` - 所有领域数据类

---

## 与 Agent 系统协作

### 定义新 Skill
```python
from api_data_gen.agents.skills import skill

@skill(name="my_skill", description="这个 skill 的作用")
def my_skill(param1: str, param2: int = 5) -> dict:
    """Skill 实现"""
    return {"result": param1}
```

### 使用 Agent Auto 模式
```python
from api_data_gen.agents import HybridAgentOrchestrator, ExecutionMode, ExecutionConfig

config = ExecutionConfig(mode=ExecutionMode.AGENT_AUTO, max_agent_turns=15)
orchestrator = HybridAgentOrchestrator(..., react_executor=ReActExecutor(llm_client))
report = orchestrator.generate(requirement, interfaces, config=config)
```
