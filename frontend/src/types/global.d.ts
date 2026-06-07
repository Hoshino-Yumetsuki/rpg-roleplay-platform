/* ============================================================
 *  Global ambient declarations
 *  -----------------------------------------------------------
 *  Types for window.* globals attached at runtime by the API
 *  client, mock-data fallbacks, toast helpers, and various
 *  cross-cutting UI bridges. The API surface is intentionally
 *  permissive (methods return Promise<any>) — the backend has
 *  no generated client, so responses are validated at call
 *  sites rather than at the type boundary.
 * ============================================================ */

/** A group of endpoint methods. Each call returns a parsed JSON payload. */
type ApiMethod = (...args: any[]) => Promise<any>;
type ApiGroup = Record<string, ApiMethod | Record<string, ApiMethod>>;

/** Permissive shape of the runtime window.api client. */
interface RpgApi {
  [group: string]: any;
}

interface Window {
  // ── Core API client ──
  api: RpgApi;
  ApiError: any;
  __API_BASE?: string;
  RPG_API_BASE?: string;
  RPG_AUTH?: any;
  RPG_DATA_READY?: any;
  __APP_VERSION__?: string;
  __USER_STATE?: any;

  // ── Toast / notifications ──
  toast?: any;
  __apiToast?: any;
  __onApiError?: any;
  __GAME_TOAST_INSTALLED?: boolean;
  __gameToastSubscribe?: any;

  // ── Mock-data fallbacks (offline rendering) ──
  MOCK_STATE?: any;
  MOCK_PLATFORM?: any;
  MOCK_NOVEL?: any;
  MOCK_RUN_STEPS?: any;
  __MOCK_BASELINE?: any;

  // ── Formatting / runtime helpers ──
  __fmt?: any;
  __guessKind?: any;
  __getRuntimeSnapshot?: any;
  __getRuntimeSnapshotSize?: any;
  __UI_ATLAS?: any;
  __RUM_ENABLED?: boolean;

  // ── Capability / dirty-page navigation bridge ──
  __capBus?: any;
  __capMarkDirty?: any;
  __capClearDirty?: any;
  __cap_dirty_pages?: any;
  __cap_navigation_installed?: boolean;

  // ── State-event bridge / worldbook toast guards ──
  __rpgStateEventBridge?: any;
  __rpg_state_bridge_inited__?: boolean;
  __rpg_wb_toast_inited__?: boolean;

  // ── Imperative UI entry points (modals, drawers, mentions) ──
  __confirm?: any;
  __prompt?: any;
  __openContinue?: any;
  __openFeedback?: any;
  __openHelp?: any;
  __openWelcome?: any;
  __refreshPlatform?: any;
  __rpgInsertMention?: any;
  __createAndEnterSave?: any;
  __normalizeSave?: any;
  __normalizeScript?: any;
  __checkAchievements?: any;

  // ── Components / helpers attached to window by side-effect modules ──
  Icon?: any;
  ModelPicker?: any;
  RpgMarkdown?: any;
  withToast?: any;
  CAP_LABEL?: any;
  capFlags?: any;
  getCaps?: any;
  normalizeProviderId?: any;
  PERMISSION_OPTIONS?: any;
  RPG_setDensity?: any;
  handleAssistantNavigation?: any;
}
