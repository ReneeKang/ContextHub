/**
 * Chat API client — thin fetch wrappers (no UI).
 * Boundaries: `/discover` vs `/generate` stay explicit for a future React service layer.
 */

const JSON_HEADERS = { "Content-Type": "application/json" };

/**
 * @param {unknown} detail FastAPI ``detail`` (string, object, or validation array).
 * @returns {string}
 */
export function formatApiErrorDetail(detail) {
  if (detail == null) {
    return "";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray(item.loc) ? item.loc.join(".") : "";
          return loc ? `${loc}: ${item.msg}` : String(item.msg);
        }
        return JSON.stringify(item);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

/**
 * @param {object|null|undefined} data Discover API JSON body.
 * @returns {boolean}
 */
export function isDiscoverEmpty(data) {
  if (!data) {
    return true;
  }
  const count = Number(data.document_count);
  if (Number.isFinite(count) && count > 0) {
    return false;
  }
  return !Array.isArray(data.documents) || data.documents.length === 0;
}

/**
 * @param {object} payload
 * @param {string} payload.question
 * @param {number} [payload.top_k]
 * @param {string[]|undefined} payload.test_department_codes
 */
/** @returns {{ question: string, top_k: number, test_department_codes?: string[] }} */
export function buildDiscoverPayload(payload) {
  const body = {
    question: payload.question,
    top_k: payload.top_k ?? 10,
  };
  if (payload.test_department_codes?.length) {
    body.test_department_codes = payload.test_department_codes;
  }
  return body;
}

/** @returns {{ question: string, document_ids: string[], top_k: number, test_department_codes?: string[] }} */
export function buildGeneratePayload(payload) {
  const body = {
    question: payload.question,
    document_ids: (payload.document_ids || [])
      .map((id) => String(id).trim())
      .filter(Boolean),
    top_k: payload.top_k ?? 5,
  };
  if (payload.test_department_codes?.length) {
    body.test_department_codes = payload.test_department_codes;
  }
  return body;
}

export async function postDiscover(payload) {
  const body = buildDiscoverPayload(payload);
  const res = await fetch("/api/v1/chat/discover", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  return _parseJsonOrThrow(res, "discover");
}

/**
 * @param {object} payload
 * @param {string} payload.question
 * @param {string[]} [payload.document_ids]
 * @param {number} [payload.top_k]
 * @param {string[]|undefined} payload.test_department_codes
 */
export async function postGenerate(payload) {
  const body = buildGeneratePayload(payload);
  if (!body.document_ids.length) {
    throw new Error("document_ids is required for generate");
  }
  const res = await fetch("/api/v1/chat/generate", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  return _parseJsonOrThrow(res, "generate");
}

async function _parseJsonOrThrow(res, label) {
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data ? data.detail : data;
    const msg = formatApiErrorDetail(detail) || `${label} failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}
