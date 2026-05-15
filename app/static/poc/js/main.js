/**
 * Entry: bind DOM events to state + API.
 */

import { isDiscoverEmpty, postDiscover, postGenerate } from "./api.js";
import {
  assignState,
  clearDocumentSelection,
  getSelectedDocumentIdsArray,
  getTestDepartmentCodes,
  hasDiscoverResults,
  patch,
  Phase,
  selectAllDocumentIds,
  setDocumentSelected,
  state,
  subscribe,
} from "./state.js";
import { renderAll } from "./render.js";

const IME_TEXT_INPUT_IDS = new Set(["inp-question", "inp-dept"]);

function getQuestionFromDom() {
  const el = document.getElementById("inp-question");
  if (el instanceof HTMLInputElement) {
    return el.value;
  }
  return state.question;
}

/** Refresh primary action buttons without full re-render. */
export function updateActionButtons() {
  const q = getQuestionFromDom().trim();
  const busy =
    state.phase === Phase.DISCOVERING || state.phase === Phase.GENERATING;

  const discoverBtn = document.getElementById("btn-discover");
  if (discoverBtn instanceof HTMLButtonElement) {
    discoverBtn.disabled = busy || !q;
  }

  const genBtn = document.getElementById("btn-generate");
  if (genBtn instanceof HTMLButtonElement) {
    const canGen =
      Boolean(q) &&
      state.selectedDocumentIds.size > 0 &&
      hasDiscoverResults() &&
      !busy;
    genBtn.disabled = !canGen;
  }
}

function syncInputsFromDom() {
  const q = document.getElementById("inp-question");
  const dept = document.getElementById("inp-dept");
  const dk = document.getElementById("inp-discover-k");
  const gk = document.getElementById("inp-gen-k");
  const agent = document.getElementById("sel-agent");
  if (q instanceof HTMLInputElement) {
    state.question = q.value;
  }
  if (dept instanceof HTMLInputElement) {
    state.deptCodesInput = dept.value;
  }
  if (agent && agent instanceof HTMLSelectElement) {
    state.selectedAgentId = agent.value;
  }
  if (dk) {
    const n = parseInt(dk.value, 10);
    if (!Number.isNaN(n)) {
      state.discoverTopK = Math.min(50, Math.max(1, n));
    }
  }
  if (gk) {
    const n = parseInt(gk.value, 10);
    if (!Number.isNaN(n)) {
      state.generateTopK = Math.min(50, Math.max(1, n));
    }
  }
}

async function onDiscover() {
  syncInputsFromDom();
  const q = state.question.trim();
  if (!q) {
    return;
  }
  const codes = getTestDepartmentCodes();
  const topK = state.discoverTopK;
  console.debug("[POC] /api/v1/chat/discover payload", {
    question: q,
    top_k: topK,
    test_department_codes: codes ?? undefined,
  });
  patch({
    phase: Phase.DISCOVERING,
    lastError: null,
    discoverResponse: null,
    generateResponse: null,
    selectedDocumentIds: new Set(),
    highlightedDocumentId: null,
    highlightedSourceChunkId: null,
    lastDiscoverTopK: topK,
    lastDiscoverDeptCodes: codes ?? null,
  });
  try {
    const data = await postDiscover({
      question: q,
      top_k: topK,
      test_department_codes: codes,
    });
    patch({
      discoverResponse: data,
      phase: isDiscoverEmpty(data) ? Phase.EMPTY : Phase.DISCOVERED,
    });
  } catch (e) {
    patch({
      phase: Phase.ERROR,
      lastError: humanDiscoverError(e),
      discoverResponse: null,
    });
  }
}

function humanDiscoverError(e) {
  if (!e) {
    return "알 수 없는 오류";
  }
  if (e.name === "TypeError" && String(e.message).includes("fetch")) {
    return "서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인해 주세요.";
  }
  return e.message || "문서 탐색 중 오류가 발생했습니다.";
}

function humanGenerateError(e) {
  if (!e) {
    return "알 수 없는 오류";
  }
  if (e.name === "TypeError" && String(e.message).includes("fetch")) {
    return "서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인해 주세요.";
  }
  const st = e.status;
  if (st === 502) {
    return "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }
  if (st === 503) {
    return "서비스를 일시적으로 사용할 수 없습니다.";
  }
  if (st === 422) {
    return e.message || "요청 형식이 올바르지 않습니다.";
  }
  return e.message || "답변 생성 중 오류가 발생했습니다.";
}

async function onGenerate() {
  syncInputsFromDom();
  const q = state.question.trim();
  const docIds = getSelectedDocumentIdsArray();
  if (!q || docIds.length === 0) {
    return;
  }
  const codes = getTestDepartmentCodes();
  const topK = state.generateTopK;
  console.debug("[POC] /api/v1/chat/generate payload", {
    question: q,
    document_ids: docIds,
    top_k: topK,
    test_department_codes: codes ?? undefined,
  });
  const prevPhase = state.phase;
  patch({
    phase: Phase.GENERATING,
    lastError: null,
    generateResponse: null,
    lastGenerateTopK: topK,
    lastGenerateDeptCodes: codes ?? null,
  });
  try {
    const data = await postGenerate({
      question: q,
      document_ids: docIds,
      top_k: topK,
      test_department_codes: codes,
    });
    patch({
      generateResponse: data,
      phase: Phase.ANSWERED,
    });
  } catch (e) {
    patch({
      phase: state.discoverResponse ? Phase.DISCOVERED : prevPhase,
      lastError: humanGenerateError(e),
      generateResponse: null,
    });
  }
}

function scrollToDocCard(docId) {
  queueMicrotask(() => {
    document
      .querySelector(`.doc-card[data-doc-id="${docId}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function onDelegatedClick(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) {
    return;
  }
  if (t.closest(".nav-item--disabled") || t.id === "nav-search") {
    ev.preventDefault();
    return;
  }
  if (t.id === "btn-discover" || t.closest("#btn-discover")) {
    ev.preventDefault();
    onDiscover();
    return;
  }
  if (t.id === "btn-generate" || t.closest("#btn-generate")) {
    ev.preventDefault();
    onGenerate();
    return;
  }
  if (t.id === "btn-sel-all") {
    const docs = state.discoverResponse?.documents || [];
    selectAllDocumentIds(docs.map((d) => String(d.raw_document_id)));
    return;
  }
  if (t.id === "btn-sel-none") {
    clearDocumentSelection();
    return;
  }
  const srcBtn = t.closest(".source-item");
  if (srcBtn instanceof HTMLElement && srcBtn.dataset.srcDoc) {
    const docId = srcBtn.dataset.srcDoc;
    const chunkId = srcBtn.dataset.srcChunk || null;
    patch({
      highlightedDocumentId: docId,
      highlightedSourceChunkId: chunkId,
    });
    scrollToDocCard(docId);
    return;
  }
}

function onDelegatedChange(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLElement)) {
    return;
  }
  if (t.id === "sel-sort" && t instanceof HTMLSelectElement) {
    patch({ sortDocumentsBy: t.value });
    return;
  }
  if (t.id === "sel-agent" && t instanceof HTMLSelectElement) {
    patch({ selectedAgentId: t.value });
    return;
  }
  if (t.classList.contains("doc-cb") && t instanceof HTMLInputElement) {
    const id = t.dataset.docId;
    if (id) {
      setDocumentSelected(id, t.checked);
    }
  }
}

function onToggle(ev) {
  const t = ev.target;
  if (t instanceof HTMLDetailsElement && t.id === "debug-details") {
    state.debugExpanded = t.open;
  }
  if (t instanceof HTMLDetailsElement && t.id === "adv-settings") {
    state.advancedSettingsOpen = t.open;
  }
}

function onCompositionStart(ev) {
  const t = ev.target;
  if (t instanceof HTMLInputElement && IME_TEXT_INPUT_IDS.has(t.id)) {
    t.dataset.composing = "true";
  }
}

function onCompositionEnd(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLInputElement) || !IME_TEXT_INPUT_IDS.has(t.id)) {
    return;
  }
  delete t.dataset.composing;
  if (t.id === "inp-question") {
    assignState({ question: t.value });
    updateActionButtons();
  } else if (t.id === "inp-dept") {
    assignState({ deptCodesInput: t.value });
  }
}

function onKeyDown(ev) {
  if (ev.key !== "Enter") {
    return;
  }
  const t = ev.target;
  if (t instanceof HTMLInputElement && t.id === "inp-question") {
    if (ev.isComposing || t.dataset.composing === "true") {
      return;
    }
    ev.preventDefault();
    onDiscover();
  }
}

function onInput(ev) {
  const t = ev.target;
  if (!(t instanceof HTMLInputElement)) {
    return;
  }
  if (t.id === "inp-question") {
    if (t.dataset.composing === "true") {
      updateActionButtons();
      return;
    }
    assignState({ question: t.value });
    updateActionButtons();
    return;
  }
  if (t.id === "inp-dept") {
    if (t.dataset.composing === "true") {
      return;
    }
    assignState({ deptCodesInput: t.value });
    return;
  }
  if (t.id === "inp-discover-k") {
    const n = parseInt(t.value, 10);
    if (!Number.isNaN(n)) {
      state.discoverTopK = Math.min(50, Math.max(1, n));
    }
    return;
  }
  if (t.id === "inp-gen-k") {
    const n = parseInt(t.value, 10);
    if (!Number.isNaN(n)) {
      state.generateTopK = Math.min(50, Math.max(1, n));
    }
  }
}

function boot() {
  subscribe(() => {
    const ae = document.activeElement;
    const fid = ae && "id" in ae ? ae.id : "";
    const debugOpen =
      document.getElementById("debug-details") instanceof HTMLDetailsElement
        ? document.getElementById("debug-details").open
        : state.debugExpanded;
    state.debugExpanded = debugOpen;
    const adv =
      document.getElementById("adv-settings") instanceof HTMLDetailsElement
        ? document.getElementById("adv-settings").open
        : state.advancedSettingsOpen;
    state.advancedSettingsOpen = adv;
    renderAll();
    updateActionButtons();
    if (fid) {
      const el = document.getElementById(fid);
      if (el && typeof el.focus === "function") {
        el.focus();
      }
    }
  });
  document.body.addEventListener("click", onDelegatedClick);
  document.body.addEventListener("change", onDelegatedChange);
  document.body.addEventListener("toggle", onToggle, true);
  document.body.addEventListener("compositionstart", onCompositionStart);
  document.body.addEventListener("compositionend", onCompositionEnd);
  document.body.addEventListener("input", onInput);
  document.body.addEventListener("keydown", onKeyDown);
  renderAll();
  updateActionButtons();
}

boot();
