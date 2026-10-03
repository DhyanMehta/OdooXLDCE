/**
 * Cross-platform helpers for OpenAPI export + openapi-typescript codegen.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND_ROOT = path.resolve(__dirname, "..");
export const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
export const OPENAPI_JSON = path.join(FRONTEND_ROOT, "openapi.json");
export const OPENAPI_TYPES = path.join(FRONTEND_ROOT, "src", "types", "openapi.d.ts");

export function resolvePython() {
  const win = process.platform === "win32";
  const candidates = [
    path.join(REPO_ROOT, "backend", ".venv", win ? "Scripts/python.exe" : "bin/python"),
    path.join(REPO_ROOT, "backend", ".venv", win ? "Scripts/python" : "bin/python3"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return win ? "python" : "python3";
}

export function exportOpenApi(destPath) {
  const py = resolvePython();
  const env = { ...process.env, APP_ENV: process.env.APP_ENV || "development" };
  const result = spawnSync(
    py,
    ["-m", "app.export_openapi", destPath],
    {
      cwd: path.join(REPO_ROOT, "backend"),
      env,
      encoding: "utf8",
      shell: false,
    },
  );
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(`OpenAPI export failed (exit ${result.status}): ${detail}`);
  }
}

export function generateTypes(schemaPath, typesPath) {
  const cli = path.join(
    FRONTEND_ROOT,
    "node_modules",
    "openapi-typescript",
    "bin",
    "cli.js",
  );
  if (!fs.existsSync(cli)) {
    throw new Error(`openapi-typescript CLI not found at ${cli}`);
  }
  const result = spawnSync(process.execPath, [cli, schemaPath, "-o", typesPath], {
    cwd: FRONTEND_ROOT,
    encoding: "utf8",
    shell: false,
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(`openapi-typescript failed (exit ${result.status}): ${detail}`);
  }
}

export function normalizeNewlines(text) {
  return text.replace(/\r\n/g, "\n");
}

export function readText(filePath) {
  return normalizeNewlines(fs.readFileSync(filePath, "utf8"));
}
