# 云笺 Vellum

云笺帮助普通人把脑海中模糊的画面整理成可确认的视觉意图草稿，再转译为文生图模型能够理解的 Prompt。

当前版本专注文生图，不包含文生视频或图生图能力。前端是一套可直接体验的灵感对话工作台；API 保持无状态，前端只需保存并回传 `InspirationState`，暂时不引入数据库或账号系统。

## 产品流程

1. 用户用自然语言描述脑海中的画面，并选择创作模式。
2. 云笺复述理解，生成包含意图、事实、视觉表达和约束的草稿。
3. 只有存在会明显改变画面的歧义时，返回一个关键问题；整个流程最多两个问题。
4. 用户可以选择答案、交给云笺决定，或用自然语言修订草稿。
5. 每轮提供 4 条可选灵感；可以整批更换，采用一条后会根据新草稿补回 4 条。
6. 草稿确认后，云笺将其编译为通用中文文生图 Prompt 和负面 Prompt。

三种创作模式：

- `faithful`：忠实还原，尽量少补充。
- `collaborative`：协同创作，适度建议，默认模式。
- `exploratory`：自由探索，保留约束并主动发挥，不用问题打断用户。

## 本地启动

需要 Python 3.11 或更新版本，以及 Node.js 18 或更新版本。

后端：

```powershell
cd D:\Vellum
python -m pip install -r requirements.txt
copy .env.example .env
python -m server.main
```

前端（另开一个终端）：

```powershell
cd D:\Vellum\client
npm install
npm run dev
```

也可以直接双击 `start.bat`，它会同时启动前后端。

- 聊天页面：`http://localhost:5173`
- 接口服务：`http://localhost:3001`
- 接口文档：`http://localhost:3001/docs`

没有配置 `LLM_API_KEY` 或设置 `USE_MOCK=true` 时，会使用确定性的本地演示响应。实时模型调用失败会返回错误，不会伪装成 Mock 结果。

## 聊天工作台

- 左侧：可收起、可调整宽度的历史灵感栏；最近 24 次会话保存在当前浏览器中，并可逐条删除。
- 中间：自然语言对话、非阻塞的补全灵感、一次一个的关键选择，以及最终 Prompt 输出。
- 右侧：按需打开的视觉意图抽屉，可调整宽度，并具体列出用户原意与云笺建议。
- 输入框：`Enter` 发送，`Shift + Enter` 换行；生成结果支持分别复制或一键复制全部提示词。
- 小屏：自动收起辅助区域，通过顶部按钮随时新建或查看草稿。

页面沿用云笺的青白纸感、柳叶色和低对比网格，并针对应用型工作台重新安排了信息密度。参考用的 `D:\UI练习\Linear-01` 未被修改。

## API

### 开始一次灵感整理

`POST /api/inspirations`

```json
{
  "idea": "雨夜里撑红伞的女孩，街道热闹但她显得很孤独",
  "mode": "collaborative"
}
```

返回完整的 `InspirationState`。`inspiration_hints` 固定提供 4 条可忽略、可采用的补全灵感；当 `status` 为 `needs_input` 时，`question` 中包含一个关键问题和 2 至 3 个选项；为 `ready` 时可以直接编译 Prompt。

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

### 更换一批灵感

`POST /api/inspirations/hints/refresh`

请求体包含当前完整 `state`，以及前端最近展示过的 `excluded_examples`。接口只更新 `inspiration_hints`，不会改变草稿；始终返回 4 条建议。

### 编译 Prompt

`POST /api/inspirations/compile`

```json
{
  "state": {}
}
```

返回 `prompt`、`negative_prompt` 和面向用户的 `creative_summary`。用户也可以跳过未回答的问题，直接把当前状态提交到这个接口。

## 代码结构与调试边界

- `server/models.py`：前后端接口的数据契约和字段限制。
- `server/routes/inspiration.py`：HTTP 路由，只负责请求转换和错误状态码。
- `server/services/inspiration_service.py`：状态流转、问题上限、灵感刷新和 Mock 行为。
- `server/services/model_gateway.py`：模型供应商调用、JSON 解析及结构修复；不包含产品规则。
- `server/prompts.py`：模型行为和输出要求，修改产品策略时从这里开始检查。
- `client/src/api.ts`：前端全部接口入口。
- `client/src/types.ts`：与 `server/models.py` 对应的前端类型。
- `client/src/App.tsx`：页面状态、历史记录和交互编排；后端仍是完整 `InspirationState` 输入输出。

调试主链路为 `App.tsx → api.ts → routes/inspiration.py → inspiration_service.py → model_gateway.py`。接口报字段错误先对照 `models.py` 与 `types.ts`；模型返回异常再检查 `prompts.py` 和 `model_gateway.py`。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server
cd client
npm run build
```
