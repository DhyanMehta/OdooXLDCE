/**
 * Fail if saved OpenAPI schema/types drift from a fresh export+codegen.
 * Does not rewrite committed artifacts.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  OPENAPI_JSON,
  OPENAPI_TYPES,
  exportOpenApi,
  generateTypes,
  readText,
} from "./api-codegen.mjs";

function fail(message) {
  console.error(message);
  process.exit(1);
}

if (!fs.existsSync(OPENAPI_JSON)) {
  fail(`Missing ${OPENAPI_JSON}. Run npm run gen:api.`);
}
if (!fs.existsSync(OPENAPI_TYPES)) {
  fail(`Missing ${OPENAPI_TYPES}. Run npm run gen:api.`);
}

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "campusos-check-api-"));
try {
  const freshSchema = path.join(tmpDir, "openapi.json");
  const freshTypes = path.join(tmpDir, "openapi.d.ts");

  exportOpenApi(freshSchema);
  const savedSchema = readText(OPENAPI_JSON);
  const newSchema = readText(freshSchema);
  if (savedSchema !== newSchema) {
    fail(
      "OpenAPI schema is stale: frontend/openapi.json does not match a fresh backend export.\n" +
        "Run: npm run gen:api",
    );
  }

  generateTypes(freshSchema, freshTypes);
  const savedTypes = readText(OPENAPI_TYPES);
  const newTypes = readText(freshTypes);
  if (savedTypes !== newTypes) {
    fail(
      "Generated API types are stale: src/types/openapi.d.ts does not match openapi-typescript output.\n" +
        "Run: npm run gen:api",
    );
  }

  console.log("check:api OK — openapi.json and openapi.d.ts are up to date.");
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true });
}
