# 共享后端（方案 C）

路径：`apps/backend`  
为 Admin 与 Student 提供同一 FastAPI 进程与数据库。

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- Admin API：现有 `/api/*`（knowledge、questions、extraction…）
- Student API：后续挂载 `/api/v1/student/*`（见实现步骤规划）
