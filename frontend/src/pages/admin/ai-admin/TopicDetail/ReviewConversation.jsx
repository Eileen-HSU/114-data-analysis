import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../shared/apiClient";
import { t, reviewFlagReasonText } from "../shared/taxStatus";
import { useAuth } from "../../../../hooks/AuthContext";

const LOCKED_STATUSES = ["confirmed", "modified", "excluded"];

const STATUS_LABEL = {
  pending_review: t("待審核", "Pending review"),
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

/**
 * Admin Human Review 對話面板。
 *
 * mode="start"：由 ClassificationList 的「開始審核」進入，掛載時會先
 *   呼叫 POST .../review/start。同一個 Admin 重複進入時，後端本來就
 *   是冪等的（回傳既有 active session），這裡不用另外判斷「是不是第
 *   一次」。如果 start 回 409（別的 Admin 正在審），不會擋住這個
 *   面板本身，而是轉成「唯讀 + 衝突提示」顯示。
 * mode="view"：由 confirmed/modified/excluded 這些已鎖定狀態的
 *   「查看」進入，不呼叫 start（呼叫了也一定 409，因為 review_status
 *   已經鎖定，不是「別人在審」而是「這筆已經結束」），只讀
 *   GET review + GET history。
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

  // 進入面板：mode="start" 才嘗試 start（冪等；409 轉成衝突顯示，
  // 不當成整個面板打不開）；mode="view" 只唯讀載入，不會去搶/建立
  // review session。
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

  // 目前這個 active session 的訊息，一律從 history 裡撈（GET review
  // 的 active_review 本身不含 messages，history 才有 include_messages）。
  const activeMessages = useMemo(() => {
    if (!activeReview) return [];
    const match = history.find((r) => r.review_id === activeReview.review_id);
    return match?.messages || [];
  }, [activeReview, history]);

  // 是否曾經有人送過訊息（不限哪個 session、哪個 Admin）——跟後端
  // _has_ever_entered_conversation() 用同一套判斷方式，決定要顯示
  // 「確認 AI 原始結果」還是「採用目前候選」。
  const hasEnteredConversation = useMemo(
    () => history.some((r) => (r.messages || []).some((m) => m.role === "user")),
    [history],
  );

  const isLocked = classification && LOCKED_STATUSES.includes(classification.review_status);

  // 有其他 Admin 持有 active session：可能來自 start() 回的 409（conflict
  // state），也可能是單純打開來看就發現 active_review.admin_id 不是自己
  // （例如透過「查看」進來，或頁面重新整理後 activeReview 還在但换了人）。
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
      // runAction 已經把錯誤放進 error / conflict，這裡不用再做什麼
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
      /* 錯誤已經顯示，這裡不用再處理 */
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
      /* 錯誤已經顯示，這裡不用再處理 */
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
        <button onClick={onClose}>{t("返回列表", "Back to list")}</button>
      </div>
    );
  }

  const segment = classification.answer_text.slice(classification.segment_start, classification.segment_end);

  return (
    <div className="admin-card review-conversation">
      <div className="review-conversation-header">
        <button onClick={onClose}>{t("← 返回列表", "← Back to list")}</button>
        <span className="review-status-badge">{STATUS_LABEL[classification.review_status] || classification.review_status}</span>
      </div>

      {error && <p className="ai-admin-error">{error}<button onClick={() => setError("")}>×</button></p>}

      {isConflict && (
        <p className="review-conflict-banner">
          ⚠ {t("此分類目前由", "This classification is currently being reviewed by")}{" "}
          <b>{conflictInfo.reviewing_admin_name || `Admin #${conflictInfo.reviewing_admin_id}`}</b>{" "}
          {t("審核中，你目前無法送出訊息、確認或排除，但仍可以查看資料與歷史紀錄。", "You cannot send messages, confirm, or exclude right now, but you can still view the data and history below.")}
        </p>
      )}

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

      {isLocked ? (
        <section className="review-section">
          <h3>{t("最終結果", "Final result")}</h3>
          {classification.review_status === "modified" ? (
            <CategoryBlock
              title={t("人工最終判斷", "Human final classification")}
              main={classification.final_main_category}
              sub={classification.final_sub_category}
              secondary={classification.final_secondary_sub_category}
              reasoning={classification.final_reasoning}
            />
          ) : (
            <p>
              {classification.review_status === "confirmed"
                ? t("已直接確認 AI 原始結果，沒有變更。", "AI original classification confirmed as-is, no changes.")
                : t("這筆分類已被排除，不會納入後續彙整分析。", "This classification has been excluded from further aggregation.")}
            </p>
          )}
        </section>
      ) : (
        <>
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
                rows={3}
              />
              <button onClick={handleSendMessage} disabled={isConflict || sending || !messageText.trim()}>
                {sending ? t("送出中…", "Sending…") : t("送出訊息", "Send message")}
              </button>
            </div>
          </section>

          <section className="review-section review-actions">
            <button
              onClick={handleConfirmCandidate}
              disabled={isConflict || busyAction !== "" || !hasEnteredConversation}
              title={!hasEnteredConversation ? t("尚未進入對話，請先在清單頁使用「確認 AI 原始結果」", "No conversation yet — use “Confirm AI original” from the list instead") : undefined}
            >
              {busyAction === "confirm-candidate" ? t("處理中…", "Working…") : t("採用目前候選", "Adopt current candidate")}
            </button>
            <button onClick={handleExclude} disabled={isConflict || busyAction !== ""} className="review-btn-danger">
              {busyAction === "exclude" ? t("處理中…", "Working…") : t("排除此分類", "Exclude this classification")}
            </button>
          </section>
        </>
      )}

      <section className="review-section">
        <h3>{t("審核歷史", "Review history")}</h3>
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
      </section>
    </div>
  );
}
