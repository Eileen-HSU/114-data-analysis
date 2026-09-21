import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../shared/apiClient";
import { t, reviewFlagReasonText } from "../shared/taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const LOCKED_STATUSES = ["confirmed", "modified", "excluded"];

const STATUS_LABEL = {
  pending_review: t("待處理", "Pending"),
  confirmed: t("已確認", "Confirmed"),
  modified: t("已修改", "Modified"),
  excluded: t("已排除", "Excluded"),
};

function CategoryBlock({ title, main, sub, secondary, reasoning }) {
  return (
    <div className="review-category-block">
      <h4>{title}</h4>
      <p><b>{t("大類別", "Main category")}</b>：{main || "—"}</p>
      <p><b>{t("子類別", "Sub category")}</b>：{sub || "—"}</p>
      <p><b>{t("次要子類別", "Secondary sub category")}</b>：{secondary || "—"}</p>
      <p><b>{t("判斷原因", "Reasoning")}</b>：{reasoning || "—"}</p>
    </div>
  );
}

function HistorySection({ history }) {
  // 【設計決策】審核歷史整段預設收合（外層 <details> 沒有 open），
  // 打開之後每個 session 自己也是獨立的 <details>，不會一次全部攤開
  // 一長串對話紀錄——這個區塊是「需要時查」的參考資料，不是這個畫面
  // 的主要工作內容。
  return (
    <details className="review-history-section">
      <summary>{t("審核歷史", "Review history")}（{history.length}）</summary>
      {history.length === 0 && <p className="review-empty-hint">{t("目前沒有任何審核紀錄。", "No review sessions yet.")}</p>}
      {history.map((r) => (
        <details key={r.review_id} className="review-history-entry">
          <summary>
            {r.admin_name || `Admin #${r.admin_id}`} · {r.status} · {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
            {r.confirmed_at ? ` → ${new Date(r.confirmed_at).toLocaleString()}` : ""}
          </summary>
          {(r.messages || []).length === 0 ? (
            <p className="review-empty-hint">{t("這個 session 沒有任何訊息。", "No messages in this session.")}</p>
          ) : (
            (r.messages || []).map((m) => (
              <div key={m.message_id} className={`review-message review-message--${m.role}`}>
                <b>{m.role === "user" ? t("管理員", "Admin") : "AI"}</b>
                <p>{m.content}</p>
              </div>
            ))
          )}
        </details>
      ))}
    </details>
  );
}

/**
 * Admin 審核工作台的「重新審核」畫面。
 *
 * mode="start"：由 ClassificationList 的「重新審核」進入，掛載時會先
 *   呼叫 POST .../review/start。同一個 Admin 重複進入時，後端本來就
 *   是冪等的（回傳既有 active session）。如果 start 回 409（別的
 *   Admin 正在審），不會擋住這個面板本身，而是轉成「唯讀 + 衝突提示」
 *   顯示。
 * mode="view"：由 confirmed/modified 這些已鎖定狀態的「查看審核紀錄」
 *   進入，不呼叫 start，只讀 GET review + GET history。
 */
export default function ReviewConversation({ classificationId, mode = "start", onClose, onChanged }) {
  const { user } = useAuth();
  const token = user?.token;
  const currentAdminId = user?.admin_id;

  const [reviewState, setReviewState] = useState(null); // { classification, active_review }
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(null); // { reviewing_admin_id, reviewing_admin_name }
  const [messageText, setMessageText] = useState("");
  const [sending, setSending] = useState(false);
  const [busyAction, setBusyAction] = useState(""); // "confirm-candidate" | "exclude" | ""

  const load = useCallback(async () => {
    try {
      setError("");
      const [state, historyRes] = await Promise.all([
        api(`/api/classification/${classificationId}/review`, token),
        api(`/api/classification/${classificationId}/review/history`, token),
      ]);
      setReviewState(state);
      setHistory(historyRes.reviews || []);
    } catch (e) {
      setError(e.message);
    }
  }, [classificationId, token]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setConflict(null);
      if (mode === "start") {
        try {
          await api(`/api/classification/${classificationId}/review/start`, token, { method: "POST" });
        } catch (e) {
          if (e.status === 409 && e.body?.reviewing_admin_id) {
            if (!cancelled) {
              setConflict({
                reviewing_admin_id: e.body.reviewing_admin_id,
                reviewing_admin_name: e.body.reviewing_admin_name,
              });
            }
          } else if (!cancelled) {
            setError(e.message);
          }
        }
      }
      if (!cancelled) {
        await load();
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classificationId, mode]);

  const classification = reviewState?.classification || null;
  const activeReview = reviewState?.active_review || null;

  const activeMessages = useMemo(() => {
    if (!activeReview) return [];
    const match = history.find((r) => r.review_id === activeReview.review_id);
    return match?.messages || [];
  }, [activeReview, history]);

  const hasEnteredConversation = useMemo(
    () => history.some((r) => (r.messages || []).some((m) => m.role === "user")),
    [history],
  );

  const isLocked = classification && LOCKED_STATUSES.includes(classification.review_status);

  const otherReviewerFromActive = useMemo(() => {
    if (!activeReview || currentAdminId == null || activeReview.admin_id === currentAdminId) return null;
    const matched = history.find((r) => r.review_id === activeReview.review_id);
    return { reviewing_admin_id: activeReview.admin_id, reviewing_admin_name: matched?.admin_name };
  }, [activeReview, currentAdminId, history]);

  const conflictInfo = conflict || otherReviewerFromActive;
  const isConflict = Boolean(conflictInfo) && !isLocked;

  const latestCandidateMessage = useMemo(
    () => [...activeMessages].reverse().find((m) => m.role === "assistant" && m.candidate_sub_category),
    [activeMessages],
  );

  const candidate = latestCandidateMessage
    ? {
      main_category: latestCandidateMessage.candidate_main_category,
      sub_category: latestCandidateMessage.candidate_sub_category,
      secondary_sub_category: latestCandidateMessage.candidate_secondary_sub_category,
      reasoning: latestCandidateMessage.candidate_reasoning,
    }
    : classification
      ? {
        main_category: classification.main_category,
        sub_category: classification.sub_category,
        secondary_sub_category: classification.secondary_sub_category,
        reasoning: classification.reasoning,
      }
      : null;

  const runAction = async (path, options) => {
    setError("");
    try {
      const result = await api(path, token, options);
      return result;
    } catch (e) {
      if (e.status === 409 && e.body?.reviewing_admin_id) {
        setConflict({
          reviewing_admin_id: e.body.reviewing_admin_id,
          reviewing_admin_name: e.body.reviewing_admin_name,
        });
      } else {
        setError(e.message);
      }
      throw e;
    }
  };

  const handleSendMessage = async () => {
    if (!messageText.trim() || sending) return;
    setSending(true);
    try {
      await runAction(`/api/classification/${classificationId}/review/message`, {
        method: "POST",
        body: JSON.stringify({ message: messageText.trim() }),
      });
      setMessageText("");
      await load();
    } catch {
      // runAction 已經把錯誤放進 error / conflict
    } finally {
      setSending(false);
    }
  };

  const handleConfirmCandidate = async () => {
    setBusyAction("confirm-candidate");
    try {
      await runAction(`/api/classification/${classificationId}/review/confirm-candidate`, { method: "POST" });
      await load();
      onChanged?.();
    } catch {
      /* 錯誤已經顯示 */
    } finally {
      setBusyAction("");
    }
  };

  const handleExclude = async () => {
    setBusyAction("exclude");
    try {
      await runAction(`/api/classification/${classificationId}/review/exclude`, { method: "POST" });
      await load();
      onChanged?.();
    } catch {
      /* 錯誤已經顯示 */
    } finally {
      setBusyAction("");
    }
  };

  if (loading) {
    return <div className="admin-card review-conversation"><p>{t("載入中…", "Loading…")}</p></div>;
  }

  if (!classification) {
    return (
      <div className="admin-card review-conversation">
        {error && <p className="ai-admin-error">{error}</p>}
        <button onClick={onClose}>{t("← 返回列表", "← Back to list")}</button>
      </div>
    );
  }

  const segment = classification.answer_text.slice(classification.segment_start, classification.segment_end);

  return (
    <div className="admin-card review-conversation">
      <div className="review-conversation-header">
        <button onClick={onClose}>{t("← 返回列表", "← Back to list")}</button>
        <span className={`review-status-tag review-status-tag--${classification.review_status}`}>
          {STATUS_LABEL[classification.review_status] || classification.review_status}
        </span>
      </div>

      {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

      {isConflict && (
        <p className="review-conflict-banner">
          ⚠ {t("此分類目前由", "This classification is currently being reviewed by")}{" "}
          <b>{conflictInfo.reviewing_admin_name || `Admin #${conflictInfo.reviewing_admin_id}`}</b>{" "}
          {t("審核中，你目前無法送出訊息、採用候選或不納入分析，但仍可以查看資料與歷史紀錄。", "You cannot send messages, adopt a candidate, or exclude right now, but you can still view the data and history below.")}
        </p>
      )}

      {isLocked ? (
        // ── 已鎖定狀態（confirmed / modified / excluded）：單欄唯讀 ──
        <div className="review-readonly">
          <section className="review-section">
            <h3>{t("原始回覆片段", "Original segment")}</h3>
            <p className="review-segment-text">{segment}</p>
          </section>

          {classification.review_status !== "excluded" && (
            <section className="review-section">
              <CategoryBlock
                title={t("AI 原始判斷", "AI original classification")}
                main={classification.main_category}
                sub={classification.sub_category}
                secondary={classification.secondary_sub_category}
                reasoning={classification.reasoning}
              />
            </section>
          )}

          {classification.review_status === "modified" && (
            <section className="review-section">
              <CategoryBlock
                title={t("人工最終判斷", "Human final classification")}
                main={classification.final_main_category}
                sub={classification.final_sub_category}
                secondary={classification.final_secondary_sub_category}
                reasoning={classification.final_reasoning}
              />
            </section>
          )}

          {classification.review_status === "confirmed" && (
            <p>{t("已直接接受 AI 分類，沒有變更。", "AI classification accepted as-is, no changes.")}</p>
          )}
          {classification.review_status === "excluded" && (
            <p>{t("這筆分類已被排除，不會納入後續彙整分析。", "This classification has been excluded from further aggregation.")}</p>
          )}

          <HistorySection history={history} />
        </div>
      ) : (
        // ── 進行中的審核：桌機兩欄 ──────────────────────────────
        // 左欄：這筆分類要看的核心資訊（原始回覆／AI 判斷／目前候選）
        // 右欄：實際跟 AI 討論的地方（對話 + 輸入框）
        // 操作按鈕放在兩欄下方、橫跨全寬，收尾動作跟「看資料」分開。
        <>
          <div className="review-layout">
            <div className="review-main">
              <section className="review-section">
                <h3>{t("原始回覆片段", "Original segment")}</h3>
                <p className="review-segment-text">{segment}</p>
              </section>

              <section className="review-section">
                <CategoryBlock
                  title={t("AI 原始判斷", "AI original classification")}
                  main={classification.main_category}
                  sub={classification.sub_category}
                  secondary={classification.secondary_sub_category}
                  reasoning={classification.reasoning}
                />
                <p>
                  {t("信心分數", "Confidence")}：{typeof classification.confidence === "number" ? classification.confidence.toFixed(2) : "—"}
                  {classification.needs_human_review && (
                    <span className="review-flag-badge">
                      {" "}⚠ {t("需人工審查", "Needs human review")}
                      {classification.review_flag_reason && ` — ${reviewFlagReasonText(classification.review_flag_reason)}`}
                    </span>
                  )}
                </p>
              </section>

              <section className="review-section">
                <h3>{t("目前候選分類", "Current candidate classification")}</h3>
                <CategoryBlock
                  title={t("候選", "Candidate")}
                  main={candidate?.main_category}
                  sub={candidate?.sub_category}
                  secondary={candidate?.secondary_sub_category}
                  reasoning={candidate?.reasoning}
                />
              </section>
            </div>

            <div className="review-side">
              <section className="review-section">
                <h3>{t("審核對話", "Review conversation")}</h3>
                <div className="review-message-list">
                  {activeMessages.length === 0 && <p className="review-empty-hint">{t("尚無對話，輸入意見後開始討論。", "No messages yet — type your feedback below to start the discussion.")}</p>}
                  {activeMessages.map((m) => (
                    <div key={m.message_id} className={`review-message review-message--${m.role}`}>
                      <b>{m.role === "user" ? t("管理員", "Admin") : "AI"}</b>
                      <p>{m.content}</p>
                    </div>
                  ))}
                </div>

                <div className="review-message-input">
                  <textarea
                    value={messageText}
                    onChange={(e) => setMessageText(e.target.value)}
                    placeholder={t("輸入你對這筆分類的意見…", "Type your feedback on this classification…")}
                    disabled={isConflict || sending}
                    rows={4}
                  />
                  <button onClick={handleSendMessage} disabled={isConflict || sending || !messageText.trim()}>
                    {sending ? t("送出中…", "Sending…") : t("送出訊息", "Send message")}
                  </button>
                </div>
              </section>
            </div>
          </div>

          <div className="review-bottom-actions">
            <button
              className="review-btn-primary"
              onClick={handleConfirmCandidate}
              disabled={isConflict || busyAction !== "" || !hasEnteredConversation}
              title={!hasEnteredConversation ? t("尚未進入對話，請先在清單頁使用「接受 AI 分類」", "No conversation yet — use “Accept AI classification” from the list instead") : undefined}
            >
              {busyAction === "confirm-candidate" ? t("處理中…", "Working…") : t("採用目前候選", "Adopt current candidate")}
            </button>
            <button onClick={handleExclude} disabled={isConflict || busyAction !== ""} className="review-btn-danger">
              {busyAction === "exclude" ? t("處理中…", "Working…") : t("不納入分析", "Exclude from analysis")}
            </button>
            <button onClick={onClose}>{t("返回列表", "Back to list")}</button>
          </div>

          <HistorySection history={history} />
        </>
      )}
    </div>
  );
}