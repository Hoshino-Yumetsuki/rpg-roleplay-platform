// @ts-nocheck
/* Empty baseline state. Previously this file shipped a full "雾港未尽 / 顾承砚"
   demo dataset that data-loader.ts captured as a fallback and rendered whenever
   the backend was unreachable or an /api/* call failed — users saw fabricated
   scripts/saves/characters as if they were real.

   The demo data has been removed. These globals now hold only the *shape* each
   structure needs (empty strings / arrays / objects) so the many components that
   chain-access window.MOCK_*.x.y don't crash. When the backend is down the UI
   shows empty / — instead of placeholder content. */

window.MOCK_NOVEL = {
  script_title: '',
  script_author: '',
  script_chapter_count: 0,
  script_word_count: 0,
  script_mode_label: '',
  script_confidence: 0,
};

window.MOCK_STATE = {
  player: {
    name: '',
    role: '',
    background: '',
    current_location: '',
    inventory: [],
  },
  world: {
    time: '',
    weather: '',
    timeline: {
      anchor_state: '',
      current_label: '',
      current_phase: '',
      pending_jump: null,
      anchors: [],
    },
    known_events: [],
  },
  relationships: {},
  permissions: {
    mode: 'full_access',
    pending_writes: [],
    pending_questions: [],
  },
  worldline: {
    user_variables: {},
    constraints: [],
    last_projection: '',
  },
  memory: {
    mode: 'normal',
    main_quest: '',
    current_objective: '',
    pinned: [],
    facts: [],
    notes: [],
    last_retrieval: '',
    last_context: {
      chapter_refs: [],
      retrieval_chunks: 0,
      tokens_used: 0,
    },
  },
  suggestions: [],
  history: [],
};

window.MOCK_RUN_STEPS = [];

window.MOCK_PLATFORM = {
  user: {
    username: '',
    display_name: '',
    role: '',
    uid: '',
    bio: '',
  },
  database: { driver: '', url: '', ok: false },
  stats: { scripts: 0, saves: 0, branches: 0, assets: 0, api_calls: 0 },
  scripts: [],
  saves: [],
  recent_assets: [],
};
