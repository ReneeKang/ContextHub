/**
 * DOM rendering — sidebar / center / right panel.
 * React migration: Sidebar, SearchWorkspace, DetailPanel components.
 */

import { AGENTS, canStartDiscover, canStartGenerate, Phase, state } from "./state.js";

const PROGRESS_STEPS = [
  { id: "filter", label: "검색 필터 적용" },
  { id: "search", label: "관련 문서 검색" },
  { id: "candidates", label: "문서 후보 표시" },
  { id: "read", label: "선택 문서 읽기" },
  { id: "generate", label: "답변 생성" },
];

/** Preserve focused / IME-composing text inputs across innerHTML rewrites. */
function captureTextInput(id) {
  const el = document.getElementById(id);
  if (!(el instanceof HTMLInputElement)) {
    return null;
  }
  if (el.dataset.composing === "true" || document.activeElement === el) {
    return {
      value: el.value,
      selectionStart: el.selectionStart,
      selectionEnd: el.selectionEnd,
    };
  }
  return null;
}

function restoreTextInput(id, saved) {
  if (!saved) {
    return;
  }
  const el = document.getElementById(id);
  if (!(el instanceof HTMLInputElement)) {
    return;
  }
  el.value = saved.value;
  const start = saved.selectionStart ?? saved.value.length;
  const end = saved.selectionEnd ?? start;
  try {
    el.setSelectionRange(start, end);
  } catch {
    /* type=search etc. may reject selection on some browsers */
  }
}

function ellipsisText(s, maxLen = 42) {
  if (s == null) {
    return "";
  }
  const t = String(s);
  if (t.length <= maxLen) {
    return esc(t);
  }
  return `${esc(t.slice(0, maxLen - 1))}…`;
}

function esc(s) {
  if (s == null) {
    return "";
  }
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fileExt(filename) {
  const m = String(filename).match(/\.([^.]+)$/);
  return m ? m[1].toUpperCase() : "—";
}

function accessBadge(scope) {
  const s = String(scope || "").toUpperCase();
  if (s === "PUBLIC") {
    return '<span class="badge badge--public">PUBLIC</span>';
  }
  if (s === "PRIVATE") {
    return '<span class="badge badge--private">PRIVATE</span>';
  }
  return '<span class="badge badge--dept">DEPT</span>';
}

function uniq(arr) {
  const set = new Set();
  for (const x of arr || []) {
    if (x == null) continue;
    const s = String(x).trim();
    if (!s) continue;
    set.add(s);
  }
  return [...set];
}

function formatDeptCodes(codes) {
  const arr = Array.isArray(codes) ? codes : [];
  return arr.length ? arr.join(", ") : "—";
}

function shortId(id) {
  const s = String(id || "");
  if (!s) return "—";
  return s.length > 10 ? s.slice(0, 8) + "…" : s;
}

function extractEmTermsFromHtml(html) {
  if (!html) return [];
  const s = String(html);
  const re = /<em\b[^>]*>([\s\S]*?)<\/em>/gi;
  const out = [];
  let m;
  while ((m = re.exec(s)) !== null) {
    const raw = m[1] ?? "";
    const cleaned = String(raw).replace(/<[^>]+>/g, "").trim();
    if (cleaned) {
      out.push(cleaned);
    }
  }
  return out;
}

function extractMatchedFieldsAndTermsFromHighlights(highlights) {
  const h = highlights && typeof highlights === "object" ? highlights : null;
  if (!h) {
    return { matchedFields: [], highlightTerms: [] };
  }

  const matchedFields = [];
  const highlightTerms = [];

  for (const [field, fragments] of Object.entries(h)) {
    if (!Array.isArray(fragments)) continue;
    const terms = uniq(fragments.flatMap(extractEmTermsFromHtml));
    const fieldHasFragments = fragments.some(
      (f) => typeof f === "string" && f.trim().length > 0
    );
    if (fieldHasFragments) {
      matchedFields.push(field);
    }
    if (terms.length) {
      highlightTerms.push(...terms);
    }
  }

  return {
    matchedFields: uniq(matchedFields).slice(0, 3),
    highlightTerms: uniq(highlightTerms).slice(0, 8),
  };
}

function renderTermPills(terms) {
  const arr = uniq(terms || []).slice(0, 6);
  if (!arr.length) return "";
  return arr.map((t) => `<span class="term-pill">${esc(t)}</span>`).join("");
}

function scoreBarFillClass(score, maxScore) {
  const n = maxScore > 0 ? score / maxScore : 0;
  const t = n >= 0.7 ? "high" : n >= 0.45 ? "mid" : "low";
  return `score-bar__fill score-bar__fill--${t}`;
}

function sortedDocuments(docs, sortBy) {
  const arr = [...(docs || [])];
  if (sortBy === "chunks") {
    arr.sort((a, b) => b.matched_chunk_count - a.matched_chunk_count);
  } else if (sortBy === "name") {
    arr.sort((a, b) =>
      String(a.original_filename).localeCompare(String(b.original_filename), "ko")
    );
  } else {
    arr.sort((a, b) => b.top_score - a.top_score);
  }
  return arr;
}

function maxTopScore(docs) {
  return docs.reduce((m, d) => Math.max(m, d.top_score || 0), 0);
}

function progressStepStatus(stepId) {
  const p = state.phase;
  const hasDiscover = Boolean(state.discoverResponse);
  const hasDocs = hasDiscover && (state.discoverResponse.document_count || 0) > 0;
  const hasSelection = state.selectedDocumentIds.size > 0;
  const genDone = p === Phase.ANSWERED;
  const genActive = p === Phase.GENERATING;
  const searchActive = p === Phase.DISCOVERING;
  const searchDone =
    hasDiscover ||
    p === Phase.EMPTY ||
    p === Phase.DISCOVERED ||
    p === Phase.GENERATING ||
    p === Phase.ANSWERED ||
    (p === Phase.ERROR && hasDiscover);

  switch (stepId) {
    case "filter":
      if (p === Phase.IDLE && !hasDiscover) {
        return "pending";
      }
      if (p === Phase.ERROR && !hasDiscover) {
        return "error";
      }
      return searchActive || searchDone ? "done" : "pending";
    case "search":
      if (searchActive) {
        return "active";
      }
      if (searchDone) {
        return "done";
      }
      if (p === Phase.ERROR && !hasDiscover) {
        return "error";
      }
      return "pending";
    case "candidates":
      if (searchActive) {
        return "pending";
      }
      if (p === Phase.EMPTY || hasDocs || (hasDiscover && !hasDocs)) {
        return "done";
      }
      return "pending";
    case "read":
      if (genDone || genActive) {
        return "done";
      }
      if (hasSelection && p === Phase.DISCOVERED) {
        return "active";
      }
      if (hasDocs && p === Phase.DISCOVERED) {
        return "pending";
      }
      return "pending";
    case "generate":
      if (genDone) {
        return "done";
      }
      if (genActive) {
        return "active";
      }
      if (p === Phase.ERROR && hasDiscover && hasSelection) {
        return "error";
      }
      if (p === Phase.DISCOVERED && hasSelection && state.lastError) {
        return "error";
      }
      return "pending";
    default:
      return "pending";
  }
}

function renderProgressSteps() {
  const items = PROGRESS_STEPS.map((step, i) => {
    const st = progressStepStatus(step.id);
    const nodeContent =
      st === "done"
        ? "✓"
        : st === "active"
          ? '<span class="spinner spinner--step"></span>'
          : st === "error"
            ? "!"
            : String(i + 1);
    return `<li class="progress-step progress-step--${st}" data-step="${step.id}">
      <span class="progress-step__node" aria-hidden="true">${nodeContent}</span>
      <span class="progress-step__label">${esc(step.label)}</span>
    </li>`;
  }).join("");
  return `<div class="progress-track-wrap">
    <div class="progress-track__header">
      <span class="progress-track__eyebrow">Retrieval Pipeline</span>
      <span class="progress-track__title">검색 진행 단계</span>
    </div>
    <ol class="progress-track" aria-label="검색 진행 단계">${items}</ol>
  </div>`;
}

export function renderSidebar() {
  const el = document.getElementById("region-sidebar");
  if (!el) {
    return;
  }
  const savedDept = captureTextInput("inp-dept");
  const agentOpts = AGENTS.map(
    (a) =>
      `<option value="${esc(a.id)}" ${state.selectedAgentId === a.id ? "selected" : ""}>${esc(a.label)}</option>`
  ).join("");

  el.innerHTML = `
    <div class="sidebar__brand">
      <span class="sidebar__logo" aria-hidden="true">CH</span>
      <div>
        <div class="sidebar__title">ContextHub</div>
        <div class="sidebar__tagline">사내 문서 RAG</div>
      </div>
    </div>
    <nav class="sidebar__nav" aria-label="메뉴">
      <a class="nav-item nav-item--active" href="#" data-nav="search" id="nav-search">
        <span class="nav-item__icon" aria-hidden="true">⌕</span> 검색
      </a>
      <span class="nav-item nav-item--disabled" title="향후 확장">
        <span class="nav-item__icon" aria-hidden="true">💬</span> 채팅
      </span>
      <span class="nav-item nav-item--disabled" title="향후 확장">
        <span class="nav-item__icon" aria-hidden="true">⚙</span> 설정
      </span>
    </nav>
    <div class="sidebar__bottom">
    <div class="sidebar__agent">
      <label class="field-label" for="sel-agent">에이전트</label>
      <select id="sel-agent" class="select-agent">${agentOpts}</select>
      <p class="sidebar__hint">NAS RAG · POST /discover → /generate</p>
    </div>
    <div class="sidebar__poc-settings">
      <label class="field-label" for="inp-dept">부서 코드</label>
      <input id="inp-dept" class="input-compact" type="text"
        placeholder="infra, dev"
        value="${esc(state.deptCodesInput)}" />
      <details class="sidebar__advanced" id="adv-settings" ${state.advancedSettingsOpen ? "open" : ""}>
        <summary class="sidebar__advanced-summary">고급 설정</summary>
        <div class="sidebar__advanced-body">
          <div class="sidebar__row">
            <label class="field-label" for="inp-discover-k">discover top_k</label>
            <input id="inp-discover-k" class="input-compact input-compact--num" type="number" min="1" max="50"
              value="${esc(String(state.discoverTopK))}" />
          </div>
          <div class="sidebar__row">
            <label class="field-label" for="inp-gen-k">generate top_k</label>
            <input id="inp-gen-k" class="input-compact input-compact--num" type="number" min="1" max="50"
              value="${esc(String(state.generateTopK))}" />
          </div>
        </div>
      </details>
    </div>
    </div>
  `;
  restoreTextInput("inp-dept", savedDept);
}

function renderSearchHero() {
  const busyDiscover = state.phase === Phase.DISCOVERING;
  const discoverDisabled = !canStartDiscover();
  const showRequestMeta =
    state.phase === Phase.DISCOVERING ||
    state.phase === Phase.DISCOVERED ||
    state.phase === Phase.EMPTY ||
    state.phase === Phase.ERROR;
  const requestMeta =
    showRequestMeta && state.lastDiscoverTopK != null
      ? `<div class="request-meta">요청: discover top_k ${esc(
          String(state.lastDiscoverTopK)
        )} · dept ${esc(formatDeptCodes(state.lastDiscoverDeptCodes))}</div>`
      : "";

  return `
    <section class="card card--hero card--search-zone">
      <h1 class="hero-title">어떤 정보를 찾고 계신가요?</h1>
      <p class="hero-sub">질문 입력 → 문서 탐색 → 선택 → 답변 생성</p>
      <div class="search-bar search-bar--prominent">
        <span class="search-bar__icon" aria-hidden="true">⌕</span>
        <input id="inp-question" class="search-bar__input" type="search"
          placeholder="찾고 싶은 문서나 궁금한 내용을 입력하세요"
          value="${esc(state.question)}" autocomplete="off" />
        <button type="button" class="btn btn--primary btn--search" id="btn-discover" ${discoverDisabled ? "disabled" : ""}>
          ${busyDiscover ? '<span class="spinner"></span>' : ""}
          문서 검색
        </button>
      </div>
      ${requestMeta}
    </section>
  `;
}

function renderDocumentCards() {
  if (state.phase === Phase.DISCOVERING) {
    return `
      <section class="card">
        <h2 class="card__title">문서 후보</h2>
        <div class="skeleton-list">
          <div class="skeleton skeleton--card"></div>
          <div class="skeleton skeleton--card"></div>
          <div class="skeleton skeleton--card"></div>
        </div>
      </section>
    `;
  }

  if (state.phase === Phase.IDLE && !state.discoverResponse) {
    return "";
  }

  if (state.phase === Phase.EMPTY) {
    return `
      <section class="card card--empty">
        <h2 class="card__title">문서 후보</h2>
        <p class="empty-msg">
          관련 문서를 찾지 못했습니다. 질문을 더 구체적으로 바꾸거나,
          부서 코드/검색 top_k 설정을 조정해 보세요.
        </p>
      </section>
    `;
  }

  if (state.phase === Phase.ERROR && !state.discoverResponse) {
    return `
      <section class="card card--error">
        <h2 class="card__title">문서 후보</h2>
        <p class="error-msg">문서 탐색에 실패했습니다.</p>
        <p class="muted error-detail">${esc(
          state.lastError || "문서 탐색 중 오류"
        )}</p>
      </section>
    `;
  }

  const dr = state.discoverResponse;
  const listPhases = new Set([
    Phase.DISCOVERED,
    Phase.GENERATING,
    Phase.ANSWERED,
    Phase.ERROR,
  ]);
  if (!dr?.documents?.length || !listPhases.has(state.phase)) {
    return "";
  }

  const docs = sortedDocuments(dr.documents, state.sortDocumentsBy);
  const mx = maxTopScore(docs);
  const totalChunks = docs.reduce((s, d) => s + (d.matched_chunk_count || 0), 0);
  const selCount = state.selectedDocumentIds.size;
  const discoverTopK =
    state.lastDiscoverTopK != null ? String(state.lastDiscoverTopK) : "—";
  const discoverDept = formatDeptCodes(state.lastDiscoverDeptCodes);

  const cards = docs
    .map((d) => {
      const id = String(d.raw_document_id);
      const isSelected = state.selectedDocumentIds.has(id);
      const isHi = state.highlightedDocumentId === id;
      let cardCls = "doc-card";
      if (isSelected) {
        cardCls += " doc-card--selected";
      }
      if (isHi) {
        cardCls += " doc-card--highlight";
      }
      const w = mx > 0 ? Math.min(100, (d.top_score / mx) * 100) : 0;
      const fillClass = scoreBarFillClass(d.top_score, mx);
      const sections = (d.representative_sections || [])
        .slice(0, 3)
        .map((t) => `<span class="section-chip">${esc(t)}</span>`)
        .join("");
      const pk = d.project_key ? esc(d.project_key) : "—";
      const checked = isSelected ? "checked" : "";

      const matchedChunks = Array.isArray(d.matched_chunks) ? d.matched_chunks : [];
      const hintChunk = matchedChunks[0] || null;
      const hint = hintChunk
        ? extractMatchedFieldsAndTermsFromHighlights(hintChunk.highlights)
        : { matchedFields: [], highlightTerms: [] };
      const hintHtml =
        hint.matchedFields.length || hint.highlightTerms.length
          ? `<div class="doc-card__hint">
              <div class="doc-card__hint-row">
                <span class="hint-label">matched</span>
                <span class="hint-value">fields: ${esc(hint.matchedFields.join(", ") || "—")}</span>
                <span class="hint-value">· hit score: ${
                  hintChunk?.score != null
                    ? esc(Number(hintChunk.score).toFixed(3))
                    : "—"
                }</span>
              </div>
              <div class="doc-card__hint-terms">${renderTermPills(
                hint.highlightTerms
              )}</div>
            </div>`
          : "";
      return `
        <article class="${cardCls}" data-doc-id="${esc(id)}">
          <header class="doc-card__head">
            <input type="checkbox" class="doc-cb" data-doc-id="${esc(id)}" ${checked}
              aria-label="선택 ${esc(d.original_filename)}" />
            <span class="doc-card__ext">${esc(fileExt(d.original_filename))}</span>
            <h3 class="doc-card__title">${esc(d.original_filename)}</h3>
          </header>
          <div class="doc-card__meta">
            <span>📁 ${esc(d.path || "—")}</span>
            <span>project: ${pk}</span>
            ${accessBadge(d.access_scope)}
          </div>
          <div class="score-bar-wrap">
            <div class="score-bar"><div class="${fillClass}" style="width:${w.toFixed(1)}%"></div></div>
            <span class="score-label">score ${esc(d.top_score.toFixed(3))} · 청크 ${esc(d.matched_chunk_count)}</span>
          </div>
          ${hintHtml}
          <div class="doc-card__sections">${sections || '<span class="muted">—</span>'}</div>
        </article>
      `;
    })
    .join("");

  const genDisabled = !canStartGenerate();

  return `
    <section class="card card--docs">
      <header class="card__header">
        <h2 class="card__title">문서 후보 <span class="badge-count">${esc(dr.document_count)}</span></h2>
        <p class="card__meta">약 ${esc(totalChunks)}개 청크 · ${esc(dr.retrieval_latency_ms)}ms · ${esc(dr.search_backend)} · discover top_k ${esc(discoverTopK)} · dept ${esc(discoverDept)}</p>
      </header>
      <div class="toolbar-inline">
        <button type="button" class="btn btn--ghost" id="btn-sel-all">전체 선택</button>
        <button type="button" class="btn btn--ghost" id="btn-sel-none">선택 해제</button>
        <select id="sel-sort" class="select-compact" aria-label="정렬">
          <option value="score" ${state.sortDocumentsBy === "score" ? "selected" : ""}>점수순</option>
          <option value="chunks" ${state.sortDocumentsBy === "chunks" ? "selected" : ""}>청크 많은 순</option>
          <option value="name" ${state.sortDocumentsBy === "name" ? "selected" : ""}>파일명순</option>
        </select>
      </div>
      <div class="doc-list">${cards}</div>
      <footer class="card__footer">
        <button type="button" class="btn btn--primary" id="btn-generate" ${genDisabled ? "disabled" : ""}>
          ${state.phase === Phase.GENERATING ? '<span class="spinner"></span>' : ""}
          선택 문서로 답변 생성
        </button>
        <span class="sel-count">${selCount}개 선택</span>
      </footer>
    </section>
  `;
}

function renderAnswerBlock() {
  if (state.phase === Phase.GENERATING) {
    return `
      <section class="card card--answer card--answer-ai card--answer-loading">
        <header class="answer-ai__header">
          <span class="answer-ai__badge">✦ AI 답변</span>
          <span class="answer-ai__status"><span class="spinner spinner--sm"></span> 생성 중…</span>
        </header>
        <div class="answer-ai__body">
          <div class="skeleton skeleton--text"></div>
          <div class="skeleton skeleton--text skeleton--short"></div>
        </div>
      </section>
    `;
  }

  if (
    state.lastError &&
    state.discoverResponse &&
    (state.phase === Phase.DISCOVERED || state.phase === Phase.ERROR)
  ) {
    return `
      <section class="card card--error">
        <h2 class="card__title">답변 생성</h2>
        <p class="error-msg">답변 생성에 실패했습니다.</p>
        <p class="muted error-detail">${esc(state.lastError)}</p>
        <p class="muted" style="margin: 0.5rem 0 0; font-size: 0.82rem;">
          선택 문서를 다시 고르거나, 질문을 조금 더 구체화해 보세요.
        </p>
      </section>
    `;
  }

  const gr = state.generateResponse;
  if (!gr || state.phase !== Phase.ANSWERED) {
    return "";
  }

  const generateTopK =
    state.lastGenerateTopK != null ? String(state.lastGenerateTopK) : "—";
  const generateDept = formatDeptCodes(state.lastGenerateDeptCodes);

  return `
    <section class="card card--answer card--answer-ai card--fade-in">
      <header class="answer-ai__header">
        <span class="answer-ai__badge">✦ AI 답변</span>
        <span class="answer-ai__meta">
          검색 ${esc(gr.retrieval_latency_ms)}ms · LLM ${gr.llm_latency_ms != null ? esc(gr.llm_latency_ms) + "ms" : "—"} · 총 ${esc(gr.total_latency_ms)}ms
          ${gr.llm_mock ? ' · <span class="badge badge--mock">mock</span>' : ""}
          · generate top_k ${esc(generateTopK)} · dept ${esc(generateDept)}
        </span>
      </header>
      <div class="answer-ai__body">
        <pre class="answer-body" id="answer-pre"></pre>
      </div>
    </section>
  `;
}

export function renderCenter() {
  const el = document.getElementById("region-center");
  if (!el) {
    return;
  }
  const savedQuestion = captureTextInput("inp-question");
  el.innerHTML = `
    ${renderSearchHero()}
    <section class="card card--progress card--progress-featured">
      ${renderProgressSteps()}
    </section>
    ${renderDocumentCards()}
    ${renderAnswerBlock()}
  `;
  restoreTextInput("inp-question", savedQuestion);

  const pre = el.querySelector("#answer-pre");
  if (pre && state.generateResponse?.answer) {
    pre.textContent = state.generateResponse.answer;
  }
}

function renderSelectedDocs() {
  const ids = [...state.selectedDocumentIds];
  if (!ids.length) {
    return `<p class="muted">문서 후보에서 선택하세요.</p>`;
  }
  const deptCodes = state.lastGenerateDeptCodes ?? state.lastDiscoverDeptCodes;
  return ids
    .map((id) => {
      const d =
        state.discoverResponse?.documents?.find(
          (x) => String(x.raw_document_id) === id
        ) ?? null;
      const title = d ? d.original_filename : id.slice(0, 8) + "…";
      const pk = d?.project_key ? esc(d.project_key) : "—";
      const rawDocumentId = d?.raw_document_id != null ? String(d.raw_document_id) : id;
      const chunkCount =
        d?.matched_chunk_count != null
          ? d.matched_chunk_count
          : Array.isArray(d?.matched_chunks)
            ? d.matched_chunks.length
            : null;
      const summary = Array.isArray(d?.representative_sections)
        ? d.representative_sections
        : [];

      return `<div class="selected-doc-item ${state.highlightedDocumentId === id ? "selected-doc-item--hi" : ""}" data-doc-id="${esc(
        id
      )}">
        <div class="selected-doc-item__top">
          <span class="selected-doc-item__name" title="${esc(d ? d.original_filename : title)}">${ellipsisText(d ? d.original_filename : title, 48)}</span>
          <span class="selected-doc-item__id mono" title="${esc(rawDocumentId)}">${esc(shortId(rawDocumentId))}</span>
        </div>
        <div class="selected-doc-item__meta">
          <span>dept: ${esc(formatDeptCodes(deptCodes))}</span>
          <span>project: ${pk}</span>
          <span>chunks: ${esc(chunkCount != null ? String(chunkCount) : "—")}</span>
          ${d?.access_scope ? accessBadge(d.access_scope) : ""}
        </div>
        <div class="selected-doc-item__summary">
          ${
            summary.length
              ? summary
                  .slice(0, 4)
                  .map((t) => `<span class="section-chip section-chip--sm">${esc(t)}</span>`)
                  .join("")
              : `<span class="muted">요약 없음</span>`
          }
        </div>
      </div>`;
    })
    .join("");
}

function renderSourcesList() {
  if (state.phase === Phase.GENERATING) {
    return `<p class="muted"><span class="spinner spinner--sm"></span> 출처 불러오는 중…</p>`;
  }

  const gr = state.generateResponse;
  const sources = gr?.sources;
  if (!sources?.length) {
    if (state.phase === Phase.ANSWERED) {
      return `<p class="muted">선택한 문서 범위에서 근거를 찾지 못했습니다. 다른 문서를 선택하거나 질문을 조정해 보세요.</p>`;
    }
    return `<p class="muted">답변 생성 후 표시됩니다.</p>`;
  }

  const discoverDocs = state.discoverResponse?.documents || [];
  const byDoc = new Map();

  for (const s of sources) {
    const sid = s?.raw_document_id != null ? String(s.raw_document_id) : null;
    if (!sid) continue;
    const cur = byDoc.get(sid) || { sid, items: [] };
    cur.items.push(s);
    byDoc.set(sid, cur);
  }

  const groups = [...byDoc.values()]
    .map((g) => {
      const items = [...g.items].sort(
        (a, b) => (Number(b.score) || 0) - (Number(a.score) || 0)
      );
      const maxScore = items.reduce(
        (m, x) => Math.max(m, Number(x.score) || 0),
        0
      );
      const doc = discoverDocs.find((d) => String(d.raw_document_id) === g.sid) || null;
      return { sid: g.sid, items, maxScore, doc };
    })
    .sort((a, b) => b.maxScore - a.maxScore);

  return groups
    .map((g) => {
      const first = g.items[0];
      const title =
        g.doc?.original_filename ||
        first?.original_filename ||
        shortId(g.sid);
      const pk = g.doc?.project_key ? esc(g.doc.project_key) : "—";
      const accessScope = g.doc?.access_scope || first?.access_scope;
      const accessHtml = accessScope ? accessBadge(accessScope) : "";
      const chunksHtml = g.items
        .map((s) => {
          const sid = String(s.raw_document_id);
          const cid = String(s.chunk_id);
          const hi =
            state.highlightedSourceChunkId === cid
              ? "source-item source-item--hi"
              : "source-item";
          const sec = s.section_title ? esc(s.section_title) : "—";
          const pg = s.page_no != null ? `p.${esc(s.page_no)}` : "p.—";
          return `<button type="button" class="${hi}" data-src-doc="${esc(sid)}" data-src-chunk="${esc(cid)}">
            <span class="source-item__file">${esc(s.original_filename)}</span>
            <span class="source-item__detail">${sec} · ${pg} · score ${esc(Number(s.score).toFixed(3))}</span>
          </button>`;
        })
        .join("");

      return `<div class="source-doc-card" data-doc-id="${esc(g.sid)}">
        <div class="source-doc-card__head">
          <span class="source-doc-card__file" title="${esc(title)}">${ellipsisText(title, 48)}</span>
          <span class="source-doc-card__meta">project: ${pk} · chunks: ${g.items.length} · max score ${esc(
            g.maxScore.toFixed(3)
          )}</span>
          ${accessHtml}
        </div>
        <div class="source-doc-card__chunks">${chunksHtml}</div>
      </div>`;
    })
    .join("");
}

function renderGenerationContextChunks(ctx) {
  if (!ctx?.length) {
    return `<p class="muted">LLM에 전달된 chunk가 없습니다.</p>`;
  }
  return ctx
    .map((c, i) => {
      const fname = c.original_filename || "—";
      const sec = c.section_title ? esc(c.section_title) : "—";
      const preview = c.text_preview != null ? esc(c.text_preview) : "";
      return `<article class="gen-ctx-card" data-chunk-id="${esc(c.chunk_id)}">
        <header class="gen-ctx-card__head">
          <span class="gen-ctx-card__rank">#${esc(i + 1)}</span>
          <span class="gen-ctx-card__file" title="${esc(fname)}">${ellipsisText(fname, 40)}</span>
        </header>
        <dl class="gen-ctx-card__meta">
          <dt>chunk</dt><dd class="mono">${esc(c.chunk_no)} · ${esc(Number(c.score).toFixed(3))}</dd>
          <dt>section</dt><dd>${sec}</dd>
          <dt>chars</dt><dd>${esc(c.char_count)}${c.included_in_prompt ? ' · <span class="gen-ctx-card__tag">in prompt</span>' : ""}</dd>
        </dl>
        <pre class="gen-ctx-card__preview">${preview}</pre>
      </article>`;
    })
    .join("");
}

function renderDebugSection() {
  const dbg = state.generateResponse?.debug;
  const dr = state.discoverResponse;

  const genCtx = dbg?.generation_context_chunks;
  const genCtxSection =
    genCtx && genCtx.length
      ? `<section class="debug-subsection">
          <h3 class="debug-subsection__title">LLM context (generation_context_chunks)</h3>
          <div class="gen-ctx-list">${renderGenerationContextChunks(genCtx)}</div>
        </section>`
      : genCtx && genCtx.length === 0
        ? `<p class="muted">generation_context_chunks: (empty)</p>`
        : "";

  let chunkRows = "";
  if (dbg?.chunks?.length) {
    chunkRows = dbg.chunks
      .map(
        (c) => `<tr>
          <td>${esc(c.chunk_rank)}</td>
          <td>${esc(c.document_rank)}</td>
          <td class="mono">${esc(String(c.chunk_id).slice(0, 8))}…</td>
          <td>${esc(c.original_filename)}</td>
          <td>${esc(Number(c.score).toFixed(3))}</td>
          <td>${esc((c.matched_fields || []).join(", "))}</td>
          <td>${esc((c.highlight_terms || []).slice(0, 5).join(", "))}</td>
        </tr>`
      )
      .join("");
  }

  const debugBody = dbg
    ? `
      <dl class="debug-dl">
        <dt>original_query</dt><dd>${esc(dbg.original_query)}</dd>
        <dt>retrieval_query</dt><dd>${esc(dbg.retrieval_query)}</dd>
        <dt>normalization</dt><dd>${dbg.normalization_applied ? "true" : "false"}</dd>
        <dt>backend</dt><dd>${esc(dbg.backend)}</dd>
        <dt>retrieval_count</dt><dd>${esc(dbg.retrieval_count)}</dd>
      </dl>
      ${
        chunkRows
          ? `<div class="debug-table-wrap"><table class="debug-table">
        <thead><tr><th>chunk#</th><th>doc#</th><th>id</th><th>file</th><th>score</th><th>matched_fields</th><th>highlight_terms</th></tr></thead>
        <tbody>${chunkRows}</tbody></table></div>`
          : ""
      }
      <details class="debug-raw">
        <summary>전체 JSON</summary>
        <pre class="debug-pre">${esc(JSON.stringify(dbg, null, 2))}</pre>
      </details>
    `
    : `<p class="muted"><code>ENABLE_RETRIEVAL_DEBUG=true</code> 시 /generate 응답에 debug·<code>generation_context_chunks</code> preview가 포함됩니다.</p>`;

  const discoverSnippet =
    dr && state.phase !== Phase.IDLE
      ? `<details class="debug-raw">
          <summary>discover 메타</summary>
          <pre class="debug-pre">${esc(
            JSON.stringify(
              {
                original_query: dr.original_query,
                retrieval_query: dr.retrieval_query,
                normalization_applied: dr.normalization_applied,
                document_count: dr.document_count,
                search_backend: dr.search_backend,
              },
              null,
              2
            )
          )}</pre>
        </details>`
      : "";

  return `
    <details class="right-section__collapse" ${state.debugExpanded ? "open" : ""} id="debug-details">
      <summary>Retrieval debug${
        dbg?.chunks?.length ? ` (${esc(String(dbg.chunks.length))} chunks)` : ""
      }</summary>
      <div class="right-section__body debug-panel__body">${genCtxSection}${debugBody}${discoverSnippet}</div>
    </details>
  `;
}

export function renderRightPanel() {
  const el = document.getElementById("region-right");
  if (!el) {
    return;
  }
  el.innerHTML = `
    <section class="right-section">
      <h2 class="right-section__title">선택된 문서</h2>
      <div class="right-section__body" id="selected-docs-list">${renderSelectedDocs()}</div>
    </section>
    <section class="right-section">
      <h2 class="right-section__title">출처 (sources)</h2>
      <div class="right-section__body source-list">${renderSourcesList()}</div>
    </section>
    ${renderDebugSection()}
  `;
}

export function renderAll() {
  renderSidebar();
  renderCenter();
  renderRightPanel();
}
