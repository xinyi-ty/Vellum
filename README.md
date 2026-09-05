# 云笺 Vellum

云笺帮助普通人把脑海中模糊的画面整理成可确认的视觉意图草稿，再转译为文生图模型能够理解的 Prompt。

当前版本专注文生图，不包含前端、文生视频或图生图能力。API 保持无状态，未来前端只需保存并回传 `InspirationState`，无需先引入数据库或账号系统。

## 产品流程

1. 用户用自然语言描述脑海中的画面，并选择创作模式。
2. 云笺复述理解，生成包含意图、事实、视觉表达和约束的草稿。
3. 只有存在会明显改变画面的歧义时，返回一个关键问题；整个流程最多两个问题。
4. 用户可以选择答案、交给云笺决定，或用自然语言修订草稿。
5. 草稿确认后，云笺将其编译为通用中文文生图 Prompt 和负面 Prompt。

三种创作模式：

- `faithful`：忠实还原，尽量少补充。
- `collaborative`：协同创作，适度建议，默认模式。
- `exploratory`：自由探索，保留约束并主动发挥，不用问题打断用户。

## 本地启动

需要 Python 3.11 或更新版本。

```powershell
cd D:\Vellum
python -m pip install -r requirements.txt
copy .env.example .env
python -m server.main
```

也可以双击 `start.bat`。服务默认运行于 `http://localhost:3001`，交互式接口文档位于 `http://localhost:3001/docs`。

没有配置 `LLM_API_KEY` 或设置 `USE_MOCK=true` 时，会使用确定性的本地演示响应。实时模型调用失败会返回错误，不会伪装成 Mock 结果。

## API

### 开始一次灵感整理

`POST /api/inspirations`

```json
{
  "idea": "雨夜里撑红伞的女孩，街道热闹但她显得很孤独",
  "mode": "collaborative"
}
```

返回完整的 `InspirationState`。当 `status` 为 `needs_input` 时，`question` 中包含一个关键问题和 2 至 3 个选项；为 `ready` 时可以直接编译 Prompt。

### 回答关键问题

`POST /api/inspirations/answer`

请求体包含上一步返回的完整 `state`，以及以下三种答案之一：

```json
{"answer": {"option_id": "wide"}}
```

```json
{"answer": {"text": "希望从街对面隔着人群观察她"}}
```

```json
{"answer": {"use_ai_decide": true}}
```

### 用自然语言修订草稿

`POST /api/inspirations/revise`

```json
{
  "state": {},
  "instruction": "红伞必须保留，人物不要哭泣"
}
```

实际请求需要把 `{}` 替换为当前完整 `InspirationState`。

### 编译 Prompt

`POST /api/inspirations/compile`

```json
{
  "state": {}
}
```

返回 `prompt`、`negative_prompt` 和面向用户的 `creative_summary`。用户也可以跳过未回答的问题，直接把当前状态提交到这个接口。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server
```
