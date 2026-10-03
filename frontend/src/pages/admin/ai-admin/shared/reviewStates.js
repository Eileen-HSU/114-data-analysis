import { t } from "./taxStatus";

// ─────────────────────────────────────────────────────────────
// Admin 分類審核的狀態定義：必須跟後端逐字一致。
//   - CLASSIFICATION_STATES：routes/admin/ai_admin.py 的 CLASSIFICATION_STATES
//     （GET /api/admin/ai/classifications?state=... 與 status_counts 的 key）
//   - REVIEW_STATUSES：classification_models.py 的 ALLOWED_REVIEW_STATUSES
//   - UNASSIGNED_KINDS：services/admin_recovery_service.py 的 UNASSIGNED_KINDS
//   - OUTDATED_REASONS：services/report_service.py 的 OUTDATED_* 常數
// scripts/check-admin-status-mapping.mjs 會比對這幾組值與後端原始碼，
// 任何一邊改了另一邊沒跟上，檢查就會失敗。
// ─────────────────────────────────────────────────────────────

export const CLASSIFICATION_STATES = ["pending_review", "in_review", "failed", "confirmed", "modified", "excluded"];
export const REVIEW_STATUSES = ["pending_review", "confirmed", "modified", "excluded"];
export const UNASSIGNED_KINDS = ["unrouted", "failed", "legacy"];
export const UNKNOWN_LEGACY_COLUMN = "unknown_legacy_column";
export const OUTDATED_REASONS = [
  "classification_confirmed",
  "classification_modified",
  "classification_excluded",
  "classification_reopened",
  "classification_rerun",
  "bulk_review_action",
  "taxonomy_published",
  "new_results_added",
];

// 清單上的分頁籤（in_review 是 pending_review 的子集合，另外以 badge 顯示，
// 不另開分頁，避免同一筆出現在兩個分頁）。
export const STATE_TABS = ["pending_review", "confirmed", "modified", "excluded"];

export const stateLabel = (state) => ({
  pending_review: t("待處理", "Pending"),
  in_review: t("審核中", "In review"),
  failed: t("處理失敗", "Failed"),
  confirmed: t("已確認", "Confirmed"),
  modified: t("已修改", "Modified"),
  excluded: t("已排除", "Excluded"),
}[state] || state);

// 系統自動通過（review_status=confirmed + auto_confirmed=true）的顯示名稱，
// 跟人工確認的「已確認」區分。規則見後端 services/auto_confirm_service.py。
export const AUTO_CONFIRMED_LABEL = () => t("自動通過", "Auto-approved");
export const isAutoConfirmed = (row) => row?.review_status === "confirmed" && Boolean(row?.auto_confirmed);

export const unassignedKindLabel = (kind) => ({
  unrouted: t("未歸屬主題", "No topic"),
  failed: t("分類失敗", "Classification failed"),
  legacy: t("舊版資料", "Legacy data"),
}[kind] || kind);

export const isLegacyTechnicalTopic = (topic) => {
  const key = typeof topic === "string" ? topic : topic?.topic_key;
  const title = typeof topic === "string" ? topic : topic?.title;
  return Boolean(topic) && (key === UNKNOWN_LEGACY_COLUMN || title === UNKNOWN_LEGACY_COLUMN);
};

export const topicDisplayName = (topic) => {
  const title = typeof topic === "string" ? topic : topic?.title;
  return isLegacyTechnicalTopic(topic)
    ? t("舊資料欄位（無法辨識）", "Unidentified legacy column")
    : title || (typeof topic === "string" ? topic : topic?.topic_key) || "";
};

// Uploaded_Answer.routing_status / 未分類原因
export const unroutedReasonLabel = (reason) => ({
  unrouted: t("系統判斷不出主題（含信心不足）", "Topic could not be determined (incl. low confidence)"),
  routing_failed: t("主題判斷服務呼叫失敗", "Topic routing service failed"),
  no_topic_candidates: t("當時沒有任何已發布主題", "No published topic was available"),
  taxonomy_unavailable: t("主題沒有可用的已發布分類架構", "Topic has no usable published taxonomy"),
  classification_failed: t("已送分類但處理失敗", "Sent for classification but failed"),
  assigned: t("已人工指派主題", "Topic assigned by admin"),
  routed: t("已自動判斷主題", "Topic routed automatically"),
  auto_topic: t("已建立自動主題並用 AI 歸納的暫定分類分析", "Analysed with an AI-derived provisional taxonomy under an auto topic"),
  legacy_question_other: t("舊流程無法判斷主題的資料", "Legacy data without a topic"),
}[reason] || reason);

export const outdatedReasonLabel = (reason) => ({
  classification_confirmed: t("有分類結果被人工確認", "A classification was confirmed"),
  classification_modified: t("有分類結果被人工修改", "A classification was modified"),
  classification_excluded: t("有分類結果被排除", "A classification was excluded"),
  classification_reopened: t("有分類結果被重新開啟審核", "A classification was reopened"),
  classification_rerun: t("有回答被重新分類", "An answer was re-classified"),
  bulk_review_action: t("批次審核操作", "Bulk review action"),
  taxonomy_published: t("Taxonomy 發布新版本", "A new taxonomy version was published"),
  new_results_added: t("有新的分析結果加入", "New analysis results were added"),
  no_completed_report: t("尚未產生任何報告", "No report generated yet"),
  last_generation_failed: t("上一次產生失敗", "Last generation failed"),
  outdated: t("資料已變更", "Data changed"),
}[reason] || reason);

// 後端錯誤 code -> 具體的使用者訊息；沒有對應時用後端 message。
export const errorMessage = (e) => {
  const code = e?.body?.code;
  const name = e?.body?.reviewing_admin_name || (e?.body?.reviewing_admin_id ? `Admin #${e.body.reviewing_admin_id}` : "");
  const known = {
    REVIEW_IN_PROGRESS_BY_OTHER: t(`此分類目前由 ${name} 審核中，暫時無法操作。`, `Currently being reviewed by ${name}.`),
    ALREADY_FINALIZED: t("這筆分類已經確認或排除過了，請重新整理。", "Already confirmed or excluded. Please refresh."),
    CLASSIFICATION_FAILED: t("分類處理失敗，不能直接確認；請使用「重新處理」。", "Classification failed; use Retry instead."),
    CONVERSATION_STARTED: t("已進入審核對話，請在對話中確認。", "Conversation already started; confirm inside the review."),
    REPROCESS_BLOCKED_BY_REVIEW: t("這則回答已有人工定案的結果，請先重新開啟審核。", "This answer has reviewed results; reopen them first."),
    ALREADY_CLASSIFIED: t("這筆回答已經有分類結果。", "This answer is already classified."),
    TAXONOMY_UNAVAILABLE: t("這個主題目前沒有已發布的分類架構。", "This topic has no published taxonomy."),
    TAXONOMY_VERSION_NOT_USABLE: t("只能使用已發布或已封存的分類架構版本。", "Only published or archived taxonomy versions can be used."),
    TAXONOMY_PUBLISH_CONFLICT: t("另一位管理員剛剛發布了版本，請重新整理後再試。", "Another admin just published; refresh and retry."),
    REPORT_NOT_READY: t("目前沒有可以納入報告的分類結果。", "No classification results to report yet."),
    NEW_CATEGORY_NEEDS_DECISION: t("這筆是 AI 提出的新類別，請到「新類別候選」加入、合併或排除。", "This is an AI-proposed category. Add, merge or exclude it under New Category Candidates."),
    NEEDS_HUMAN_JUDGEMENT: t("這筆需要人工判斷，請逐筆確認。", "This item needs human judgement. Confirm it individually."),
    DRAFT_IN_PROGRESS: t("這個主題有還沒發布的分類架構草稿。請先到該主題的「分類架構」發布或刪除草稿，再加入新類別。", "This topic has an unpublished taxonomy draft. Publish or delete it in the topic's Taxonomy tab first."),
    CATEGORY_EXISTS: t("分類架構裡已經有這個類別，請改用「合併」。", "The taxonomy already has this category. Use Merge instead."),
    ADOPT_FAILED: t("發布失敗，分類架構和回答都維持原樣。", "Publishing failed. The taxonomy and answers were left unchanged."),
  };
  return (code && known[code]) || e?.body?.message || e?.message || t("操作失敗", "Action failed");
};
