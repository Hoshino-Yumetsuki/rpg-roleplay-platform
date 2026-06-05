// Core API types for RPG Roleplay frontend - matches api-client.js IIFE surface

export interface ApiErrorInstance {
  code: string;
  status: number;
  message: string;
  payload?: unknown;
}

export interface SseHandler<T = unknown> {
  onEvent?: (evt: { event: string; data: T }) => void;
  onError?: (error: ApiErrorInstance) => void;
  onClose?: () => void;
  [key: `on_${string}`]: ((data: T) => void) | undefined;
}

export interface SseStream {
  stop: () => void;
  done: Promise<void>;
}

// ── Auth ─────────────────────────────────────────────
export interface RegisterBody {
  username: string;
  password: string;
  email: string;
  invite_code?: string;
}

export interface LoginBody {
  username: string;
  password: string;
}

export interface UserInfo {
  user: {
    id: number;
    uid: string;
    username: string;
    display_name?: string;
    role: string;
    bio?: string;
  };
  token?: string;
}

// ── Scripts ──────────────────────────────────────────
export interface RawScriptInfo {
  id: number;
  uid?: string;
  title: string;
  name?: string;
  description?: string;
  subtitle?: string;
  chapter_count?: number;
  chapters?: number;
  word_count?: number;
  words?: number;
  import_report?: {
    mode_label?: string;
    confidence?: number;
    problem_label?: string;
  };
  mode_label?: string;
  confidence?: number;
  problem_label?: string;
  updated_at: string;
  updated_at_human?: string;
  is_public?: boolean;
  clone_count?: number;
  script?: { id: number };
}

export interface ScriptInfo {
  id: number;
  uid: string;
  title: string;
  description: string;
  chapter_count: number;
  word_count: number;
  import_report: {
    mode_label: string;
    confidence: number;
    problem_label: string;
  };
  updated_at: string;
  is_public: boolean;
  clone_count: number;
  _raw: RawScriptInfo;
}

// ── Saves ────────────────────────────────────────────
export interface RawSaveInfo {
  id: number;
  uid?: string;
  title?: string;
  name?: string;
  script_id?: number;
  branch_count?: number;
  branches?: number;
  updated_at?: string;
  updated_at_human?: string;
  last_played_at?: string;
  created_at?: string;
  current?: boolean;
  script?: { id: number };
}

export interface SaveInfo {
  id: number;
  uid: string;
  title: string;
  script_id: number | undefined;
  branch_count: number;
  updated_at: string;
  last_played_at: string;
  last_played_ts: string | null;
  created_ts: string | null;
  current: boolean;
  _raw: RawSaveInfo;
}

// ── Mock data types ──────────────────────────────────
export interface MockNovel {
  title: string;
  author: string;
  genre: string;
  chapters: Array<{
    id: number;
    title: string;
    content: string;
    word_count: number;
  }>;
  [key: string]: unknown;
}

export interface MockState {
  player: Record<string, unknown>;
  world: Record<string, unknown>;
  relationships: unknown[];
  memory: unknown[];
  worldline: Record<string, unknown>;
  permissions: {
    pending_writes: unknown[];
    pending_questions: unknown[];
    [key: string]: unknown;
  };
  suggestions: unknown[];
  turn: number;
  history: unknown[];
  inventory: unknown[];
  timeline: Record<string, unknown>;
  _raw: Record<string, unknown>;
  [key: string]: unknown;
}

export interface MockRunSteps {
  steps: unknown[];
  [key: string]: unknown;
}

export interface MockPlatform {
  user: {
    id: number | null;
    uid: string;
    username: string;
    display_name: string;
    role: string;
    bio: string;
  };
  stats: {
    scripts: number | null;
    saves: number | null;
    branches: number | null;
    assets: number | null;
    api_calls: number | null;
    [key: string]: unknown;
  };
  scripts: ScriptInfo[];
  saves: SaveInfo[];
  recent_assets: Array<{ name: string; size: number; kind: string; at: string }>;
  database: Record<string, unknown>;
  [key: string]: unknown;
}

// ── Toast ────────────────────────────────────────────
export interface ToastOptions {
  kind?: 'ok' | 'danger' | 'warning' | 'info';
  duration?: number;
  detail?: string;
}

// ── Raw HTTP helpers ─────────────────────────────────
export interface RawApi {
  GET: (path: string, query?: Record<string, unknown>) => Promise<unknown>;
  POST: (path: string, body?: unknown, opts?: Record<string, unknown>) => Promise<unknown>;
  PATCH: (path: string, body?: unknown, opts?: Record<string, unknown>) => Promise<unknown>;
  PUT: (path: string, body?: unknown, opts?: Record<string, unknown>) => Promise<unknown>;
  DEL: (path: string, body?: unknown, opts?: Record<string, unknown>) => Promise<unknown>;
  sseStream: (path: string, body: unknown, handlers: SseHandler) => SseStream;
}

// ── API Method signatures ────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ApiMethod = (...args: any[]) => Promise<unknown>;

interface ApiNamespace {
  [key: string]: ApiMethod | ApiNamespace;
}

export interface ApiInterface extends ApiNamespace {
  base: string;
  me: ApiInterface['account'];
  raw: RawApi;
  auth: ApiNamespace;
  account: ApiNamespace;
  platform: ApiNamespace;
  admin: ApiNamespace;
  scripts: ApiNamespace;
  federation: ApiNamespace;
  saves: ApiNamespace;
  branches: ApiNamespace;
  rules: ApiNamespace;
  cards: ApiNamespace;
  chats: ApiNamespace;
  library: ApiNamespace;
  uploads: ApiNamespace;
  credentials: ApiNamespace;
  models: ApiNamespace;
  tools: ApiNamespace;
  mcp: ApiNamespace;
  skills: ApiNamespace;
  plugins: ApiNamespace;
  game: ApiNamespace;
  worldline: ApiNamespace;
  memories: ApiNamespace;
}
