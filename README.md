# 中考数学 AI 自适应学习系统

## 项目结构（方案 C）

```
LearningSystem/
├── apps/
│   ├── backend/                      # 共享 FastAPI（Admin + Student 同进程同库）
│   │   ├── app/
│   │   │   ├── api/                  # 现有 Admin 路由；后续增加 api/student/
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   ├── services/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   ├── requirements.txt
│   │   └── .env
│   └── frontend/
│       ├── admin/                    # 后台管理 Web（端口 5173）
│       └── student/                  # 学生端 Web（端口 5174，骨架已建）
├── docs/                             # 产品与实现文档
├── data/
│   └── raw/
└── README.md
```

> 原先 `apps/admin/backend`、`apps/admin/frontend` 已迁至上述路径；不再使用独立的 `apps/student/backend`。

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- 开发可用 SQLite；生产建议 PostgreSQL 15+

### 后端启动（共享）

```bash
cd apps/backend

python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

pip install -r requirements.txt

# 配置环境变量（编辑 .env）
uvicorn app.main:app --reload --port 8000
```

### 管理端前端

```bash
cd apps/frontend/admin
npm install
npm run dev
```

访问 http://localhost:5173

### 学生端前端

```bash
cd apps/frontend/student
npm install
npm run dev
```

访问 http://localhost:5174

## 使用流程（Admin）

1. **配置LLM** → 系统配置 → 运行设置，填入大模型API Key和地址
2. **上传资料** → 知识图谱管理 → 资料上传，上传课程标准PDF或教材PDF
3. **知识抽取** → 知识图谱管理 → 知识抽取，选择文件启动抽取任务
4. **查看结果** → 知识图谱管理 → 知识点管理，查看/编辑抽取的知识点
5. **关系构建** → 知识图谱管理 → 知识抽取，启动关系抽取任务

## 已实现功能

### 后台管理系统 - 知识图谱 / 题库等

- [x] PDF文件上传（课程标准/教材）
- [x] 大模型API配置
- [x] 知识点自动抽取与关系抽取
- [x] 知识点 CRUD / 关系管理 / 图谱概览
- [x] 真题题库 Word 解析与管理（见 docs）

### 待开发模块

- [ ] 学生端闭环（见 `docs/学生端自适应学习闭环-实现步骤规划.md`）
- [ ] 共享后端 `api/student` 路由与学情模型
- [ ] AI 智能学习引擎深化

## 技术栈

| 层面 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python) |
| 数据库 | SQLite（开发）/ PostgreSQL（生产）+ SQLAlchemy async |
| 前端框架 | React 18 + TypeScript |
| UI组件 | Ant Design 5 |
| 构建工具 | Vite |
| PDF解析 | PyMuPDF |
| LLM | OpenAI兼容接口（DeepSeek/GPT-4o等）|
