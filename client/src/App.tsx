import {
  ArrowUp,
  Check,
  ChevronDown,
  Clipboard,
  Menu,
  PanelRight,
  Plus,
  X,
} from "lucide-react";
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { answerQuestion, compilePrompt, refreshInspirationHints, reviseDraft, startInspiration } from "./api";
import type {
  CompiledPrompt,
  CreationMode,
  DraftStatement,
  InspirationHint,
  InspirationState,
  KeyQuestion,
} from "./types";

type BusyAction = "send" | "answer" | "compile" | "refresh" | null;

interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  text?: string;
  question?: KeyQuestion | null;
  hints?: InspirationHint[];
  sceneContext?: DraftStatement | null;
  promptResult?: CompiledPrompt;
  answered?: boolean;
}

interface SavedSession {
  id: string;
  title: string;
  updatedAt: string;
  mode: CreationMode;
  state: InspirationState;
  messages: ConversationMessage[];
}

const STORAGE_KEY = "vellum.inspiration-sessions.v1";

const modes: Array<{ value: CreationMode; label: string; description: string }> = [
  { value: "faithful", label: "忠实还原", description: "只整理你明确说出的内容，建议不写入草稿。" },
  { value: "collaborative", label: "协同创作", description: "给出可选灵感，只在关键分歧处问一次。" },
  { value: "exploratory", label: "自由探索", description: "保留核心意图，其余交给云笺大胆延展。" },
];

const seeds = [
  "雨夜里，一个撑红伞的人穿过霓虹街道",
  "云海之上的古城，清晨第一束阳光刚刚照进来",
  "一只鲸鱼游过月光下的森林，安静而梦幻",
];

function uid() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

function loadSessions(): SavedSession[] {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (!value) return [];
    const parsed = JSON.parse(value) as SavedSession[];
    return Array.isArray(parsed)
      ? parsed.map((session) => ({
          ...session,
          state: { ...session.state, inspiration_hints: session.state.inspiration_hints ?? [] },
        }))
      : [];
  } catch {
    return [];
  }
}

function formatSessionTime(value: string) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function App() {
  // 会话只保存在当前浏览器；后端保持无状态，所有接口都接收并返回完整 state。
  const initialSessions = useRef(loadSessions()).current;
  const initialSession = initialSessions[0] ?? null;
  const [mode, setMode] = useState<CreationMode>(initialSession?.mode ?? "collaborative");
  const [input, setInput] = useState("");
  const [state, setState] = useState<InspirationState | null>(initialSession?.state ?? null);
  const [messages, setMessages] = useState<ConversationMessage[]>(initialSession?.messages ?? []);
  const [sessions, setSessions] = useState<SavedSession[]>(initialSessions);
  const [sessionId, setSessionId] = useState(initialSession?.id ?? uid());
  const [busy, setBusy] = useState<BusyAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [sidebarWidth, setSidebarWidth] = useState(248);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftWidth, setDraftWidth] = useState(380);
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const modeMeta = modes.find((item) => item.value === mode)!;
  const shellStyle = {
    "--sidebar-width": `${sidebarOpen ? sidebarWidth : 0}px`,
    "--draft-width": `${draftWidth}px`,
  } as CSSProperties;

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 24)));
  }, [sessions]);

  useEffect(() => {
    if (!state || messages.length === 0) return;
    const saved: SavedSession = {
      id: sessionId,
      title: state.original_idea.slice(0, 24),
      updatedAt: new Date().toISOString(),
      mode,
      state,
      messages,
    };
    setSessions((current) => [saved, ...current.filter((item) => item.id !== sessionId)].slice(0, 24));
  }, [messages, mode, sessionId, state]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (timeline) timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    function closeMenu(event: MouseEvent) {
      if (!(event.target as Element).closest?.(".mode-picker")) setModeMenuOpen(false);
    }
    document.addEventListener("mousedown", closeMenu);
    return () => document.removeEventListener("mousedown", closeMenu);
  }, []);

  function resetConversation() {
    setSessionId(uid());
    setState(null);
    setMessages([]);
    setInput("");
    setMode("collaborative");
    setError(null);
    setCopied(null);
    setDraftOpen(false);
    textareaRef.current?.focus();
  }

  function openSession(session: SavedSession) {
    setSessionId(session.id);
    setState(session.state);
    setMessages(session.messages);
    setMode(session.mode);
    setInput("");
    setError(null);
    if (window.innerWidth < 760) setSidebarOpen(false);
  }

  function deleteSession(id: string) {
    setSessions((current) => current.filter((session) => session.id !== id));
    if (id === sessionId) resetConversation();
  }

  function appendAssistant(nextState: InspirationState) {
    setMessages((current) => [
      ...current,
      {
        id: uid(),
        role: "assistant",
        text: nextState.understanding,
        question: nextState.question,
        hints: nextState.inspiration_hints ?? [],
        sceneContext: nextState.draft.scene_context,
      },
    ]);
  }

  async function submitIdea() {
    const value = input.trim();
    if (!value || busy) return;
    setError(null);
    setInput("");
    setMessages((current) => [...current, { id: uid(), role: "user", text: value }]);
    setBusy("send");
    try {
      const nextState = !state
        ? await startInspiration(value, mode)
        : state.status === "needs_input"
          ? await answerQuestion(state, { text: value })
          : await reviseDraft(state, value);
      setState(nextState);
      appendAssistant(nextState);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接失败，请稍后重试。");
    } finally {
      setBusy(null);
    }
  }

  async function chooseAnswer(
    messageId: string,
    label: string,
    answer: { option_id: string } | { use_ai_decide: true },
  ) {
    if (!state || busy) return;
    setError(null);
    setBusy("answer");
    setMessages((current) => [
      ...current.map((message) => message.id === messageId ? { ...message, answered: true } : message),
      { id: uid(), role: "user", text: label },
    ]);
    try {
      const nextState = await answerQuestion(state, answer);
      setState(nextState);
      appendAssistant(nextState);
    } catch (reason) {
      setMessages((current) => current.map((message) =>
        message.id === messageId ? { ...message, answered: false } : message,
      ));
      setError(reason instanceof Error ? reason.message : "连接失败，请稍后重试。");
    } finally {
      setBusy(null);
    }
  }

  async function createPrompt() {
    if (!state || busy) return;
    setError(null);
    setBusy("compile");
    try {
      const result = await compilePrompt(state);
      setMessages((current) => [...current, { id: uid(), role: "assistant", promptResult: result }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接失败，请稍后重试。");
    } finally {
      setBusy(null);
    }
  }

  async function copyText(id: string, value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(id);
    window.setTimeout(() => setCopied(null), 1600);
  }

  async function useHint(hint: InspirationHint) {
    if (!state || busy) return;
    setError(null);
    setBusy("send");
    setMessages((current) => [...current, { id: uid(), role: "user", text: hint.example }]);
    try {
      // “采用”是一项真实的草稿修订，而不是只把文字暂存到输入框。
      const nextState = await reviseDraft(state, hint.example);
      setState(nextState);
      appendAssistant(nextState);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接失败，请稍后再试。");
    } finally {
      setBusy(null);
    }
  }

  async function refreshHints(messageId: string) {
    if (!state || busy) return;
    setError(null);
    setBusy("refresh");
    // 请求模型避开最近看过的内容，同时遵守接口的 40 条上限，避免长对话产生 422。
    const excludedExamples = messages
      .flatMap((message) => message.hints ?? [])
      .map((hint) => hint.example)
      .slice(-40);
    try {
      const nextState = await refreshInspirationHints(state, excludedExamples);
      setState(nextState);
      setMessages((current) => current.map((message) =>
        message.id === messageId ? { ...message, hints: nextState.inspiration_hints } : message,
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法更换灵感，请稍后再试。");
    } finally {
      setBusy(null);
    }
  }

  function beginResize(kind: "sidebar" | "draft", event: React.PointerEvent) {
    event.preventDefault();
    const onMove = (moveEvent: PointerEvent) => {
      if (kind === "sidebar") setSidebarWidth(Math.min(340, Math.max(210, moveEvent.clientX)));
      else setDraftWidth(Math.min(520, Math.max(320, window.innerWidth - moveEvent.clientX)));
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.classList.remove("is-resizing");
    };
    document.body.classList.add("is-resizing");
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }

  const currentSessionTitle = state?.original_idea.slice(0, 28) ?? "新的灵感";
  // 旧批次对应的是旧 state，只允许最新批次继续修改当前草稿。
  const currentHintMessageId = [...messages].reverse().find((message) => message.hints?.length)?.id ?? null;

  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"} ${draftOpen ? "draft-open" : ""}`} style={shellStyle}>
      <header className="topbar">
        <div className="topbar-left">
          <button className="icon-button menu-button" onClick={() => setSidebarOpen((value) => !value)} aria-label={sidebarOpen ? "收起历史栏" : "展开历史栏"}><Menu size={17} /></button>
          <div className="brand-block"><img src="/vellum-mark.svg" alt="" className="brand-mark" /><span className="brand-cn">云笺</span><span className="brand-en">Vellum</span></div>
        </div>
        <div className="session-title"><span className="session-dot" />{currentSessionTitle}</div>
        <div className="top-actions">
          <span className="model-badge">通用文生图</span>
          <button className={`icon-button draft-toggle ${draftOpen ? "active" : ""}`} onClick={() => setDraftOpen((value) => !value)} aria-label="查看视觉草稿"><PanelRight size={17} />{state && <i />}</button>
          <button className="top-new-button" onClick={resetConversation}><Plus size={15} /><span>新建</span></button>
          <span className="avatar">云</span>
        </div>
      </header>

      {sidebarOpen && <button className="mobile-scrim sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="关闭历史栏" />}

      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-hidden={!sidebarOpen}>
        <button className="new-button" onClick={resetConversation}><Plus size={16} />新建灵感<span className="shortcut">N</span></button>
        <nav className="side-nav" aria-label="创作流程">
          <p className="side-label">工作台</p>
          <button className="nav-item active">灵感对话</button>
          <button className="nav-item" onClick={() => setDraftOpen(true)}>视觉草稿{state && <span className="nav-status">{state.status === "ready" ? "就绪" : "更新中"}</span>}</button>
          <button className="nav-item" disabled={!state || Boolean(busy)} onClick={createPrompt}>Prompt 输出</button>
        </nav>
        <section className="history-section">
          <p className="side-label"><span>历史灵感</span></p>
          <div className="history-list">
            {sessions.length ? sessions.map((session) => (
              <div key={session.id} className="history-item-row">
                <button className={`history-item ${session.id === sessionId ? "active" : ""}`} onClick={() => openSession(session)}><span>{session.title}</span><time>{formatSessionTime(session.updatedAt)}</time></button>
                <button className="history-delete" onClick={() => deleteSession(session.id)} aria-label={`删除历史记录：${session.title}`}>删除</button>
              </div>
            )) : <p className="history-empty">完成一次对话后，灵感会自动保存在这里。</p>}
          </div>
        </section>
        <div className="mode-note"><div><strong>{modeMeta.label}</strong><p>{modeMeta.description}</p></div></div>
        <button className="resize-handle left-resize" onPointerDown={(event) => beginResize("sidebar", event)} aria-label="调整历史栏宽度" />
      </aside>

      <main className="conversation" ref={timelineRef}>
        <div className={`conversation-inner ${messages.length ? "has-messages" : ""}`}>
          {messages.length === 0 ? (
            <>
              <section className="welcome"><div className="eyebrow">云笺灵感对话</div><h1>先说出一幕，<br /><span>灵感会慢慢显形。</span></h1><p>不需要提示词术语。云笺会先听懂你真正想表达的画面，再给出少量、可选择的补全方向。</p></section>
              <div className="starter-grid">
                {seeds.map((seed, index) => <button key={seed} onClick={() => { setInput(seed); textareaRef.current?.focus(); }}><span className="starter-number">0{index + 1}</span><span>{seed}</span></button>)}
              </div>
            </>
          ) : <div className="conversation-heading"><span>INSPIRATION THREAD</span><h1>{currentSessionTitle}</h1></div>}

          <div className="message-list" aria-live="polite">
            {messages.map((message) => (
              <MessageItem key={message.id} message={message} activeQuestionId={state?.question?.id ?? null} currentHintMessageId={currentHintMessageId} busy={busy} copied={copied} onAnswer={chooseAnswer} onCompile={createPrompt} onCopy={copyText} onUseHint={useHint} onRefreshHints={refreshHints} />
            ))}
            {busy && <div className="thinking-row"><span>{busy === "compile" ? "正在编译 Prompt" : busy === "refresh" ? "正在换一批灵感" : "正在理解并寻找可补全的画面线索"}</span><i /><i /><i /></div>}
          </div>
        </div>

        <div className="composer-wrap">
          <div className="composer">
            {state && <div className="composer-context"><span>已收集 {state.draft.facts.length + state.draft.visual_language.length + 1} 条画面信息</span><button onClick={createPrompt} disabled={Boolean(busy)}>生成 Prompt</button></div>}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onInput={(event) => { const target = event.currentTarget; target.style.height = "auto"; target.style.height = `${Math.min(target.scrollHeight, 160)}px`; }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitIdea(); }
              }}
              placeholder={state ? "继续补充画面，或直接采用上方的一条灵感……" : "用最简单的话描述你脑海中的画面……"}
              rows={1}
              disabled={Boolean(busy)}
            />
            <div className="composer-footer">
              <div className="mode-picker">
                <button className="mode-trigger" onClick={() => !state && setModeMenuOpen((value) => !value)} disabled={Boolean(state)}><span>{modeMeta.label}</span><ChevronDown size={13} /></button>
                {modeMenuOpen && !state && (
                  <div className="mode-menu"><p>选择云笺参与创作的程度</p>{modes.map((item) => <button key={item.value} className={item.value === mode ? "selected" : ""} onClick={() => { setMode(item.value); setModeMenuOpen(false); }}><i>{item.value === mode && <Check size={11} />}</i><span><strong>{item.label}</strong><small>{item.description}</small></span></button>)}</div>
                )}
              </div>
              <span className="send-hint">Enter 发送 · Shift+Enter 换行</span>
              <button className="send-button" onClick={() => void submitIdea()} disabled={!input.trim() || Boolean(busy)} aria-label="发送"><ArrowUp size={18} /></button>
            </div>
          </div>
          {error && <div className="error-banner"><span>{error}</span><button onClick={() => setError(null)}><X size={14} /></button></div>}
          <p className="composer-disclaimer">建议只是灵感，不会在未经选择时改变你的原意。</p>
        </div>
      </main>

      {draftOpen && <button className="draft-scrim" onClick={() => setDraftOpen(false)} aria-label="关闭视觉草稿" />}
      <DraftDrawer state={state} open={draftOpen} onClose={() => setDraftOpen(false)} onResize={(event) => beginResize("draft", event)} />
    </div>
  );
}

interface MessageItemProps {
  message: ConversationMessage;
  activeQuestionId: string | null;
  currentHintMessageId: string | null;
  busy: BusyAction;
  copied: string | null;
  onAnswer: (messageId: string, label: string, answer: { option_id: string } | { use_ai_decide: true }) => void;
  onCompile: () => void;
  onCopy: (id: string, value: string) => void;
  onUseHint: (hint: InspirationHint) => void;
  onRefreshHints: (messageId: string) => void;
}

function MessageItem({ message, activeQuestionId, currentHintMessageId, busy, copied, onAnswer, onCompile, onCopy, onUseHint, onRefreshHints }: MessageItemProps) {
  if (message.role === "user") {
    return <article className="message user-message"><div className="user-bubble">{message.text}</div></article>;
  }

  if (message.promptResult) {
    const result = message.promptResult;
    const combined = `主 Prompt\n${result.prompt}\n\n负面 Prompt\n${result.negative_prompt || "无"}`;
    return (
      <article className="message assistant-message"><div className="message-body prompt-output">
        <div className="prompt-heading"><div><p className="message-author">云笺 · Prompt 已生成</p><h2>{result.creative_summary}</h2></div><button className="copy-all" onClick={() => void onCopy(`${message.id}-all`, combined)}>{copied === `${message.id}-all` ? <><Check size={13} />已复制全部</> : <><Clipboard size={13} />复制全部</>}</button></div>
        <PromptBlock title="主 Prompt" content={result.prompt} copyId={`${message.id}-main`} copied={copied} onCopy={onCopy} />
        <PromptBlock title="负面 Prompt" content={result.negative_prompt || "没有额外的排除项"} copyId={`${message.id}-negative`} copied={copied} onCopy={onCopy} subtle />
      </div></article>
    );
  }

  const question = message.question;
  const isActive = Boolean(question && question.id === activeQuestionId && !message.answered);
  const hintsAreCurrent = message.id === currentHintMessageId;
  return (
    <article className="message assistant-message"><div className="message-body">
      <p className="message-author">云笺</p><p className="assistant-copy">{message.text}</p>
      {message.sceneContext && <div className="scene-context-inline"><span>情境理解</span><p>{message.sceneContext.text}</p></div>}
      {message.hints && message.hints.length > 0 && (
        <section className={`inspiration-card ${hintsAreCurrent ? "" : "resolved"}`}><div className="inspiration-heading"><div><span>让画面更具体的灵感</span><small>采用后会自动补回 4 条</small></div>{hintsAreCurrent && <button className="refresh-hints" onClick={() => onRefreshHints(message.id)} disabled={Boolean(busy)}>换一批</button>}</div><div className="hint-list">
          {message.hints.map((hint) => <button key={hint.id} disabled={!hintsAreCurrent || Boolean(busy)} onClick={() => onUseHint(hint)}><span className="hint-label">{hint.label}</span><strong>{hint.example}</strong><small>{hint.suggestion}</small><i>{hintsAreCurrent ? "采用" : "已更新"}</i></button>)}
        </div></section>
      )}
      {question && (
        <div className={`question-card ${!isActive ? "resolved" : ""}`}><div className="question-heading"><span>一个关键选择</span><small>{question.why_it_matters}</small></div><h3>{question.prompt}</h3><div className="option-grid">
          {question.options.map((option, index) => <button key={option.id} disabled={!isActive || Boolean(busy)} onClick={() => onAnswer(message.id, option.label, { option_id: option.id })}><span className="option-index">0{index + 1}</span><strong>{option.label}</strong><small>{option.effect}</small></button>)}
        </div>{isActive ? <div className="question-actions"><button onClick={() => onAnswer(message.id, "交给云笺决定", { use_ai_decide: true })} disabled={Boolean(busy)}>交给云笺</button><button onClick={onCompile} disabled={Boolean(busy)}>暂不选择，直接生成</button></div> : <div className="answered-mark"><Check size={14} />已处理这项选择</div>}</div>
      )}
    </div></article>
  );
}

function PromptBlock({ title, content, copyId, copied, onCopy, subtle = false }: { title: string; content: string; copyId: string; copied: string | null; onCopy: (id: string, value: string) => void; subtle?: boolean }) {
  return <div className={`prompt-block ${subtle ? "subtle" : ""}`}><div className="prompt-label"><span>{title}</span><button onClick={() => void onCopy(copyId, content)}>{copied === copyId ? <><Check size={13} />已复制</> : <><Clipboard size={13} />复制</>}</button></div><p>{content}</p></div>;
}

function DraftDrawer({ state, open, onClose, onResize }: { state: InspirationState | null; open: boolean; onClose: () => void; onResize: (event: React.PointerEvent) => void }) {
  const allStatements = state ? [...(state.draft.scene_context ? [state.draft.scene_context] : []), state.draft.core_intent, ...state.draft.facts, ...state.draft.visual_language] : [];
  const userStatements = useMemo(() => uniqueStatements(allStatements.filter((item) => item.origin === "user")), [state]);
  const aiStatements = useMemo(() => uniqueStatements(allStatements.filter((item) => item.origin === "assistant")), [state]);
  return (
    <aside className={`draft-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="resize-handle right-resize" onPointerDown={onResize} aria-label="调整草稿栏宽度" />
      <div className="draft-header"><div><span>VISUAL INTENT</span><h2>视觉意图草稿</h2></div><button onClick={onClose} aria-label="关闭视觉草稿"><X size={17} /></button></div>
      {!state ? <div className="empty-draft"><h3>画面从一句话开始</h3><p>对话开始后，你确认的内容与云笺建议会分别出现在这里。</p></div> : (
        <div className="draft-content">
          <div className="draft-state"><span className={state.status === "ready" ? "ready" : "working"} />{state.status === "ready" ? "当前草稿可以生成" : `正在厘清 · ${state.questions_asked}/2 个关键问题`}</div>
          {state.draft.scene_context && <section className="draft-section scene-section"><p className="draft-section-label">情境理解</p><StatementRow statement={state.draft.scene_context} featured /></section>}
          <section className={`draft-section ${state.draft.scene_context ? "" : "core-section"}`}><p className="draft-section-label">核心意图</p><StatementRow statement={state.draft.core_intent} featured /></section>
          <section className="draft-section"><p className="draft-section-label">画面事实 <span>{state.draft.facts.length}</span></p><div className="statement-list">{state.draft.facts.map((item, index) => <StatementRow key={`${item.text}-${index}`} statement={item} />)}</div></section>
          <section className="draft-section"><p className="draft-section-label">视觉表达 <span>{state.draft.visual_language.length}</span></p><div className="statement-list">{state.draft.visual_language.map((item, index) => <StatementRow key={`${item.text}-${index}`} statement={item} />)}{!state.draft.visual_language.length && <p className="empty-line">尚未选择视觉表达</p>}</div></section>
          {(state.draft.constraints.must_keep.length > 0 || state.draft.constraints.avoid.length > 0) && <section className="draft-section constraints"><p className="draft-section-label">创作边界</p>{state.draft.constraints.must_keep.length > 0 && <div className="constraint-row"><span>保留</span><div>{state.draft.constraints.must_keep.map((item) => <i key={item}>{item}</i>)}</div></div>}{state.draft.constraints.avoid.length > 0 && <div className="constraint-row avoid"><span>避免</span><div>{state.draft.constraints.avoid.map((item) => <i key={item}>{item}</i>)}</div></div>}</section>}
          <section className="source-section">
            <div className="source-block user-source"><div className="source-title"><span><i />你的原意</span><b>{userStatements.length}</b></div>{userStatements.map((item) => <p key={item.text}>{item.text}</p>)}</div>
            <div className="source-block ai-source"><div className="source-title"><span><i />云笺建议</span><b>{aiStatements.length}</b></div>{aiStatements.length ? aiStatements.map((item) => <p key={item.text}>{item.text}</p>) : <p className="source-empty">还没有采用任何建议</p>}</div>
          </section>
        </div>
      )}
    </aside>
  );
}

function uniqueStatements(items: DraftStatement[]) {
  return items.filter((item, index) => items.findIndex((candidate) => candidate.text === item.text) === index);
}

function StatementRow({ statement, featured = false }: { statement: DraftStatement; featured?: boolean }) {
  return <div className={`statement ${statement.origin === "assistant" ? "from-ai" : "from-user"} ${featured ? "featured" : ""}`}><span className="statement-dot" /><p>{statement.text}</p><small>{statement.origin === "assistant" ? "建议" : "确认"}</small></div>;
}

export default App;
