export type CreationMode = "faithful" | "collaborative" | "exploratory";
export type StatementOrigin = "user" | "assistant";
export type StatementStatus = "confirmed" | "suggested";

export interface DraftStatement {
  text: string;
  origin: StatementOrigin;
  status: StatementStatus;
}

export interface VisualDraft {
  scene_context?: DraftStatement | null;
  core_intent: DraftStatement;
  facts: DraftStatement[];
  visual_language: DraftStatement[];
  constraints: {
    must_keep: string[];
    avoid: string[];
  };
}

export interface QuestionOption {
  id: string;
  label: string;
  effect: string;
}

export interface KeyQuestion {
  id: string;
  prompt: string;
  why_it_matters: string;
  options: QuestionOption[];
}

export interface InspirationHint {
  id: string;
  label: string;
  suggestion: string;
  example: string;
}

export interface InspirationState {
  original_idea: string;
  mode: CreationMode;
  understanding: string;
  draft: VisualDraft;
  question: KeyQuestion | null;
  inspiration_hints: InspirationHint[];
  questions_asked: number;
  status: "needs_input" | "ready";
}

export interface CompiledPrompt {
  prompt: string;
  negative_prompt: string;
  creative_summary: string;
}
