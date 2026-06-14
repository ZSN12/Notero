# 可靠性修复方案（参考 2026-06-06 排查）

## 问题总结

今天的核心 bug 链：

1. **前端**：`file input` 选同一个文件不触发 `onChange` → 用户点了上传但根本没发请求
2. **后端**：`logging` 没配置 → `logger.info` 全被静默 → 看不到任何请求日志
3. **AI 纠正**：`min_ratio=0.65` 过保守 → DeepSeek 合法结果被丢弃 → 用户看到的是本地稿
4. **UI 状态**：没有"正在纠正"状态 → 用户以为结果已纠正，实际没走 LLM
5. **缺乏验证**：没有 e2e 测试 → 问题在线上才被发现

---

## 修复清单

### 1. 前端：上传按钮强制触发（已修复 ✅）

```tsx
// 每次点击前清空 input value，强制浏览器认为"值变了"
<button onClick={() => {
  if (audioInputRef.current) audioInputRef.current.value = '';
  audioInputRef.current?.click();
}}>
```

**为什么**：`<input type="file">` 的 `onChange` 只在 `value` 变化时触发，选同一个文件 value 不变。

---

### 2. 后端：强制 Logging 配置（已修复 ✅）

```python
# app/main.py 开头
import logging
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
```

**为什么**：Python 默认 logging 级别是 WARNING，所有 `logger.info` 被丢弃。没有日志 = 盲人摸象。

---

### 3. AI 纠正：放宽阈值 + 核心词兜底（已修复 ✅）

```python
# 三处统一
min_ratio=0.50  # 之前 0.60/0.65/0.70 不一致

# 新增核心词覆盖率判断
_core_terms()  # 提取内容词（"进程"、"管道"、"父子进程"）
# 如果长度比不够，但 75% 核心词还在，就接受
```

**为什么**：课堂 ASR 有大量"啊、OK、是不是"等废话，DeepSeek 正常去掉后长度很容易降到 65% 以下。

---

### 4. 前端：显示"纠正状态"（已修复 ✅）

在 `NoteDetail` 转写面板标题旁显示状态标签，并根据 `correction_error` 内容做语义化提示：

| 状态 | 标签文案 | 触发条件 |
|------|---------|---------|
| 🟢 AI 已纠正 | `AI 已纠正` | `is_ai_corrected=True` |
| 🟡 本地整理 | `本地整理` | `is_ai_corrected=False` 且无错误 |
| 🔴 未配置 API | `本地整理：未配置 API` | `correction_error` 包含"未配置" |
| 🔴 纠正超时 | `AI 纠正超时` | `correction_error` 包含"超时" |
| 🔴 疑似删减 | `AI 纠正被拦截：疑似删减` | `correction_error` 包含"删减" |
| 🔴 其他失败 | `AI 纠正失败` | 其他 `correction_error` |

代码位置：`src/pages/note-detail/index.tsx` 标题栏、`src/pages/note-detail/hooks/useAudioUpload.ts` 回调、`src/pages/note-detail/hooks/useRestructure.ts`。

---

### 5. 端到端测试（已补充 ✅）

`backend/tests/test_e2e_audio_upload.py` 现包含 4 个场景：

1. **`test_audio_batch_stream_events_and_ai_correction`** — AI 纠正成功全流程
   - Mock ASR + Mock DeepSeek（`preserves_source_content=True`）
   - 断言 SSE 序列：`status → chunk → done`
   - 断言 `is_ai_corrected=True`、display_text 包含专业术语

2. **`test_audio_batch_without_llm_falls_back_to_local`** — 无 LLM 降级
   - `has_llm=False`
   - 断言 `is_ai_corrected=False` 且 `correction_error` 非空

3. **`test_audio_batch_ai_rejected_for_truncation`** — AI 结果被拦截
   - Mock DeepSeek 返回过短文本（`preserves_source_content=False`）
   - 断言 `is_ai_corrected=False`，且 fallback 到本地长文本

4. **`test_audio_batch_chunked_upload_flow`** — 大文件分片上传
   - 构造 >10MB 文件触发分片上传路径
   - 断言每片返回 `received=True`，finish 返回 200

**运行**：
```bash
python -m pytest backend/tests/test_e2e_audio_upload.py -v
```

---

### 6. 监控/告警（已补充 ✅）

新增 `backend/scripts/health_check_audio_pipeline.py`，可独立运行：

```bash
export API_BASE=http://localhost:8003
export ADMIN_EMAIL=admin
export ADMIN_PASSWORD=admin123
python backend/scripts/health_check_audio_pipeline.py
```

功能：
1. 探测 `/api/health`
2. 登录获取 token
3. 创建临时 notebook + session
4. 上传 mock 音频（Mock ASR + Mock DeepSeek）
5. 解析 SSE，断言事件序列和 `is_ai_corrected=True`
6. 退出码：0=健康，1=降级，2=异常

**集成到 cron / CI**：
```bash
# 每天抽查一次
0 9 * * * cd /opt/notero && python backend/scripts/health_check_audio_pipeline.py || alert
```

后端已在 `audio.py` 关键路径输出结构化日志：
```
audio_upload pipeline: session=xxx asr_ok=True llm_called=True llm_accepted=True
```

---

### 7. 前端防御：上传超时/失败提示（已加强 ✅）

`src/pages/note-detail/hooks/useAudioUpload.ts` 新增 **SSE  stall 检测**：

- 上传开始后启动 30 秒定时器
- 每次收到 `onStatus` / `onChunk` / `onDone` / `onError` 回调时刷新计时
- 若 30 秒内无任何 SSE 事件到达：
  - 自动 `abort()` 取消请求
  - UI 显示 `上传处理超时，请检查网络或稍后重试`
  - 重置 `isUploadingAudio=false`

```tsx
const UPLOAD_STALL_TIMEOUT_MS = 30000;

const startStallTimer = (abort: () => void) => {
  lastSseAtRef.current = Date.now();
  stallTimerRef.current = setTimeout(() => {
    if (Date.now() - lastSseAtRef.current >= UPLOAD_STALL_TIMEOUT_MS) {
      abort();
      setAudioUploadError('上传处理超时，请检查网络或稍后重试');
      setIsUploadingAudio(false);
    }
  }, UPLOAD_STALL_TIMEOUT_MS);
};
```

---

## 优先级

| 优先级 | 事项 | 状态 |
|--------|------|------|
| **P0** | file input 清空触发 | ✅ 已修复 |
| **P0** | logging 配置 | ✅ 已修复 |
| **P0** | min_ratio + 核心词兜底 | ✅ 已修复 |
| **P1** | 前端显示纠正状态标签 | ✅ 已修复 |
| **P1** | e2e 上传测试 | ✅ 已补充 |
| **P2** | 监控/health check | ✅ 已补充 |
| **P2** | 上传超时防御 | ✅ 已加强 |

---

## 核心原则

> **任何环节失败，都必须让用户感知到。**

今天的反面教材：
- 前端没发请求 → 用户以为在转写（静默失败）
- 后端没日志 → 开发者看不到问题（静默失败）
- DeepSeek 结果被丢弃 → 用户看到的是本地稿（静默降级）

修复后的目标：
- 上传失败 → UI 显示红色错误
- 后端异常 → 日志可见 + 前端收到 error SSE
- DeepSeek 被拦截 → UI 显示"本地整理，AI 纠正被拦截：xxx"
