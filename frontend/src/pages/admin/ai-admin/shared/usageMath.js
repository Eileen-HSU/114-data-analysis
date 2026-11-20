// AI 用量與成本頁的計算（試算器、金額格式）。純函式，不呼叫 API；
// scripts/check-ai-usage-calc.mjs 會測這裡。

// 小金額保留較多位數，避免 0.0004 美金顯示成 0.00
export function fmtAmount(value) {
  if (value == null) return "—";
  const abs = Math.abs(value);
  const digits = abs === 0 ? 2 : abs < 0.01 ? 4 : abs < 1 ? 3 : 2;
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatMoney(usd, fx) {
  if (usd == null) return "—";
  if (!fx) return `US$ ${fmtAmount(usd)}`;
  return `NT$ ${fmtAmount(usd * fx)}（US$ ${fmtAmount(usd)}）`;
}

export function estimate(metrics, { surveys, responses, chars }) {
  const gen = metrics?.per_survey_generation;
  const per100 = metrics?.per_100_responses;
  const per1k = metrics?.per_1000_chars;
  const useChars = chars != null && per1k;
  const analysis = useChars ? per1k : per100;
  const analysisUnits = useChars ? (surveys * responses * chars) / 1000 : (surveys * responses) / 100;
  const pick = (key) => {
    const genTokens = gen ? gen.tokens[key] * surveys : null;
    const anaTokens = analysis ? analysis.tokens[key] * analysisUnits : null;
    const genCost = gen?.cost_usd ? gen.cost_usd[key] * surveys : null;
    const anaCost = analysis?.cost_usd ? analysis.cost_usd[key] * analysisUnits : null;
    const parts = [genTokens, anaTokens].filter((x) => x != null);
    const costParts = [genCost, anaCost].filter((x) => x != null);
    return {
      generationTokens: genTokens,
      analysisTokens: anaTokens,
      tokens: parts.length ? parts.reduce((a, b) => a + b, 0) : null,
      costUsd: costParts.length && costParts.length === parts.length ? costParts.reduce((a, b) => a + b, 0) : null,
    };
  };
  return { basis: useChars ? "chars" : "responses", avg: pick("avg"), high: pick("p90"), missingGeneration: !gen, missingAnalysis: !analysis };
}

