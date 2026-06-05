// RPG Roleplay · Global Window Declarations
// window.api / window.MOCK_* / window.RPG_* set by IIFE modules

import type {
  ApiInterface,
  MockNovel,
  MockState,
  MockRunSteps,
  MockPlatform,
  ToastOptions,
  ApiErrorInstance,
} from './api';

declare global {
  interface Window {
    // ── API Client (api-client.js IIFE) ───────────────
    api: ApiInterface;
    __API_BASE: string;
    ApiError: typeof ApiError;
    withToast: <T>(
      promise: Promise<T>,
      okMsg?: string,
      failMsg?: string
    ) => Promise<T>;
    __apiToast: (msg: string, opts?: ToastOptions) => void;

    // ── Data Loader ────────────────────────────────────
    MOCK_NOVEL: MockNovel;
    MOCK_STATE: MockState;
    MOCK_RUN_STEPS: MockRunSteps;
    MOCK_PLATFORM: MockPlatform;
    RPG_DATA_READY: Promise<{
      online: boolean;
      authed: boolean;
      platform?: MockPlatform;
      state?: MockState;
    }>;
    RPG_AUTH: { authed: boolean; online: boolean };
    __MOCK_BASELINE: {
      novel: MockNovel;
      state: MockState;
      runSteps: MockRunSteps;
      platform: MockPlatform;
    };
    __fmt: {
      bytes: (n: number) => string;
      ago: (ts: string | number) => string;
    };
    __guessKind: (name: string) => string;
    __normalizeScript: (s: unknown) => unknown;
    __normalizeSave: (s: unknown) => unknown;
    __refreshPlatform: () => Promise<{
      platform: MockPlatform;
      state: MockState;
      authed: boolean;
    }>;

    // ── Capabilities Bus ──────────────────────────────
    __capBus: EventTarget;

    // ── Telemetry ─────────────────────────────────────
    __onApiError: (error: ApiErrorInstance) => void;

    // ── Toast (from platform-app) ─────────────────────
    toast: (msg: string, opts?: ToastOptions) => void;

    // ── i18n ──────────────────────────────────────────
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    changeLanguage: any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    t: any;
  }

  // ── ApiError class (api-client.js) ──────────────────
  class ApiError extends Error {
    code: string;
    status: number;
    payload: unknown;
    constructor(code: string, status: number, message: string, payload?: unknown);
  }
}

export {};
