# 《23:59》技术规格 v1.1（给 Codex）

2026-11-25 · 鬼知

## 0. 设定核验结论（对应《23:59》最终封板改动清单）

封板清单全部采纳：剧名《23:59》、时间 23:52–23:59、耳机串频、第 4 位 AI 便衣民警陆建军（老陆）、取消玩家肉身阻拦。核验时另外发现 4 处会卡死真结局的细节，已按下表裁定。**以本文为准**。

| # | 封板清单里的问题 | 本规格的裁定 |
| --- | --- | --- |
| 1 | “提交拼图即结算”与“跨过 00:00 才算通关”矛盾；而且老陆自动传唤如果发生在 T8，玩家来不及把新拿到的审批单放进拼图 | **结局只在 T8 结束、时钟跳向 00:00 的瞬间判定**。拼图板随时可填可改，不消耗回合，填对的内容跨循环保留 |
| 2 | 老陆兜底传唤写的是“下一回合”执行，条件在 T7 满足时会拖到 T8，紧贴着判定 | 改为**条件满足的当回合立刻执行** `DETAIN` |
| 3 | 林岚和老陆都会“追着周走”，但周在 T5 有脚本移动，按旧的结算顺序林岚会走到周刚离开的区 | 移动结算顺序改为 **小陈 → 周 → 林岚 → 老陆**，追踪者一律在被追踪者之后结算 |
| 4 | “实物”没有定义：线索牌跨循环保留，如果上一轮的牌也算实物，老陆开局就能被说服 | 实物 = **本轮**小陈已交出记录本、玩家手里真的拿着它时出示 C6 或 C7；或已交出记录本的小陈本人与老陆同区 |

上一版的裁定继续有效：单回合每项数值变化 **所有来源合计封顶 ±30**；T4 密谈是脚本事件（玩家必须装睡才听得到）；关键剧情节点由代码强制；共 8 张线索牌 C0–C7。

第 8 节附真结局路线：从“跳至 23:53”开始，在 T7 保住审批单，T8 填好拼图，跨零点得到结局 D，数值已逐回合推过。

## 1. 技术栈、部署与分工

一个 Python 后端服务同时提供游戏 API 和静态前端页面，部署在魔搭创空间，模型走魔搭 API-Inference 的 OpenAI 兼容接口。

| 层 | 选型 | 负责人 |
| --- | --- | --- |
| 后端 | Python 3.11 + FastAPI + uvicorn，单进程，游戏状态存内存（按 `session_id` 区分） | Codex |
| 模型调用 | `openai` Python SDK，`base_url` 和 `model` 全部走环境变量 | Codex |
| 前端 | 纯 HTML + CSS + 原生 JS，放在 `web/`，由 FastAPI 以静态文件挂载在 `/` | Claude |
| 剧情与台词 | `scenario/` 下的 JSON 和角色卡文案 | Gemini 出稿，Codex 录入 |
| 美术 | 立绘、车厢背景、线索牌图，放 `web/assets/` | Codex / 生图流程 |

**环境变量**

```
LLM_BASE_URL=https://api-inference.modelscope.cn/v1/
LLM_API_KEY=<魔搭访问令牌>
NPC_MODEL=<角色用模型 ID>
TAGGER_MODEL=<打标签用模型 ID，可与 NPC_MODEL 相同>
LLM_MOCK=0        # 1 = 不调模型，用假数据跑通流程
LLM_TIMEOUT=20    # 秒
```

魔搭 API-Inference 的地址是 `https://api-inference.modelscope.cn/v1/`，用标准 OpenAI SDK 调用，API Key 就是魔搭访问令牌（[魔搭官方文章](https://developer.aliyun.com/article/1651776)）。免费额度大约每天 2000 次，前提是魔搭账号绑定阿里云并完成实名认证，否则接口报 401（[申请教程](https://aicoding.csdn.net/6a696eb7662f9a54cb958e3c.html)）。

**额度是硬约束**：如果每回合 1 次打标签 + 4 个 NPC + 重试，约 5 次调用；一轮 8 回合约 40 次；打出真结局约 5 轮，就是 200 次。一天只够十来个人玩完。所以第 6 节规定了省调用的规则，另外前端提供“填自己的魔搭令牌”的选项作为后备。

**待 Codex 确认的两件事**

- [ ] 魔搭创空间是否支持 Docker 自定义镜像及所需端口。不支持的话，退回创空间支持的 Python SDK（如 Gradio），在其底层 FastAPI 上挂载我们的路由和静态页
- [ ] 选定的 `NPC_MODEL` 在 API-Inference 上实测单次延迟和 JSON 输出稳定性，优先中小尺寸、非推理类的 Qwen 指令模型（推理模型会先输出一大段思考，太慢）

## 2. 目录结构与剧本数据

所有剧情数据放在 `scenario/` 的 JSON 里，引擎代码里不出现任何角色名或台词。换一套 JSON 就是另一个故事，这也是创作手记里的工程卖点。

```
23-59/
├─ app.py                 # FastAPI 入口：挂载 /api 和 web/
├─ engine/
│  ├─ state.py            # GameState / NPCState
│  ├─ turn.py             # 回合结算主流程（第 3 节）
│  ├─ rules.py            # 规则校验（第 5 节）
│  ├─ tagger.py           # 关键词兜底 + LLM 打标签
│  ├─ npc.py              # NPC 决策调用与 JSON 修复
│  ├─ llm.py              # OpenAI 兼容客户端、超时、mock
│  └─ endings.py          # 拼图校验与结局判定
├─ prompts/  tagger.txt  npc.txt
├─ scenario/
│  ├─ world.json          # 区域、回合与时钟、数值上下限、单回合封顶 30、initial_flags
│  ├─ characters.json     # 四人角色卡
│  ├─ items.json
│  ├─ clues.json          # 8 张线索牌 + 解锁规则
│  ├─ tags.json           # 话题标签 × 数值表
│  ├─ timeline.json       # 8 回合脚本事件
│  └─ endings.json
├─ web/                   # 前端（Claude 负责）index.html style.css main.js assets/
├─ tests/                 # 第 8 节验收用例
└─ Dockerfile  requirements.txt  README.md
```

**角色与数值维度**：每个角色在 JSON 里声明自己的 `stats`，引擎不写死维度名。

| 角色 | id | 初始区域 | 数值（初始） | 随身物品 |
| --- | --- | --- | --- | --- |
| 周明远 | zhou | FRONT | guard 75 / guilt 15 / panic 25 | ITEM_APPROVAL_SLIP |
| 陈默（小陈） | chen | REAR | guard 60 / guilt 55 / panic 40 | ITEM_LOGBOOK（含旧工牌） |
| 林岚 | lin | MID | guard 65 / guilt 45 / panic 30 | ITEM_FAKE_TESTIMONY、录音笔 |
| 陆建军（老陆） | lu | MID | resolve（把握值）0，过线 70 | 警官证 |
| 玩家 | — | MID | — | 降噪耳机 |

**characters.json：老陆示例**（其余三人同结构，另有 `secret` 和 `disclosure_tiers`）

```json
{
  "id": "lu",
  "name": "陆建军",
  "start_zone": "MID",
  "stats": {"resolve": 0},
  "persona": "42 岁便衣民警，刚值完夜班，靠窗打盹。只认证据，不帮人推理，不管闲事。",
  "cover_story": "说自己是下班回家的普通人，亮明身份前不提警察。",
  "secret": null,
  "observe_hint": "夹克内袋露出一角深蓝色证件套",
  "speech_style": "短、冷、反问：“证据呢？”"
}
```

**tags.json：话题标签 × 数值**（每个标签对同一角色每轮只生效一次；老陆只算“听到”的部分）

| 标签 | 含义 | zhou | chen | lin | lu | 附加效果 |
| --- | --- | --- | --- | --- | --- | --- |
| `TAG_LANLAN` | 提到“岚岚” | — | guilt +10 | guard −25, guilt +15 | — | 对 lin 命中时解锁 C5 |
| `TAG_LIN_IDENTITY` | 告诉对方“林岚是老赵的女儿” | panic +10 | guilt +15, guard −10 | 同 TAG_LANLAN | resolve +20 | — |
| `TAG_LAST_WORDS` | 老赵喊“快跑”、从没怪过小陈 | panic +10 | guard −15, guilt +20 | 出示 C7 时 guilt −20, guard −30 | resolve +20 | 对 lin 出示 C7 → `lin_forgave = true`；若 `lin_target = chen` 则清空 |
| `TAG_ACCUSATION_CHEN` | 指责小陈害死师父 | guard −5 | guard +20, panic +25 | panic +10 | — | 陷阱：小陈会彻底闭嘴 |
| `TAG_BRIBE_10W` | 10 万、封口费、逼签伪证 | panic +35, guard +10 | guard −30, guilt +15 | guard −20 | resolve +20 | 对 lin 命中 → `lin_target = zhou` |
| `TAG_APPROVAL_SLIP` | 审批单、压下报告、匿名信栽赃 | panic +40 | guilt +15 | panic +15 | resolve +20 | — |
| `TAG_K14_HAZARD` | K14+200 隐患、明早首班车 | panic +25, guilt +10 | guilt +25, guard −15 | guilt −10 | resolve +20 | — |

数值规则：各来源先相加，再按**单回合 ±30 封顶**截断，最后限制在 0–100。老陆的 resolve 由标签（传闻）带来的部分**累计最多 45**，只靠嘴永远过不了线；见到实物（第 0 节第 4 条的定义）直接 +70，不受 ±30 封顶。

**clues.json：8 张线索牌**（牌跨循环保留，物品和状态每轮重置）

| ID | 名称 | 解锁规则（代码判定） | 随话出示时触发的标签 | 拼图 |
| --- | --- | --- | --- | --- |
| C0_EARPHONE_ECHO | 耳机串频残音：“……快跑……别告诉岚岚……江心隧道没断电……” | T2 开始时自动解锁，只有玩家听得到 | LAST_WORDS + LANLAN | — |
| C1_OFFICIAL_LIE | 官方通报 | 开局自带 | — | 干扰 |
| C2_HALF_TESTIMONY | 匿名半页问询表 | 与 lin 同区执行 OBSERVE(lin) | ACCUSATION_CHEN（对 chen） | 干扰 |
| C3_WHISPER_BRIBE | 车尾密谈 | T4 脚本密谈发生时，玩家在 REAR 且本回合为 WAIT（装睡） | BRIBE_10W | 拼图 2 |
| C4_APPROVAL_SLIP | 免停运审批单 + 背面快递底单 | 老陆 `INTERCEPTED` 周的毁证，或老陆执行 `DETAIN(zhou)` | APPROVAL_SLIP | 拼图 1 |
| C5_LIN_IDENTITY | 林岚的身份 | TAG_LANLAN 命中 lin | LIN_IDENTITY | — |
| C6_K14_HAZARD | 记录本数据 K14+200 / 0.3MΩ | chen 执行 HAND_OVER | K14_HAZARD | 拼图 4 |
| C7_BADGE_LAST_WORDS | 工牌刻字 | chen 执行 HAND_OVER | LAST_WORDS | 拼图 3 |

OBSERVE 其他人不给牌，只给一句笔记提示（`observe_hint`），例如“他一直按着工装内袋”“公文包夹层鼓起一块”。

## 3. 回合结算流程

每回合严格按下面的顺序执行，**玩家先动，NPC 后动**：NPC 决策时已经看到玩家这回合说的话和数值变化。第 8 节的通关路线依赖这个顺序，不要改。

回合与时钟：T1–T8 对应 23:52–23:59。玩家每回合提交可选的 `move` 加一个主动作：

| 主动作 | 参数 | 说明 |
| --- | --- | --- |
| `SPEAK_PRIVATE` | target, text, clue_id（可选） | 只有同区的 target 听得到；可附带出示 1 张牌 |
| `SPEAK_PUBLIC` | text, clue_id（可选） | 全车 4 人都听得到（出示的牌只有同区的人看得到） |
| `OBSERVE` | target | 观察同区目标 |
| `WAIT` | — | 静观；在 REAR 时表现为“缩在角落帽檐下假装睡死” |

拼图板走单独接口，不占回合。玩家不再有任何阻拦动作，阻拦只由老陆完成。

1. **回合开始事件**：仅 T2，播放耳机串频并解锁 C0（玩家在行动前就能看到）。
2. **玩家移动**：如有 `move`，立刻生效。
3. **玩家主动作**：标签 = Tagger(text) ∪ 所附牌的标签（第 2 节线索表）。私聊只对 target 生效，公开发言对听得到的每个人生效。对老陆出示 C6 或 C7 且玩家本轮持有 `ITEM_LOGBOOK` → 老陆 resolve +70。OBSERVE 按线索表解锁。
4. **查表算数值**：累加 → 单回合 ±30 封顶（老陆的实物 +70 除外）→ 老陆传闻部分累计不超过 45 → 限制 0–100；记录 delta，标记已用标签。
5. **脚本事件**：取 timeline.json 本回合事件，满足条件的产生广播、数值变化或强制动作。
6. **关键节点强制**（第 5 节列表）：小陈交出、林岚追周与对质、老陆亮证与追踪、老陆传唤。被强制的 NPC 本回合动作锁定。强制动作带来的数值变化（如林岚对质给周的 panic）在锁定时立即计入（同样受 ±30 封顶），之后的检查（包括老陆传唤）一律用更新后的数值。
7. **NPC 并发决策**：按第 6 节省调用规则挑出要调模型的 NPC，`asyncio.gather` 并发；被强制的只要台词和内心独白。
8. **规则校验**：逐个校验（第 5 节）。`REJECTED` 的带原因重决策 1 次，再失败降级 `STAY`。
9. **生效**，分三步：
    - 先结算执法：`DETAIN`、`INTERCEPTED`；被控制的 NPC 本回合其余动作作废。
    - 再结算非移动动作（对质、私聊、交出、毁证、拉闸）。结算完再检查一次老陆传唤，覆盖模型自主发起的对质把周推过 75 的情况；此时触发的传唤同样在移动前生效，周本回合的移动作废。
    - 最后按 **小陈 → 周 → 林岚 → 老陆** 的顺序结算移动。处于追踪状态的林岚、老陆移到周**本回合移动后**所在的区。
    - 产出给玩家的 events；玩家不在同区时只看得到“两人在低声说话”，听不到内容。
10. **回合末**：`PULL_BRAKE` 成功 → 立刻回档（结局 A）。T8 结束 → 如果拼图还没全对，但 C3、C4、C6、C7 都已解锁，先暂停（`awaiting_final_puzzle = true`），前端弹出「23:59 最后一刻：你已集齐全部真相，请完成拼图」，玩家确认后再跳向 00:00 判定；否则直接跳向 00:00，按第 5 节结局表判定。其余情况 `turn += 1`。

**拼图板**：玩家随时把牌放进 4 个槽位。四块全对 → `puzzle_solved = true`，只提示“你已洞悉真相，现在去这一轮里亲手改变它”，不直接结算。有错只提示“某块似乎只是表象”，不说哪块。

**回档**：保留 `clues_unlocked`、`puzzle_slots`、`loop_count`、`endings_seen`、`notebook`，其余按 scenario 重置。完成过至少 1 次循环后，开局可选“跳至 23:53”：直接应用 T1 的默认状态，从 T2 开始（先播耳机串频）。

## 4. 数据结构

状态分两类：**跨循环保留**的只有玩家的牌、拼图和笔记，其余都是**本轮状态**，回档即重置。

```python
@dataclass
class NPCState:
    id: str                      # zhou / chen / lin / lu
    zone: str                    # FRONT / MID / REAR
    stats: dict[str, int]        # zhou/chen/lin: guard, guilt, panic；lu: resolve
    hearsay_resolve: int         # 仅 lu：传闻带来的 resolve 累计，上限 45
    items: list[str]
    used_tags: set[str]          # 本轮已生效的标签
    memory: list[str]            # 私有记忆：只含亲耳听到/亲眼看到的事，最多 12 条
    tracking: str | None         # lin / lu 追踪的对象，通常是 "zhou"
    detained: bool               # 仅 zhou：被老陆控制后不再行动
    forced_action: dict | None   # 本回合被代码锁定的动作

@dataclass
class GameState:
    session_id: str
    # ── 跨循环保留 ──
    loop_count: int
    clues_unlocked: list[str]
    puzzle_slots: dict[str, str | None]   # "1".."4" → clue_id
    puzzle_solved: bool
    notebook: list[str]          # 提示句、偷听到的原话
    endings_seen: list[str]
    # ── 本轮状态 ──
    turn: int                    # 1..8 → 23:52..23:59
    player_zone: str             # 开局 MID
    player_items: list[str]      # 本轮拿到的实物，如 ITEM_LOGBOOK
    player_waited: bool
    awaiting_final_puzzle: bool  # 初始 False
    npcs: dict[str, NPCState]
    flags: dict
    log: list[LogEntry]
```

**flags**：`approval_slip_status`（`HELD` / `DESTROYED` / `SECURED`）、`logbook_handed`、`lin_target`（`chen` / `zhou` / `null`）、`lin_forgave`、`lu_active`、`t4_whisper_done`。

**初始值**（写在 `world.json` 的 `initial_flags`，每次回档按此重置）：`approval_slip_status = "HELD"`、`logbook_handed = false`、**`lin_target = "chen"`**（T5/T6 脚本依赖它，不能初始化成 null，否则林岚不会动）、`lin_forgave = false`、`lu_active = false`、`t4_whisper_done = false`。

**NPC 输出的动作 JSON**（模型只允许输出这一个对象）

```json
{
  "thought": "内心独白，一两句，只在透视面板显示",
  "speech": "说出口的话，可为空字符串，最多 60 字",
  "speech_to": "player | zhou | chen | lin | lu | all | none",
  "action": "STAY | MOVE | WHISPER | HIDE_OR_DESTROY | CONFRONT | PULL_BRAKE",
  "target": "FRONT | MID | REAR | zhou | chen | lin | lu | ITEM_xxx | null"
}
```

`action` 只能从本回合传给模型的 `allowed_actions` 里选。`HAND_OVER`、`DETAIN` 只由代码强制，从不交给模型选。

**LogEntry**（透视面板逐条展示）

```json
{
  "turn": 7, "clock": "23:58", "npc": "zhou",
  "tags_hit": ["TAG_K14_HAZARD"],
  "delta": {"panic": 25, "guilt": 10},
  "stats_after": {"guard": 85, "guilt": 25, "panic": 80},
  "thought": "...", "speech": "...",
  "proposed": {"action": "HIDE_OR_DESTROY", "target": "ITEM_APPROVAL_SLIP"},
  "verdict": "REJECTED", "reason": "只能在车尾销毁",
  "retry": {"action": "MOVE", "target": "REAR", "verdict": "PASS"},
  "forced": false, "llm_ms": 2310, "json_repaired": false
}
```

## 5. 规则引擎、脚本事件与结局

规则层是确定性代码，输入动作和状态，输出 `PASS` / `REJECTED` / `INTERCEPTED` 及原因。传给模型的 `allowed_actions` **不按区域预先过滤**，让模型有机会提出“在车头毁证”然后被驳回，透视面板才有可看的驳回和重决策。

**校验清单**（“老陆在场”= 老陆与行动者同区；“老陆已亮证”= `lu_active`）

| 动作 | 出现在 allowed_actions 的条件 | 校验规则 → 结果 |
| --- | --- | --- |
| `STAY` | 总是 | → PASS |
| `MOVE(zone)` | 总是 | zone 合法且不是当前区 → PASS；否则 REJECTED |
| `WHISPER(t)` | 同区有其他 NPC | t 同区 → PASS，双方写入私有记忆；玩家同区且 WAIT → 玩家也听到原话 |
| `CONFRONT(t)` | 同区有其他人 | t 同区 → PASS，t 的 panic +20、guilt +10（计入封顶）；否则 REJECTED“对方不在这节车厢” |
| `HIDE_OR_DESTROY(item)` | 持有该物品且 panic ≥ 65 | 不在 REAR → REJECTED“只能在车尾垃圾箱销毁”；在 REAR 且老陆已亮证并在场 → **INTERCEPTED**：解锁 C4，`SECURED`，zhou `detained`；否则 PASS，`DESTROYED`（老陆未亮证时，周不知道他是警察） |
| `PULL_BRAKE` | panic ≥ 90 | 不在 FRONT → REJECTED“拉环只在车头”；在 FRONT 且老陆在场（**不论是否亮证**，公共安全例外）→ INTERCEPTED，该 NPC panic −20；否则 PASS → 回档 |
| `HAND_OVER(item)` | 从不给模型 | 见下方强制节点 |
| `DETAIN(zhou)` | 从不给模型 | 见下方强制节点 |

**关键节点强制**（第 3 节第 6 步，按顺序检查）

1. **小陈交出**：chen guilt ≥ 75、guard ≤ 35、玩家同区 → 强制 `HAND_OVER(ITEM_LOGBOOK)`：物品进 `player_items`，解锁 C6、C7，`logbook_handed = true`。
2. **老陆见到实物**：`logbook_handed` 且 chen 与 lu 同区 → lu resolve +70（每轮一次）。玩家出示实物的 +70 已在第 3 步结算。
3. **老陆亮证**：lu resolve ≥ 70 且未亮证 → `lu_active = true`，`tracking = zhou`，产生“亮出警官证”事件。此后每回合跟到周所在区。
4. **林岚追周**：`lin_target = zhou` → `tracking = zhou`；与 zhou 同区时强制 `CONFRONT(zhou)`，zhou 另加 panic +30（计入封顶）。
5. **老陆传唤**：`lu_active`、lu 与 zhou 同区、`logbook_handed`、lin 与 zhou 同区且（`lin_target = zhou` 或 `lin_forgave`）、zhou panic ≥ 75 → **当回合**强制 `DETAIN(zhou)`：解锁 C4，`SECURED`，zhou `detained`。

**timeline.json 脚本事件**（公放每回合都重复同一句报站：“7 号线末班车，前方到站：江心站，列车即将驶入江心隧道……”）

| 回合 | 时钟 | 事件 | 代码效果 |
| --- | --- | --- | --- |
| T1 | 23:52 | 驶入江心隧道，暴雨，车门锁死 | 无 |
| T2 | 23:53 | 回合开始：玩家耳机里 3 秒电流串频 | 解锁 C0（只有玩家听到） |
| T3 | 23:54 | 列车剧烈晃动 | zhou 若 panic < 65 且未被控制：强制 `MOVE(REAR)` |
| T4 | 23:55 | 车尾灯管闪烁 | 若 zhou、chen 都在 REAR：玩家在 REAR 且未 WAIT → 密谈取消（“两人看了你一眼，闭上了嘴”）；否则脚本密谈发生（台词写死），`t4_whisper_done`；玩家在 REAR 且 WAIT → 解锁 C3 |
| T5 | 23:56 | 车窗雾气上出现“还没修好” | zhou 若 panic < 65 且未被控制：强制 `MOVE(FRONT)`；lin 若 `lin_target = chen`：强制 `MOVE(REAR)` |
| T6 | 23:57 | 列车提速 | lin 与 chen 同在 REAR 且 `lin_target = chen` → 强制 `CONFRONT(chen)`，chen 另加 guard +20、panic +25 |
| T7 | 23:58 | 红色警示灯闪烁 | 无 |
| T8 | 23:59 | 回合结束时时钟跳向 00:00 | 结局判定 |

**endings.json：结局判定**（T8 结束时自上而下匹配）

| 结局 | 条件 | 画面状态 |
| --- | --- | --- |
| A 回档 | `PULL_BRAKE` 成功（立刻触发），或 T8 结束时 `puzzle_solved = false`（含 23:59 暂停确认后仍未全对） | 红警电弧 → 黑屏 → 时钟 23:59 倒转回 23:52 |
| D 真结局「早班车停运通知」 | `puzzle_solved` + `SECURED` + `logbook_handed` + `lin_forgave` | 高亮态：雨停、金白晨光、屏幕“00:00 · 终点站 · 安全抵达” |
| C 「正义迟到」 | `puzzle_solved` + `SECURED` + `logbook_handed`，`lin_forgave = false` | 正常态：雨夜站台，玻璃上有红蓝警灯倒影 |
| B 「沉入暗影的真相」 | `puzzle_solved`，其余情况 | 昏暗态：铅灰雨夜、频闪冷灯 |

结局 B、C、D 各调用一次模型，让四人基于本轮私有记忆各说一句告别独白；结局旁白和标题写死在 JSON。

## 6. LLM 层

模型只做两件事：**给玩家的话打标签**、**替 NPC 选动作并说台词**。数值、线索、胜负全部由代码决定。

### 6.1 Tagger

1. 先跑关键词表（tags.json 里每个标签配 `keywords`，如 `TAG_BRIBE_10W`: “10万”“十万”“封口费”“手术费”“伪证”）。命中就直接用，**不调模型**。
2. 没命中且文本 ≥ 6 个字，才调 `TAGGER_MODEL` 做多选题：输入玩家原话 + 7 个标签的一句话定义，只输出 `{"tags": [...]}`。
3. 模型返回了不存在的标签就丢掉；解析失败就当作空列表。

### 6.2 哪些 NPC 这回合要调模型（省额度的关键）

满足任一条才调：与玩家同区；玩家公开发言；被强制动作（需要台词）；本回合有脚本事件涉及它；panic ≥ 65（在密谋动作）。其余 NPC 走脚本默认动作，没有就 `STAY`，前端只显示动作不显示台词。目标：**平均每回合 ≤ 3 次调用**。

老陆另有一条：未亮证时，只有玩家直接对他说话才调模型（其余时间靠窗打盹，前端显示动作即可）；亮证后的移动和执法都是代码强制，只在亮证、拦截、传唤这几个节点调模型要一句台词。老陆没有 `secret` 和 `disclosure_tiers`，prompt 里的“心态”由 resolve 翻译：0–44 =“你觉得这人在说胡话，没有证据你不会表态”，45–69 =“你开始留意，但还缺实物”。他永远不替玩家分析案情。

### 6.3 NPC prompt 模板（prompts/npc.txt）

system 部分由代码拼装，每回合重新生成：

```
你在扮演《23:59》里的{name}。{persona}
你对外的说法：{cover_story}
你心里知道但不愿说的事：{secret}
此刻你可以松口承认的内容：{disclosable}      ← 按当前数值分档给出，没达标就写“无，继续隐瞒”
你现在的心态：{state_words}                  ← 把数字翻译成话，例如 panic 70 = “你很慌，只想毁掉证据”
你在{zone}。同一节车厢的人：{others}。
你记得的事（只有这些）：{memory}
本回合可选动作：{allowed_actions}
{retry_hint}                                  ← 仅重决策时：“你刚才想{action}，但{reason}。请重新选择。”
{forced_hint}                                 ← 仅强制时：“你已决定{action}，只需写台词和心理活动。”
只输出一个 JSON 对象，字段为 thought / speech / speech_to / action / target，不要输出任何其他文字。
```

user 部分是本回合它看到的事（玩家对它说的话、公开发言、同区发生的动作）。**不传历史对话**，只传 `memory`，这就是“短循环防上下文衰减”。

“分档可透露”是防剧透的主要手段：如 chen 在 guard > 35 时 `disclosable` 为空，guard ≤ 35 时放出“收过钱、不是师父的错”，交出后才放出工牌内容。分档写在 characters.json 的 `disclosure_tiers`。

### 6.4 容错

- 请求 `temperature` 0.7，`max_tokens` 300，超时 `LLM_TIMEOUT` 秒。
- 解析：去掉 Markdown 代码块包裹 → 截取第一个 `{` 到最后一个 `}` → `json.loads` → 校验字段和枚举。
- 失败则带上“你上次的输出不是合法 JSON”重试 1 次；再失败或超时 → 降级为 `{"speech": "……", "action": "STAY"}`，日志标 `json_repaired` / `fallback`。游戏绝不因模型崩溃。
- `LLM_MOCK=1`：所有调用返回预设 JSON（按 NPC 轮换台词），用于前端联调和跑测试，不消耗额度。

## 7. 前后端 API 契约

前端只通过下面 5 个接口和后端打交道，全部 JSON。只要字段不变，前后端可以各自开发；字段要改先在这份文档里改。

| 方法 | 路径 | 请求 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/session` | `{}` | `{session_id, view}` |
| POST | `/api/turn` | 见下方 | `{events, view, inspector}` |
| POST | `/api/puzzle` | `{session_id, slots: {"1": "C4_...", "2": null, ...}, confirm_midnight?: bool}` | `{solved, hint}`；带 confirm_midnight 时另返回 `events, view` |
| POST | `/api/restart` | `{session_id, skip_to_t2: bool}` | `{view}` |
| GET | `/api/state?session_id=` | — | `{view, inspector}` |

请求头可带 `X-User-Token`：玩家自己的魔搭令牌，有则优先使用，只存在内存里不落盘。

**23:59 暂停**：`/api/turn` 返回的 `view.awaiting_final_puzzle = true` 时，前端停在 23:59 并打开拼图板，此时不允许提交新回合。玩家放好牌后调用 `/api/puzzle` 并带 `"confirm_midnight": true`，接口返回 `{solved, hint, events, view}`，`events` 里是 `midnight`（带结局）或 `loop_reset`。确认时仍未全对 → 回档。

**`/api/turn` 请求**

```json
{
  "session_id": "...",
  "move": "MID",
  "action": {"type": "SPEAK_PRIVATE", "target": "lu",
             "text": "这是小陈刚交给我的检修记录本，你看看。",
             "clue_id": "C6_K14_HAZARD"}
}
```

`action.type` 为 `SPEAK_PRIVATE`（target + text，可选 clue_id）、`SPEAK_PUBLIC`（text，可选 clue_id）、`OBSERVE`（target）、`WAIT`。`move` 可为 `null`。text 可以为空但带 clue_id，即“只亮牌不说话”。非法请求（如对不同区的人私聊）返回 400 和一句中文提示，不消耗回合。

**`view`：界面当前快照**

```json
{
  "turn": 5, "clock": "23:56", "loop_count": 3,
  "player": {"zone": "MID", "items": ["ITEM_LOGBOOK"]},
  "npcs": [
    {"id": "zhou", "name": "周明远", "zone": "FRONT",
     "stats": {"guard": 85, "guilt": 25, "panic": 55}, "mood": "强作镇定", "status": null},
    {"id": "lu", "name": "陆建军", "zone": "FRONT",
     "stats": {"resolve": 70}, "mood": "亮证追踪", "status": "TRACKING_ZHOU"}
  ],
  "clues": [{"id": "C3_WHISPER_BRIBE", "name": "车尾密谈", "text": "...", "image": "assets/clues/c3.png"}],
  "puzzle": {"slots": {"1": null, "2": "C3_WHISPER_BRIBE", "3": "C7_BADGE_LAST_WORDS", "4": "C6_K14_HAZARD"}, "solved": false},
  "notebook": ["他一直按着工装内袋"],
  "can_skip_to_t2": true,
  "awaiting_final_puzzle": false,
  "ending": null
}
```

`status` 取值：`null` / `TRACKING_ZHOU` / `DETAINED`。

**`events`：本回合发生的事，按播放顺序排列**，前端逐条做动画。每条是 `{kind, actor, target, zone, text}`，`kind` 取值：

- `broadcast`：公放报站、车窗雾字等环境事件
- `earphone`：T2 耳机串频（只有玩家）
- `speech`：NPC 说话（玩家听得到的才下发）
- `whisper_seen` / `whisper_heard`：看到两人低声说话 / 装睡偷听到的原话
- `move` / `confront` / `hand_over` / `destroy` / `brake`：物理动作
- `badge`：老陆亮证；`intercepted` / `detain`：老陆拦截或传唤
- `clue_unlocked`：解锁线索牌，`target` 为 clue_id
- `loop_reset`：回档，前端播放电弧、黑屏、时钟倒转
- `midnight`：T8 结束跨入 00:00，带 `ending`

**过场动画不定时长**：提交回合后立刻播放隧道飞掠循环动画，直到接口返回再收尾跳钟（最短约 1.2 秒）。模型延迟还没实测，不能按 2–3 秒写死。

**`inspector`**：本轮全部 LogEntry（第 4 节格式）加上每个 NPC 的 `memory`。透视面板是给评委看工程的，可以剧透，前端默认收起。

**`ending`**：`{id: "B"|"C"|"D", title, narration, visual: "dim"|"normal"|"bright", farewells: [{npc, text}]}`。结局 A 不走 `ending`，只发 `loop_reset`。

## 8. 开发顺序与验收

先用 `LLM_MOCK=1` 把整套规则跑通、测试全绿，再接真模型。规则错了换模型也救不回来。

| 日期（太平洋时间） | Codex | Claude（前端） |
| --- | --- | --- |
| 11/26 | scenario JSON 录入；state / rules / turn / endings；mock 模式；下方测试 1–9、11–14 全绿 | 车厢主界面静态稿：水下隧道车窗、三区俯视条、四人状态卡、线索牌、拼图板、点阵时钟 |
| 11/27 | 5 个 API 接口；tagger + npc + JSON 修复；实测模型延迟 | 对接 mock API；回合过场、事件动画 |
| 11/28 | 接真模型调 prompt；魔搭创空间部署跑通 | 透视面板、回档时钟倒转、三种结局光影、跳至 23:53 |
| 11/29 | 修 bug，按试玩反馈调数值 | 试玩、打磨、文案替换 |
| 11/30 | 开源仓库 + README（含本地 / vLLM 部署说明） | 录演示视频、创作手记 |

**验收测试（tests/，全部在 mock 模式下跑）**

- [ ] 1. **真结局一轮通关**：按下方「第 3 轮路线」，T8 结束得到结局 D
- [ ] 2. **第 2 轮取牌**：按下方「第 2 轮路线」，本轮结束时已解锁 C3、C6、C7
- [ ] 3. **毁证被驳回再重决策**：zhou 在 FRONT 且 panic ≥ 65 时提交销毁 → REJECTED → 重决策 `MOVE(REAR)`
- [ ] 4. **老陆未亮证时周照样能毁证**：zhou 与未亮证的 lu 同在 REAR，销毁 → `DESTROYED`；若 `puzzle_solved`，T8 结束得到结局 B
- [ ] 5. **公共安全例外**：zhou 在 FRONT 且 panic ≥ 90 拉闸，lu 未亮证但在场 → INTERCEPTED，没有回档
- [ ] 6. **只靠嘴过不了线**：对 lu 说完全部 5 个会加 resolve 的标签 → resolve = 45，未亮证
- [ ] 7. **装睡偷听**：T3 结束时玩家在 REAR、T4 选 WAIT → 解锁 C3；T4 在 REAR 说话 → 密谈取消、无 C3
- [ ] 8. **数值封顶**：一句话同时命中 BRIBE 和 APPROVAL_SLIP，zhou panic 只涨 30
- [ ] 9. **无人干预的第一轮**：连续 8 次 WAIT → T3 zhou 去车尾、T5 zhou 回车头且 lin 去车尾、T6 lin 对质 chen、T8 回档，保留 C0、C1
- [ ] 10. **模型全挂**：mock 返回非法 JSON 或超时 → NPC 降级 STAY，游戏继续
- [ ] 11. **只拼图不行动**：开局就把四块拼对后连续 WAIT → T8 结束得到结局 B，不是 D
- [ ] 12. **T8 才拿到 C4**：T8 内老陆传唤解锁 C4，拼图 1 槽还空 → 返回 `awaiting_final_puzzle = true`，不回档；放入 C4 并确认 → 按本轮状态得到 C 或 D
- [ ] 13. **林岚对质当回合触发传唤**：zhou panic 65，老陆已亮证且同区，记录本已交出；玩家 WAIT，林岚强制对质把 zhou 推到 ≥ 75 → **同一回合** DETAIN
- [ ] 14. **初始化**：新开局和每次回档后 `lin_target == "chen"`

**第 2 轮路线**（从“跳至 23:53”开始，已持有 C0、C1）

1. T2：移到 REAR，对 chen 说师父喊你快跑并亮 C0 → chen guard 45、guilt 85（两个标签合计受封顶）。
2. T3：WAIT。zhou 走到 REAR。
3. T4：WAIT（装睡）→ 密谈发生，解锁 C3。
4. T5：对 chen 亮 C3 → guard 15、guilt 100 → 强制交出，解锁 C6、C7。
5. T6–T8：自由探索。没有 C4，拼图不全，T8 结束回档。玩家在拼图板上先放好 2–4 槽。

**第 3 轮路线**（测试 1；从“跳至 23:53”开始，已持有 C0、C3、C6、C7，拼图 2–4 槽已填）

1. T2：移到 REAR，对 chen 亮 C3 → guard 30、guilt 70。
2. T3：对 chen 亮 C7 → guard 15、guilt 90 → 强制交出，玩家拿到 `ITEM_LOGBOOK`。zhou 走到 REAR。
3. T4：移到 MID，对 lu 亮 C6（手里有实物）→ resolve 70 → 亮证，回合末跟到 REAR。密谈照常发生，玩家不在场。
4. T5：对 lin 亮 C7 并说出 10 万封口 → `lin_forgave = true`，`lin_target = zhou`。zhou 脚本回 FRONT，lin、lu 按顺序跟到 FRONT。
5. T6：移到 FRONT，公开说出审批单的事；lin 强制对质 zhou → zhou panic 55（封顶）。
6. T7：公开说出 K14+200 和明早首班车 → zhou panic 85 ≥ 75 → lu 当回合 `DETAIN`，解锁 C4，`SECURED`。
7. T8：把 C4 放进拼图 1 槽 → `puzzle_solved`；WAIT。时钟跳向 00:00 → 结局 D。

第 3 轮留有 1 回合余量（T8）；如果 T2 一句话同时亮 C3 又提“快跑”，小陈当回合就会交出，还能再省 1 回合。
