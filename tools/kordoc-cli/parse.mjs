#!/usr/bin/env node
/**
 * ContextHub kordoc CLI bridge (stdout JSON contract).
 *
 * Usage:
 *   node parse.mjs --input /path/to/file.hwp --ext hwp --filename "doc.hwp"
 *
 * Success stdout:
 *   { "ok": true, "markdown_text": "...", "blocks_json": [], "metadata_json": {},
 *     "page_count": null, "parser_name": "kordoc", "parser_version": "..." }
 *
 * Wire real kordoc by setting KORDOC_ENGINE_CMD to an executable that accepts:
 *   <engine> --input <path> --ext <ext>
 * and prints the same JSON shape to stdout.
 */

import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

function parseArgs(argv) {
  const out = { input: null, ext: null, filename: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--input") out.input = argv[++i];
    else if (a === "--ext") out.ext = argv[++i];
    else if (a === "--filename") out.filename = argv[++i];
  }
  return out;
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj));
}

function fail(message) {
  emit({ ok: false, error: message });
  process.exit(1);
}

const args = parseArgs(process.argv);
if (!args.input || !args.ext) {
  fail("missing --input or --ext");
}

const engineCmd = process.env.KORDOC_ENGINE_CMD?.trim();
if (engineCmd) {
  const parts = engineCmd.split(/\s+/);
  const res = spawnSync(parts[0], [...parts.slice(1), "--input", args.input, "--ext", args.ext], {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (res.status !== 0) {
    fail(res.stderr?.trim() || res.stdout?.trim() || `engine exit ${res.status}`);
  }
  process.stdout.write(res.stdout || "{}");
  process.exit(0);
}

// PoC fallback: no engine — document that operator must configure KORDOC_ENGINE_CMD.
const hint =
  "KORDOC_ENGINE_CMD is not set. Point it at your kordoc binary (or wrapper) that emits " +
  "ContextHub JSON on stdout. See docs/parser-architecture.md.";
try {
  readFileSync(args.input);
} catch (e) {
  fail(`cannot read input file: ${e.message}`);
}
fail(hint);
