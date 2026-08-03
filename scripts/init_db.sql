-- 数据库初始化脚本
-- 使用方法: psql -U postgres -f init_db.sql

-- 创建数据库
CREATE DATABASE learning_system;

-- 连接到数据库
\c learning_system;

-- 知识点表
CREATE TABLE IF NOT EXISTS knowledge_points (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    subject VARCHAR(20) DEFAULT 'math',
    domain VARCHAR(50),
    grade SMALLINT,
    chapter VARCHAR(200),
    section VARCHAR(200),
    curriculum_ref VARCHAR(100),
    cognitive_level VARCHAR(20),
    exam_frequency VARCHAR(10),
    exam_question_types TEXT,
    description TEXT,
    keywords TEXT,
    source VARCHAR(50),
    status VARCHAR(20) DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 知识点关系表
CREATE TABLE IF NOT EXISTS knowledge_relations (
    id SERIAL PRIMARY KEY,
    from_point_id VARCHAR(50) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    to_point_id VARCHAR(50) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    relation_type VARCHAR(30) NOT NULL,
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_point_id, to_point_id, relation_type)
);

-- 典型题目表
CREATE TABLE IF NOT EXISTS typical_questions (
    id SERIAL PRIMARY KEY,
    knowledge_point_id VARCHAR(50) REFERENCES knowledge_points(id) ON DELETE CASCADE,
    question_content TEXT NOT NULL,
    answer TEXT,
    analysis TEXT,
    difficulty SMALLINT,
    question_type VARCHAR(30),
    source VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_configs (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description VARCHAR(500),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 上传文件表
CREATE TABLE IF NOT EXISTS uploaded_files (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(500) NOT NULL,
    original_name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50),
    file_size INTEGER,
    grade VARCHAR(20),
    semester VARCHAR(20),
    status VARCHAR(20) DEFAULT 'uploaded',
    parse_result JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 抽取任务表
CREATE TABLE IF NOT EXISTS extraction_tasks (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    source_file_id INTEGER REFERENCES uploaded_files(id),
    status VARCHAR(20) DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    result_summary JSONB,
    error_message TEXT,
    config JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_kp_domain ON knowledge_points(domain);
CREATE INDEX IF NOT EXISTS idx_kp_grade ON knowledge_points(grade);
CREATE INDEX IF NOT EXISTS idx_kp_status ON knowledge_points(status);
CREATE INDEX IF NOT EXISTS idx_kr_from ON knowledge_relations(from_point_id);
CREATE INDEX IF NOT EXISTS idx_kr_to ON knowledge_relations(to_point_id);
CREATE INDEX IF NOT EXISTS idx_tq_kp ON typical_questions(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_et_status ON extraction_tasks(status);

-- 插入默认配置
INSERT INTO system_configs (key, value, description) VALUES
    ('llm_api_key', '', '大模型API密钥'),
    ('llm_base_url', 'https://api.deepseek.com/v1', '大模型API地址'),
    ('llm_model', 'deepseek-chat', '大模型名称'),
    ('llm_temperature', '0.1', '生成温度(0-1)'),
    ('llm_max_tokens', '4096', '最大输出token数'),
    ('extraction_batch_size', '5', '每批抽取的切片数量')
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE knowledge_points IS '知识点主表';
COMMENT ON TABLE knowledge_relations IS '知识点关系表';
COMMENT ON TABLE typical_questions IS '典型题目表';
COMMENT ON TABLE system_configs IS '系统配置表';
COMMENT ON TABLE uploaded_files IS '上传文件记录表';
COMMENT ON TABLE extraction_tasks IS '知识抽取任务表';
