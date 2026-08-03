# 大模型 API 使用场景说明

> 本文档记录系统中各功能模块对大模型（LLM）API 的依赖情况，便于部署和排障时快速定位。

## 系统配置项

系统在「系统配置 → 运行设置」中维护以下 LLM 相关配置（`system_configs` 表）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `llm_api_key` | （空） | 大模型 API 密钥，如 DeepSeek、OpenAI 等 |
| `llm_base_url` | `https://api.deepseek.com/v1` | 兼容 OpenAI 格式的 API 地址 |
| `llm_model` | `deepseek-v4-flash` | 模型名称 |
| `llm_temperature` | `0.1` | 生成温度，越低越确定 |
| `llm_max_tokens` | `4096` | 单次最大输出 token 数 |

以上配置由 `app/services/llm_client.py` 中的 `create_llm_client()` 统一读取，构建 `LLMClient` 实例（基于 `openai.AsyncOpenAI`），供所有需要大模型的服务共用。

---

## 需要大模型 API Key 的任务

以下 4 个任务启动时会检查 `llm_api_key`，**为空则直接报错退出**。

### 1. 知识抽取（课标知识点分类）

- **服务文件**：`app/services/extraction_service.py`
- **任务类型**：`knowledge_extraction`
- **流程**：PDF 正则预提取编号条目 → 分批发给 LLM 做 domain / category_1 / category_2 / cognitive_level 分类
- **相关配置**：`extraction_batch_size`（每批条目数）、`extraction_llm_concurrency`（LLM 并发数）
- **Key 检查位置**：`_run_extraction_async()` 开头

### 2. 关系抽取（知识点依赖关系）

- **服务文件**：`app/services/extraction_service.py`
- **任务类型**：`relation_extraction`
- **流程**：按领域分组，将知识点列表发给 LLM 分析 prerequisite / related 关系
- **Key 检查**：与知识抽取共用同一入口检查

### 3. 知识点智能关联（题目 ↔ 知识点匹配）

- **服务文件**：`app/services/kp_link_service.py`
- **流程**：题目内容（题干+选项）分批发给 LLM，匹配最佳知识点 ID，生成待确认建议
- **Key 检查位置**：`_run_kp_link_async()` 开头

### 4. 教材标注（知识点 ↔ 年级/章节匹配）

- **服务文件**：`app/services/annotation_service.py`
- **流程**：解析教材 PDF 文本，分批发给 LLM 为知识点匹配年级段和章节
- **Key 检查位置**：`run_annotation_task()` 开头

---

## 不需要大模型的任务

以下任务完全基于本地规则引擎或 OCR，**无需配置 API Key 即可正常运行**。

### 1. 试卷解析（Word → 结构化题目）

- **服务文件**：`app/services/word_parser.py`
- **技术手段**：`python-docx` + `lxml` 解析 docx XML 结构；正则匹配题号、大题标题、分值、选项、答案、解析；提取嵌入图片为文件
- **说明**：纯规则引擎，不调用任何外部 API

### 2. 答案图片转文本

- **服务文件**：`app/services/answer_image_text_service.py`
- **技术手段**：本地 EasyOCR 引擎识别公式图片 + 图像处理（分数线检测、根号横线检测）+ 字符串规则纠错（√→V 修正等）
- **说明**：首次加载 OCR 引擎较慢，但全程本地运算，不调用 LLM

### 3. 章节目录抽取

- **服务文件**：`app/services/chapter_toc_service.py`
- **技术手段**：正则匹配「第X章」「X.X 标题」格式，从 PDF 文本中提取章节结构
- **说明**：`extraction_service.py` 中特判 `task_type == "chapter_toc_extraction"` 直接走本地逻辑，绕过 LLM

### 4. 结构模板生成

- **服务文件**：`app/services/exam_template_service.py`
- **技术手段**：纯数据库统计聚合（题型分布、知识点分值占比）
- **说明**：不涉及任何文本理解，仅做数值计算

### 5. 课标 PDF 解析（OCR + 正则提取）

- **服务文件**：`app/services/pdf_parser.py`
- **技术手段**：PyMuPDF 提取文字版 PDF 文本 / EasyOCR 识别扫描版 PDF；正则提取编号条目、一级/二级分类标题
- **说明**：此步骤仅做文本提取和结构化，不调用 LLM。提取结果随后交给「知识抽取」任务由 LLM 分类

---

## 总结

```
┌──────────────────────────────────┐
│         需要大模型 API Key        │
├──────────────────────────────────┤
│  知识抽取（分类）                 │
│  关系抽取（依赖关系）             │
│  知识点智能关联（题目↔知识点）     │
│  教材标注（知识点↔年级/章节）      │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│        不需要大模型 API Key       │
├──────────────────────────────────┤
│  试卷解析（Word→题目）            │
│  答案图片转文本（本地OCR）         │
│  章节目录抽取（正则）              │
│  结构模板生成（数据库统计）         │
│  课标PDF解析（OCR+正则提取）       │
└──────────────────────────────────┘
```
