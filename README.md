# 《23:59》末班七号线 — AI NPC 时间循环推理游戏

> **第三期「AI+∞开发者创作大赛」开源参赛作品**  
> 一款面向中轻量开源大模型的 **Multi-Agent 时间循环心理博弈与真相还原游戏**。

## 核心亮点

1. **全员失忆短循环 × 真正的行动派 AI NPC**：
   * 8 分钟（`23:52` – `23:59`）江心水下隧道末班车循环，每次失败全员记忆清零，仅玩家跨循环保留线索牌与真相拼图。
   * 4 位 AI NPC（周明远、陈默、林岚、便衣民警陆建军）均拥有**量化状态、私有记忆隔离、分档可透露红线与可改变游戏状态的物理动作**（移动、偷听私聊、当众对质、销毁证物、拉紧急制动、便衣亮证追踪与依法拦截抓捕）。
2. **规则校验闭环与弱模型稳定化工程**：
   * **两层解耦**：玩家自由发言先经【关键词 + 轻量 Tagger】映射标准话题标签，由确定性代码按单回合 ±30 封顶算数值；AI 专心负责扮演台词与提交结构化动作 JSON。
   * **规则硬校验 + 驳回重决策**：例如周明远在车头区企图销毁审批单会被规则引擎 `REJECTED("只能在车尾垃圾箱销毁")`，随后反馈原因触发重决策改为 `MOVE(REAR)`；若 JSON 破损或超时则自动修复/安全降级 `STAY`，绝不崩盘。
   * **右上角一键展开【Agent 工程透视面板】**：完整实时展示私有记忆、内心独白、动作提案、校验裁决（`PASS / REJECTED / INTERCEPTED`）与重试轨迹。
3. **数据驱动与零代码换剧本**：
   * 所有角色、台词、线索、标签与时间线全部配置在 `scenario/*.json`，引擎代码零硬编码人物名与剧情文本。

---

## 快速启动

### 1. 本地运行（Mock 模式免 Key 体验）
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
LLM_MOCK=1 uvicorn app:app --host 0.0.0.0 --port 7860
```
浏览器打开 `http://127.0.0.1:7860` 即可试玩。

### 2. 接入魔搭 API-Inference（推荐用于魔搭创空间公开试玩）
```bash
export LLM_BASE_URL="https://api-inference.modelscope.cn/v1/"
export LLM_API_KEY="<你的魔搭访问令牌>"
export NPC_MODEL="Qwen/Qwen2.5-7B-Instruct"
export TAGGER_MODEL="Qwen/Qwen2.5-7B-Instruct"
export LLM_MOCK=0
uvicorn app:app --host 0.0.0.0 --port 7860
```
前端右上角同时提供 **「🔑 模型令牌」** 选项（通过 `X-User-Token` 请求头仅存内存透传），方便试玩者使用自己的魔搭额度。

### 3. 单台 DGX Spark / 本地 vLLM / SGLang 离线部署方案
本引擎基于标准 OpenAI 兼容接口，支持在单台 **NVIDIA DGX Spark（GB10 128GB）** 或本地 GPU 上使用 SGLang / vLLM 部署 `Qwen3-8B` / `Qwen2.5-7B-Instruct` 驱动全部 4 位 AI NPC：
```bash
# 1) 启动本地 SGLang / vLLM 服务（示例端口 8000）
python -m sglang.launch_server --model-path Qwen/Qwen3-8B --port 8000 --host 0.0.0.0

# 2) 将游戏后端指向本地推理服务
export LLM_BASE_URL="http://127.0.0.1:8000/v1"
export LLM_API_KEY="local-spark"
export NPC_MODEL="Qwen/Qwen3-8B"
export TAGGER_MODEL="Qwen/Qwen3-8B"
export LLM_MOCK=0
uvicorn app:app --host 0.0.0.0 --port 7860
```

---

## 自动化验收测试

```bash
pytest -v
```
涵盖《23:59》技术规格 v1.1 第 8 节全部 11 项核心验收用例以及剧本数据规范、T8 终局拼图防冤死确认和 HTTP API 契约测试。
