/**
 * POC UI state — vanilla store (maps to React context + reducers later).
 */

export const Phase = {
  IDLE: "idle",
  DISCOVERING: "discovering",
  DISCOVERED: "discovered",
  EMPTY: "empty",
  GENERATING: "generating",
  ANSWERED: "answered",
  ERROR: "error",
};

/** Alias used in design docs */
export const EMPTY_RESULT = Phase.EMPTY;

export const AGENTS = [
  { id: "nas-rag", label: "NAS 문서 RAG (기본)" },
  { id: "project-docs", label: "프로젝트 문서 (placeholder)" },
];

/** Central mutable store (POC only). */
export const state = {
  question: "",
  selectedAgentId: "nas-rag",
  deptCodesInput: "",
  discoverTopK: 30,
  generateTopK: 5,
  phase: Phase.IDLE,
  lastError: null,
  discoverResponse: null,
  generateResponse: null,
  selectedDocumentIds: new Set(),
  sortDocumentsBy: "score",
  highlightedDocumentId: null,
  highlightedSourceChunkId: null,
  debugExpanded: false,
  advancedSettingsOpen: false,
  // Last request meta for QA visibility (UI only; backend contract unchanged).
  lastDiscoverTopK: null,
  lastDiscoverDeptCodes: null,
  lastGenerateTopK: null,
  lastGenerateDeptCodes: null,
};

let _notify = () => {};

export function subscribe(listener) {
  _notify = listener;
}

export function patch(patchOrFn) {
  if (typeof patchOrFn === "function") {
    patchOrFn(state);
  } else {
    Object.assign(state, patchOrFn);
  }
  _notify();
}

/** Update store without re-render (e.g. while typing in a text input). */
export function assignState(updates) {
  Object.assign(state, updates);
}

export function setDocumentSelected(rawId, selected) {
  if (selected) {
    state.selectedDocumentIds.add(rawId);
  } else {
    state.selectedDocumentIds.delete(rawId);
  }
  _notify();
}

export function selectAllDocumentIds(ids) {
  state.selectedDocumentIds = new Set(ids);
  _notify();
}

export function clearDocumentSelection() {
  state.selectedDocumentIds.clear();
  _notify();
}

export function getTestDepartmentCodes() {
  const raw = state.deptCodesInput.trim();
  if (!raw) {
    return undefined;
  }
  const codes = raw.split(/[\s,]+/).filter(Boolean);
  return codes.length ? codes : undefined;
}

export function getDocumentById(id) {
  const docs = state.discoverResponse?.documents;
  if (!docs) {
    return null;
  }
  return docs.find((d) => String(d.raw_document_id) === String(id)) ?? null;
}

/** @returns {string[]} Selected ``raw_document_id`` values for /generate. */
export function getSelectedDocumentIdsArray() {
  return [...state.selectedDocumentIds];
}

export function hasDiscoverResults() {
  const dr = state.discoverResponse;
  if (!dr) {
    return false;
  }
  const count = Number(dr.document_count);
  if (Number.isFinite(count) && count > 0) {
    return true;
  }
  return Array.isArray(dr.documents) && dr.documents.length > 0;
}

export function canStartDiscover() {
  return Boolean(state.question.trim()) && state.phase !== Phase.DISCOVERING && state.phase !== Phase.GENERATING;
}

export function canStartGenerate() {
  return (
    Boolean(state.question.trim()) &&
    state.selectedDocumentIds.size > 0 &&
    hasDiscoverResults() &&
    state.phase !== Phase.GENERATING &&
    state.phase !== Phase.DISCOVERING
  );
}
