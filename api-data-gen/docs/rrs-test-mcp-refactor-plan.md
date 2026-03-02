# rrs-test-mcp 造数链路分析与重构落地方案

## 1. 本阶段目标

本阶段只做两件事：

1. 明确 `D:\workspace\rrs-test-mcp` 中哪些文件真正参与了“测试场景生成 + 造数 + SQL输出”链路。
2. 给出按阶段落地的重构方案，后续严格按阶段执行，不直接把 Java 一次性翻译成 Python。

当前不做业务代码迁移，只做方案和范围冻结。

## 2. 当前主入口与调用链

当前主入口是：

- `D:\workspace\rrs-test-mcp\src\main\java\cn\webank\rrs\springai\TestMultiAPIDataGen.java`

对外工具封装入口是：

- `D:\workspace\rrs-test-mcp\src\main\java\cn\webank\rrs\springai\TestDataGenerationService.java`
- `D:\workspace\rrs-test-mcp\src\main\java\cn\webank\rrs\DataGenMcpServerApplication.java`

当前核心调用链可概括为：

```text
TestDataGenerationService.generateTestData
  -> TestMultiAPIDataGen.generateTestData
    -> 解析 apiMappings
    -> DBDataGenerator.getTableInfoFromSQL
      -> 查询 t_request_info / t_database_operation
      -> SQLAnalyzer.extractSQLInfo
    -> getAllTableSchemas
      -> TableInfoJson.generateTableJson
    -> generateP0Scenarios
      -> LLM 生成测试场景
    -> identifyLocalFieldsForTables
      -> TestDataGen.identifyLocalFields
      -> DictRules / 字典映射 / 固定规则
    -> sampleDataForAI
      -> DBDataGenerator.sampleTableData
    -> analyzeDataFeatures
      -> LLM 分析样本特征
    -> generateAndMergeDataForScenarios
      -> LLM 补全字段
      -> 本地规则补字段
      -> 合并校验
    -> generateInsertStatements
      -> 输出 INSERT SQL
```

结论：当前实现不是“单一造数器”，而是一个大编排类，把接口回放、SQL提取、表结构抽取、样本采样、本地规则造数、LLM补数、SQL渲染全部揉在一起。

## 3. 涉及造数的文件清单

### 3.1 核心必迁移文件

这些文件直接参与当前造数主链路，应视为 Python 重构的主要参考源：

| 类别 | 文件 | 作用 | 重构建议 |
| --- | --- | --- | --- |
| 主编排 | `src/main/java/cn/webank/rrs/springai/TestMultiAPIDataGen.java` | 多接口场景生成、样本采样、AI补数、本地补数、SQL拼装总入口 | 拆成多个 Python 模块，不保留“大一统类” |
| MCP工具封装 | `src/main/java/cn/webank/rrs/springai/TestDataGenerationService.java` | 对外暴露 `generateTestData` 工具方法 | 后续改为 Python tool / agent action |
| SQL回放与采样 | `src/main/java/cn/webank/rrs/DBDataGenerator.java` | 从流量表回放接口 SQL、采样业务表、字段匹配、fallback 样本生成 | 拆为 `trace_repo`、`sampler`、`field_matcher` |
| SQL解析 | `src/main/java/cn/webank/rrs/SQLAnalyzer.java` | 提取表名和 where 条件 | Python 中独立成纯函数模块 |
| 单表造数规则 | `src/main/java/cn/webank/rrs/springai/TestDataGen.java` | 本地字段规则、AI字段识别、局部造数 | 保留规则思想，重写实现 |
| 表结构抽取 | `src/main/java/cn/webank/rrs/springai/TableInfoJson.java` | `SHOW CREATE TABLE` 转 JSON schema | Python 独立成 schema extractor |
| 字典规则 | `src/main/java/cn/webank/rrs/springai/DictRules.java` | 根据字段名/注释/字典表决定本地生成规则 | 迁移为规则插件 |
| 字典映射预处理 | `src/main/java/cn/webank/rrs/springai/SysDictProcessor.java` | 生成并写入 `t_aml_sys_dict_info` | 迁移为一次性数据准备脚本，不纳入实时编排 |
| 数据库连接 | `src/main/java/cn/webank/rrs/AMLMysqlExample.java` | AML 与 `rrs_test_dev` 库连接、字典查询 | 改为 Python 配置化 repository |
| 数据库连接 | `src/main/java/cn/webank/rrs/AMLTidbExample.java` | TiDB 连接和建表信息获取 | 改为 Python 配置化 repository |

### 3.2 与主链路重复但可作为迁移参考的文件

这些文件包含了重复实现或早期抽取版，不一定继续保留，但对拆分模块有参考价值：

| 文件 | 作用 | 处理建议 |
| --- | --- | --- |
| `src/main/java/cn/webank/rrs/APIMapperExtractor.java` | 从 `TestMultiAPIDataGen` 中提取出的接口-SQL信息获取逻辑 | 保留为“能力边界参考”，不要再继续复制 |
| `src/main/java/cn/webank/rrs/util/ToolTableInfoExtractor.java` | 通用版接口表信息提取工具 | 后续与 `APIMapperExtractor` 合并为一个 Python trace extractor |
| `src/main/java/cn/webank/rrs/springai/GetTableName.java` | 只提取接口涉及表名 | 可并入 trace extractor 子能力 |
| `src/main/java/cn/webank/rrs/RrsTestDevExample.java` | 直接查 `t_request_info` / `t_database_operation` 的示例 | 仅做行为参考 |
| `python/api_mapper_extractor.py` | 已有 Python 版接口映射提取原型 | 可作为 Python 重构的起点之一 |

### 3.3 对外运行和接入层文件

这些文件不负责造数逻辑本身，但决定后续 Python 方案如何被调用：

| 文件 | 作用 | 处理建议 |
| --- | --- | --- |
| `src/main/java/cn/webank/rrs/DataGenMcpServerApplication.java` | Spring AI MCP 服务端启动 | 后续可替换为 Python CLI / FastAPI / MCP server |
| `src/main/java/cn/webank/rrs/SimpleDataGenMcpClient.java` | 通过 HTTP SSE 调用 MCP 工具 | 迁移后决定是否保留调用方式 |
| `src/main/java/cn/webank/rrs/client/SimpleMcpClient.java` | Java MCP client | 非第一优先级 |
| `src/main/java/cn/webank/rrs/client/DataGenClientTool.java` | 客户端工具封装 | 非第一优先级 |
| `src/main/java/cn/webank/rrs/client/DataGenMcpClientApplication.java` | 客户端示例 | 非第一优先级 |
| `src/main/java/cn/webank/rrs/client/McpServerAndClientLauncher.java` | 启动服务端和客户端 | 非第一优先级 |

### 3.4 可明确排除出本次重构主范围的文件

这些文件与 Spring AI、RAG、Demo 有关，但不属于本次“多接口造数主链路”的最小闭环：

- `src/main/java/cn/webank/rrs/springai/TestSingleAPIMultiData.java`
- `src/main/java/cn/webank/rrs/springai/TestSpringAi*.java`
- `src/main/java/cn/webank/rrs/springai/Qwen72B.java`
- `src/main/java/cn/webank/rrs/springai/Rag*.java`
- `src/main/java/cn/webank/rrs/MockService.java`
- `src/main/java/cn/webank/rrs/test/**`
- `src/main/java/cn/webank/rrs/dqc/**`
- `src/main/java/cn/webank/rrs/lineage/**`

这些文件可以后看，不应干扰第一阶段重构。

## 4. 当前实现的主要问题

### 4.1 单类过重

`TestMultiAPIDataGen.java` 同时承担：

- 编排
- prompt 构造
- LLM 调用
- JSON 清洗
- 数据校验
- 本地规则补齐
- SQL 渲染

这会导致迁移时无法做局部替换，也很难做单元测试。

### 4.2 数据访问逻辑重复

以下能力在多个类里重复实现：

- 从 `t_request_info` 获取 `trace_id`
- 从 `t_database_operation` 获取 SQL
- 提取表名和过滤条件

这说明现在没有稳定的“接口 SQL 提取层”。

### 4.3 强依赖内网环境

当前链路依赖这些库表：

- `rrs_test_dev.t_request_info`
- `rrs_test_dev.t_database_operation`
- `rrs_test_dev.field_match_relations`
- `rrs_test_dev.t_aml_sys_dict_info`
- `rrs_test_dev.t_aml_f_import_info`
- `aml_new3.业务表`
- `aml_new3.aml_f_sys_dict`

所以如果不先建立本地 mock MySQL 环境，Python 重构无法稳定验证。

### 4.4 配置硬编码

当前 Java 和已有 Python 原型里都存在硬编码：

- DB 地址
- 用户名密码
- LLM base URL
- API key

这会直接阻碍迁移后的复用和安全治理。

### 4.5 自动化能力不足

当前实现里还存在不适合 agent 自动执行的逻辑：

- `DictRules` 中依赖控制台输入选择映射关系
- 本地规则与 AI 规则的决策流程写死在代码中
- fallback 顺序不可配置

这与“让大模型判断采用哪种造数方式”的目标冲突。

## 5. 重构目标

目标不是“把 Java 改成 Python”这么简单，而是做三层重构：

1. **语言层重构**：Java -> Python。
2. **架构层重构**：大类编排 -> 原子模块。
3. **决策层重构**：固定流程 -> 可由 agent/skill 编排的策略执行。

## 6. 目标 Python 架构建议

建议把未来 Python 项目拆成下面这些模块：

```text
api_data_gen/
  domain/
    models.py                  # InterfaceInfo / SqlInfo / TableSchema / Scenario
  infra/
    db/
      mysql_client.py          # 配置化数据库访问
      trace_repository.py      # t_request_info / t_database_operation
      schema_repository.py     # SHOW CREATE TABLE / information_schema
      sample_repository.py     # 业务表采样
      dict_repository.py       # 字典和映射表
    llm/
      client.py                # 模型调用统一封装
  services/
    sql_parser.py              # SQL 解析
    interface_trace_service.py # 根据接口提取 SQL / 表 / 条件
    schema_service.py          # 结构抽取与缓存
    local_rule_service.py      # 本地规则生成器
    sample_analysis_service.py # 样本分析
    scenario_service.py        # 场景生成
    data_generation_service.py # 单场景/多场景造数
    insert_render_service.py   # SQL 渲染
  strategies/
    local_only.py
    llm_only.py
    local_then_llm.py
    llm_then_local.py
  agents/
    tools.py                   # 面向 agent 的原子工具
    router.py                  # 根据上下文选择策略
  cli/
    main.py                    # 命令行入口
```

核心原则：

- 每个模块只做一件事。
- LLM 调用与规则生成分离。
- 所有数据库访问都从 repository 层进出。
- “先本地还是先 AI” 不写死在主流程，而是做成可配置策略。

## 7. local MySQL mock 环境建议

你已经明确要求在本机 MySQL 模拟内网环境，这一步必须前置。

建议本地最小化准备以下几类表：

### 7.1 链路回放元数据表

这些表用于从接口反查 SQL：

- `t_request_info`
- `t_database_operation`

### 7.2 规则辅助表

- `field_match_relations`
- `t_aml_sys_dict_info`
- `t_aml_f_import_info`

### 7.3 业务样本表

至少先准备当前入口案例实际会用到的业务表，例如：

- `aml_f_tidb_model_result`
- `aml_f_wst_alert_cust_trans_info`
- `aml_f_wst_alert_cust_drft_record`

如果后续接口会扩展，再逐步补表，不需要一开始完整复制内网库。

### 7.4 本地库策略

建议建立两个本地 schema：

- `rrs_test_dev_local`
  作用：放接口回放元数据、字段映射、规则辅助表
- `aml_mock`
  作用：放业务表和样本数据

这样结构上与线上职责一致，但不会把所有内容混在一个库里。

## 8. agent skill / 原子化方案建议

你提到希望更灵活，而不是“本地优先，再 AI 兜底”写死。这个方向是对的。

建议不要一上来做一个“大而全 skill”，而是拆成几类原子工具，由 agent 决策调用：

### 8.1 推荐的原子工具

1. `extract_interface_sql`
   输入接口路径和接口名，输出 trace、SQL、表、过滤条件。

2. `load_table_schema`
   输入表名，输出标准化 schema。

3. `sample_table_data`
   输入表名和采样策略，输出样本。

4. `resolve_local_generators`
   输入 schema，输出哪些字段适合本地规则生成。

5. `generate_scenarios`
   输入需求、接口行为、schema，输出测试场景。

6. `generate_table_rows_local`
   只用本地规则造字段值。

7. `generate_table_rows_llm`
   只用 LLM 生成目标字段。

8. `merge_and_validate_rows`
   合并本地和 LLM 结果，并做字段长度/非空/主键校验。

9. `render_insert_sql`
   把记录渲染成 SQL。

### 8.2 推荐的策略层

不要写死一种流程，至少支持四种策略：

- `local_only`
- `llm_only`
- `local_then_llm`
- `llm_then_local`

让 agent 根据以下信息选择策略：

- 是否有可靠本地规则
- 是否有足够样本
- 是否依赖字典值
- 是否要求结果可解释
- 是否要求完全脱离外部模型

### 8.3 skill 设计建议

如果后续落 skill，建议 skill 只包含：

- 工作流说明
- 原子工具清单
- 何时选择何种造数策略
- 本地 mock 库约定
- 必要脚本

不要把所有业务规则塞进一个超长 `SKILL.md`，规则细节应拆到 `references/` 或 `scripts/`。

## 9. 建议的分阶段执行方案

### Phase 0: 范围冻结与现状建模

产出：

- 当前这份分析文档
- 造数相关文件清单
- 当前调用链和依赖库表清单

完成标准：

- 能明确回答“哪些文件必须迁移，哪些只是参考，哪些可排除”

当前状态：已完成。

### Phase 1: 本地 mock 数据环境设计

产出：

- 本地 MySQL 建库建表方案
- 最小必要表清单
- 需要你提供的 DDL / 样例数据清单
- 字段映射与数据准备说明

完成标准：

- Python 不接内网也能跑通接口 SQL 提取、表结构读取、样本采样

这一步需要你提供表结构和样例数据。

### Phase 2: Python 基础能力迁移

先迁移纯基础能力，不碰 LLM 编排：

- SQL 解析
- trace 查询
- schema 抽取
- 样本采样
- 字典映射查询

完成标准：

- 能在本地 mock 库中，根据接口路径拿到 SQL 和表结构

### Phase 3: Python 本地规则造数闭环

产出：

- 本地字段识别
- 本地字段生成器
- 数据校验
- INSERT SQL 渲染

完成标准：

- 在不调用 LLM 的情况下，能生成一版可执行 SQL

### Phase 4: LLM 场景生成与补数能力接入

产出：

- 场景生成模块
- 样本特征分析模块
- LLM 字段补数模块
- 合并与校验模块

完成标准：

- 能对选中的场景生成补充数据，并和本地规则结果合并

### Phase 5: agent / skill 化封装

产出：

- 原子工具接口
- 策略选择器
- CLI / MCP / agent skill 接入方案

完成标准：

- 模型或调用方可以按场景选择造数策略，而不是走固定流程

## 10. 下一阶段需要你提供的输入

为了进入 Phase 1，你需要提供以下最小输入：

### 必需

1. 本地要模拟的表结构 DDL
   建议优先给这些表：
   - `t_request_info`
   - `t_database_operation`
   - `field_match_relations`
   - `t_aml_sys_dict_info`
   - `t_aml_f_import_info`
   - `aml_f_tidb_model_result`
   - `aml_f_wst_alert_cust_trans_info`
   - `aml_f_wst_alert_cust_drft_record`

2. 每张表的少量样例数据
   不需要很多，3 到 10 行即可，优先覆盖主键、日期、状态码、金额、客户号等关键字段。

### 可选但强烈建议

1. 一个真实需求样例
   包括：
   - 需求描述
   - 接口名/接口路径
   - 固定字段
   - 依赖固定值

2. 一份你认为“理想输出”的样例
   包括：
   - 希望生成的测试场景样式
   - 希望生成的 INSERT SQL 样式

## 11. 建议的下一步

下一步不要直接写 Python 代码，先做 Phase 1：

1. 你提供本地 mock 所需的表结构和样例数据。
2. 我基于这些输入，在当前仓库补一份 Phase 1 markdown：
   - 本地建库方案
   - 最小数据集设计
   - Python 模块拆分草图
3. Phase 1 文档确认后，再进入第一批 Python 脚手架实现。

