// 前後端 Admin 狀態 enum 一致性檢查：
//   node scripts/check-admin-status-mapping.mjs
// 比對 src/pages/admin/ai-admin/shared/reviewStates.js 與後端原始碼裡的
// 狀態常數，任何一邊新增 / 改名而另一邊沒跟上就失敗（exit 1）。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.resolve(root, "..", "backend");
const read = (p) => fs.readFileSync(p, "utf8");

const frontendSource = read(path.join(root, "src/pages/admin/ai-admin/shared/reviewStates.js"));
const frontendArray = (name) => {
  const match = frontendSource.match(new RegExp(`export const ${name} = \\[([\\s\\S]*?)\\];`));
  assert.ok(match, `frontend ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
};
const pyConstants = (file, prefix) => {
  const source = read(path.join(backend, file));
  return [...source.matchAll(new RegExp(`^${prefix}[A-Z_]* = "([^"]+)"`, "gm"))].map((m) => m[1]);
};
const sorted = (xs) => [...xs].sort();

// 1. 清單 state（ai_admin.py CLASSIFICATION_STATES）
const aiAdmin = read(path.join(backend, "routes/admin/ai_admin.py"));
const statesMatch = aiAdmin.match(/CLASSIFICATION_STATES = \(([^)]*)\)/);
assert.ok(statesMatch, "backend CLASSIFICATION_STATES not found");
const backendStates = [...statesMatch[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
assert.deepEqual(frontendArray("CLASSIFICATION_STATES"), backendStates, "CLASSIFICATION_STATES mismatch");

// 2. review_status（classification_models.py REVIEW_STATUS_*）
assert.deepEqual(sorted(frontendArray("REVIEW_STATUSES")), sorted(pyConstants("classification_models.py", "REVIEW_STATUS_")), "REVIEW_STATUSES mismatch");

// 3. 未分類 kinds（admin_recovery_service.py KIND_*）
assert.deepEqual(sorted(frontendArray("UNASSIGNED_KINDS")), sorted(pyConstants("services/admin_recovery_service.py", "KIND_")), "UNASSIGNED_KINDS mismatch");

// 4. report outdated reasons（report_service.py OUTDATED_*）
assert.deepEqual(sorted(frontendArray("OUTDATED_REASONS")), sorted(pyConstants("services/report_service.py", "OUTDATED_")), "OUTDATED_REASONS mismatch");

// 5. 每個 state / kind / reason 都有中英文 label（沒有漏掉而直接顯示英文 key）
for (const state of frontendArray("CLASSIFICATION_STATES")) {
  assert.ok(frontendSource.includes(`  ${state}: t(`), `missing label for state ${state}`);
}
for (const reason of frontendArray("OUTDATED_REASONS")) {
  assert.ok(frontendSource.includes(`  ${reason}: t(`), `missing label for outdated reason ${reason}`);
}
for (const tab of frontendArray("STATE_TABS")) {
  assert.ok(backendStates.includes(tab), `STATE_TABS contains unknown state ${tab}`);
}

console.log(`Admin status mapping OK: ${backendStates.length} states, ${frontendArray("OUTDATED_REASONS").length} outdated reasons, ${frontendArray("UNASSIGNED_KINDS").length} unassigned kinds.`);
