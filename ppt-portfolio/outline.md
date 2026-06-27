# Presentation Outline

## Page 1 [cover]
- **Title**: Nootbook — AI 辅助课程笔记平台
- **Content**: 全栈独立开发作品 | 实时语音转录 · PPT 课件对齐 · AI 知识图谱 · RAG 智能问答

## Page 2 [table_of_contents]
- **Title**: 目录
- **Content**: 
  1. 项目概述
  2. 技术架构
  3. 核心功能实现
  4. 技术亮点与总结

## Page 3 [chapter]
- **Title**: 01 项目概述
- **Content**: 为课堂学习场景打造的 AI 一体化笔记解决方案

## Page 4 [content]
- **Title**: 项目背景与核心痛点
- **Content**:
  - 课堂听讲时手动记笔记效率低，容易遗漏重点
  - 课后复习时难以快速定位 PPT 对应内容
  - 零散笔记缺乏结构化知识梳理
  - 传统笔记工具无法与 AI 能力深度结合
  - Nootbook 定位：听课 → 转录 → 对齐 → 复习 → 测验的完整闭环

## Page 5 [content]
- **Title**: 核心功能总览
- **Content**:
  - 六大核心模块：实时语音转录、PPT 课件对齐、AI 知识图谱、RAG 智能问答、AI 测验生成、笔记编辑导出
  - 【预留产品截图区域：Dashboard 首页 + 笔记详情页整体界面】

## Page 6 [chapter]
- **Title**: 02 技术架构
- **Content**: React 18 + FastAPI 全栈架构，AI 能力深度集成

## Page 7 [content]
- **Title**: 前后端技术栈
- **Content**:
  - 前端：React 18 + TypeScript + Vite + Tailwind CSS + Zustand + ReactFlow
  - 后端：FastAPI + SQLAlchemy + SQLite + Alembic 迁移
  - AI/音频：FunASR 本地模型 + DeepSeek API + DashScope Embedding
  - 向量搜索：本地轻量级实现，神经 Embedding + TF-IDF 降级策略

## Page 8 [content]
- **Title**: 系统架构与数据流
- **Content**:
  - 用户层 → React 前端 → FastAPI 后端 → 多服务模块（ASR/PPT/向量/RAG/知识图谱/测验）
  - 数据存储：SQLite 关系数据 + 本地向量索引 + 文件系统（音频/PPT 图片）
  - 异步任务：多 Agent 并行处理，状态机驱动进度追踪

## Page 9 [chapter]
- **Title**: 03 核心功能实现
- **Content**: 从代码层面拆解四大 AI 功能模块

## Page 10 [content]
- **Title**: 实时语音转录与流式 ASR
- **Content**:
  - 三级降级策略：FunASR 本地模型 → DashScope 云端 ASR → Whisper API
  - 流式实时转录：600ms 分块缓冲 + 模型缓存去重，避免文本重复
  - 时间戳精确对齐：每个转录片段附带起止时间，支持后续 PPT 对齐
  - 【预留截图区域：语音转录界面 + 实时流式效果】

## Page 11 [content]
- **Title**: PPT 课件对齐与知识图谱
- **Content**:
  - PPT 解析：python-pptx 提取文本 + Pillow 渲染幻灯片为 PNG 图片
  - 幻灯片与转录文本时间轴对齐，支持逐页跳转定位
  - AI 知识图谱：DeepSeek 分析笔记内容 → 生成结构化节点关系 → ReactFlow 交互可视化
  - 节点类型：主题/概念/要点/难点/示例/流程/函数/问题/结论
  - 【预留截图区域：PPT 播放器 + 知识图谱画布】

## Page 12 [content]
- **Title**: RAG 智能问答与 AI 测验
- **Content**:
  - RAG 流程：用户提问 → 本地向量检索（Top-K 相关片段）→ DeepSeek 流式生成答案
  - 答案溯源：每条回答标注来源（PPT 页码 / 转录片段 / 笔记块）
  - AI 测验：基于课程内容自动生成选择题题库，支持答题、提交、查看解析
  - SSE 流式推送：实时状态更新 + 答案片段逐字呈现
  - 【预留截图区域：RAG 问答界面 + 测验界面】

## Page 13 [content]
- **Title**: 技术亮点与工程实践
- **Content**:
  - 本地向量搜索：无需外部向量数据库，DashScope Embedding + numpy 余弦相似度
  - 多 Agent 异步架构：转录/知识图谱/测验/向量索引并行处理，状态机追踪进度
  - 三级容错降级：ASR、Embedding、LLM 均设计 fallback 策略，确保服务可用性
  - 完整用户系统：JWT 认证 + 权限控制 + 分享链接 + 数据导入导出

## Page 14 [final]
- **Title**: 感谢观看
- **Content**: Nootbook — 用 AI 重新定义课堂笔记体验 | 全栈独立开发作品
