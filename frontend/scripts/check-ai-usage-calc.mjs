// AI 用量與成本頁的試算器與金額格式：node scripts/check-ai-usage-calc.mjs
// 驗證：
//   - 問卷生成 + 回覆分析的 token／金額加總（平均與 P90）
//   - 有填平均字數時改用「每 1,000 字」計算
//   - 資料不足的部分不計入，並標示出來（不會用 0 假裝有資料）
//   - 有任一部分缺單價時，金額顯示「—」而不是少算的數字
//   - 金額格式：一律只顯示美金；小金額保留位數
import assert from "node:assert/strict";
import { estimate, fmtAmount, formatMoney } from "../src/pages/admin/ai-admin/shared/usageMath.js";

const stat = (avg, p90) => ({ avg, p90, n: 5 });
const metrics = {
  per_survey_generation: { tokens: stat(8000, 10000), cost_usd: stat(0.006, 0.008) },
  per_100_responses: { tokens: stat(20000, 30000), cost_usd: stat(0.002, 0.003) },
  per_1000_chars: { tokens: stat(2000, 2500), cost_usd: stat(0.0002, 0.0003) },
};

// 10 份問卷 × 每份 100 筆
let r = estimate(metrics, { surveys: 10, responses: 100, chars: null });
assert.equal(r.basis, "responses");
assert.equal(r.avg.generationTokens, 80000);
assert.equal(r.avg.analysisTokens, 200000);
assert.equal(r.avg.tokens, 280000);
assert.ok(Math.abs(r.avg.costUsd - (0.06 + 0.02)) < 1e-12);
assert.equal(r.high.tokens, 100000 + 300000);

// 有填平均字數 → 每 1,000 字：10 × 100 × 80 字 = 80,000 字 = 80 個千字
r = estimate(metrics, { surveys: 10, responses: 100, chars: 80 });
assert.equal(r.basis, "chars");
assert.equal(r.avg.analysisTokens, 80 * 2000);

// 問卷生成資料不足：只算分析，並標示
r = estimate({ ...metrics, per_survey_generation: null }, { surveys: 10, responses: 100, chars: null });
assert.equal(r.missingGeneration, true);
assert.equal(r.avg.tokens, 200000);

// 全部不足：tokens 為 null（畫面顯示「—」），不是 0
r = estimate({ per_survey_generation: null, per_100_responses: null, per_1000_chars: null }, { surveys: 1, responses: 1, chars: null });
assert.equal(r.avg.tokens, null);
assert.equal(r.avg.costUsd, null);

// 分析缺單價：金額不顯示（避免少算）
r = estimate({ ...metrics, per_100_responses: { tokens: stat(20000, 30000), cost_usd: null } }, { surveys: 1, responses: 100, chars: null });
assert.equal(r.avg.tokens, 28000);
assert.equal(r.avg.costUsd, null);

// 金額格式
assert.equal(formatMoney(null, 32), "—");
assert.equal(formatMoney(0.5, null), "US$ 0.500");
assert.equal(formatMoney(2, 32.5), "US$ 2.00");
assert.equal(fmtAmount(0.0004), "0.0004");
assert.equal(fmtAmount(0), "0.00");

console.log("check-ai-usage-calc: all passed");
