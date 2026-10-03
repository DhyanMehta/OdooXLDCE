/**
 * Regenerate frontend/openapi.json from the backend, then TypeScript types.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  OPENAPI_JSON,
  OPENAPI_TYPES,
  exportOpenApi,
  generateTypes,
} from "./api-codegen.mjs";

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "campusos-gen-api-"));
try {
  const tmpSchema = path.join(tmpDir, "openapi.json");
  const tmpTypes = path.join(tmpDir, "openapi.d.ts");

  exportOpenApi(tmpSchema);
  fs.mkdirSync(path.dirname(OPENAPI_JSON), { recursive: true });
  fs.copyFileSync(tmpSchema, OPENAPI_JSON);

  generateTypes(OPENAPI_JSON, tmpTypes);
  fs.mkdirSync(path.dirname(OPENAPI_TYPES), { recursive: true });
  fs.copyFileSync(tmpTypes, OPENAPI_TYPES);

  console.log(`Wrote ${OPENAPI_JSON}`);
  console.log(`Wrote ${OPENAPI_TYPES}`);
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true });
}
