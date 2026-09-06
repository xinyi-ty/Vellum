import type { CompiledPrompt, CreationMode, InspirationState } from "./types";

async function request<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = typeof payload?.detail === "string" ? payload.detail : "请求没有成功，请稍后再试。";
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export function startInspiration(idea: string, mode: CreationMode) {
  return request<InspirationState>("/api/inspirations", { idea, mode });
}

export function answerQuestion(
  state: InspirationState,
  answer: { option_id: string } | { text: string } | { use_ai_decide: true },
) {
  return request<InspirationState>("/api/inspirations/answer", { state, answer });
}

export function reviseDraft(state: InspirationState, instruction: string) {
  return request<InspirationState>("/api/inspirations/revise", { state, instruction });
}

export function refreshInspirationHints(state: InspirationState, excludedExamples: string[]) {
  return request<InspirationState>("/api/inspirations/hints/refresh", {
    state,
    excluded_examples: excludedExamples,
  });
}

export function compilePrompt(state: InspirationState) {
  return request<CompiledPrompt>("/api/inspirations/compile", { state });
}
