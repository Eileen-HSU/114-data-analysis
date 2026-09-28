import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../shared/apiClient";
import { errorMessage } from "../shared/reviewStates";
import { FailureNotice } from "../shared/StatusWidgets";
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
  const [busyAction, setBusyAction] = useState(""); // "confirm-candidate" | "confirm-manual" | "exclude" | ""
  // 送出後、AI 回覆前先把自己的訊息顯示出來，並顯示「AI 思考中」。
  const [pendingMessage, setPendingMessage] = useState("");
  const [aiNotice, setAiNotice] = useState(null); // { failure } | { rejected: true }
  const [manualSub, setManualSub] = useState("");
  const [manualSecondary, setManualSecondary] = useState("");
  const [manualReason, setManualReason] = useState("");
  const messageEndRef = useRef(null);

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
      setError(errorMessage(e));
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
            setError(errorMessage(e));
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
        setError(errorMessage(e));
      }
      throw e;
    }
  };

  const handleSendMessage = async () => {
    const text = messageText.trim();
    if (!text || sending) return;
    setSending(true);
    setAiNotice(null);
    setPendingMessage(text);
    setMessageText("");
    try {
      const result = await runAction(`/api/classification/${classificationId}/review/message`, {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });
      if (result?.ai_error) setAiNotice({ failure: result.ai_error });
      else if (result?.taxonomy_rejected) setAiNotice({ rejected: true });
      await load();
    } catch {
      // runAction 已經把錯誤放進 error / conflict；把沒送出的文字還給輸入框
      setMessageText(text);
    } finally {
      setPendingMessage("");
      setSending(false);
    }
  };

  // 「維持 AI 原始分類」：
  //   - 這個 session 還沒送出任何訊息 -> confirm-original（狀態：已確認）
  //   - 已經跟 AI 討論過 -> 依既有規則記為「已修改」（最終分類 = AI 原始），
  //     保留「曾提出異議」這個審核紀錄，用 confirm-manual 明確寫入原始分類。
  const aiOriginalInOptions = Boolean(
    classification?.sub_category
    && (reviewState?.taxonomy_options || []).some((o) => o.sub_category === classification.sub_category),
  );
  const discussedInSession = activeMessages.some((m) => m.role === "user");
  const handleKeepOriginal = async () => {
    setBusyAction("keep-original");
    try {
      if (!discussedInSession) {
        await runAction(`/api/classification/${classificationId}/review/confirm-original`, { method: "POST" });
      } else {
        await runAction(`/api/classification/${classificationId}/review/confirm-manual`, {
          method: "POST",
          body: JSON.stringify({
            sub_category: classification.sub_category,
            secondary_sub_category: classification.secondary_sub_category || undefined,
            reasoning: t("討論後維持 AI 原始分類", "Kept the AI's original classification after discussion"),
          }),
        });
      }
      await load();
      onChanged?.();
    } catch {
      /* 錯誤已經顯示 */
    } finally {
      setBusyAction("");
    }
  };

  const handleConfirmManual = async () => {
    if (!manualSub) return;
    setBusyAction("confirm-manual");
    try {
      await runAction(`/api/classification/${classificationId}/review/confirm-manual`, {
        method: "POST",
        body: JSON.stringify({
          sub_category: manualSub,
          secondary_sub_category: manualSecondary || undefined,
          reasoning: manualReason.trim() || undefined,
        }),
      });
      await load();
      onChanged?.();
    } catch {
      /* 錯誤已經顯示 */
    } finally {
      setBusyAction("");
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

  const options = reviewState?.taxonomy_options || [];
  const optionGroups = useMemo(() => {
    const groups = new Map();
    options.forEach((o) => {
      const key = o.main_category || t("（未分組）", "(Ungrouped)");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ value: o.sub_category, proposed: o.proposed });
    });
    return [...groups.entries()];
  }, [options]);

  // 預設選取目前候選（AI 建議或原始判斷），方便只改一點點就確認。
  useEffect(() => {
    if (!manualSub && candidate?.sub_category && options.some((o) => o.sub_category === candidate.sub_category)) {
      setManualSub(candidate.sub_category);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidate?.sub_category, options.length]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeMessages.length, pendingMessage]);

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
                {classification.answer_text && classification.answer_text !== segment && (
                  <details>
                    <summary>{t("查看完整回答", "Show full answer")}</summary>
                    <p className="review-segment-text">{classification.answer_text}</p>
                  </details>
                )}
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

              <section className="review-section review-manual-pick">
                <h3>{t("選擇最終分類", "Choose the final category")}</h3>
                {options.length === 0 ? (
                  <p className="review-empty-hint">{t("這筆資料沒有可用的分類清單，請先到「其他 / 未歸屬資料」指派主題。", "No category list is available for this item. Assign a topic first under Other / Unassigned.")}</p>
                ) : (
                  <>
                    <label>
                      <span className="review-field-label">{t("子類別", "Sub category")}</span>
                      <select value={manualSub} disabled={isConflict || busyAction !== ""} onChange={(e) => setManualSub(e.target.value)}>
                        <option value="">{t("請選擇…", "Choose…")}</option>
                        {optionGroups.map(([main, subs]) => (
                          <optgroup key={main} label={main}>
                            {subs.map((sub) => <option key={sub.value} value={sub.value}>{sub.value}{sub.proposed ? t("（AI 新提出）", " (new, proposed by AI)") : ""}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span className="review-field-label">{t("次要子類別（選填）", "Secondary (optional)")}</span>
                      <select value={manualSecondary} disabled={isConflict || busyAction !== ""} onChange={(e) => setManualSecondary(e.target.value)}>
                        <option value="">{t("無", "None")}</option>
                        {optionGroups.map(([main, subs]) => (
                          <optgroup key={main} label={main}>
                            {subs.filter((sub) => sub.value !== manualSub).map((sub) => <option key={sub.value} value={sub.value}>{sub.value}{sub.proposed ? t("（AI 新提出）", " (new, proposed by AI)") : ""}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span className="review-field-label">{t("判斷原因（選填）", "Reason (optional)")}</span>
                      <textarea rows={2} value={manualReason} disabled={isConflict || busyAction !== ""}
                        onChange={(e) => setManualReason(e.target.value)}
                        placeholder={t("為什麼歸到這一類？會寫進審核紀錄。", "Why this category? Saved to the audit log.")} />
                    </label>
                    <button className="review-btn-primary" onClick={handleConfirmManual}
                      disabled={isConflict || busyAction !== "" || !manualSub}>
                      {busyAction === "confirm-manual" ? t("處理中…", "Working…") : t("以此分類確認", "Confirm with this category")}
                    </button>
                  </>
                )}
              </section>
            </div>

            <div className="review-side">
              <section className="review-section">
                <h3>{t("跟 AI 討論（選用）", "Discuss with AI (optional)")}</h3>
                <p className="review-empty-hint">{t("可以請 AI 說明判斷理由或建議其他分類；AI 只能從分類清單裡建議。", "Ask the AI to explain or suggest another category; it can only suggest categories from the list.")}</p>
                <div className="review-message-list">
                  {activeMessages.length === 0 && !pendingMessage && <p className="review-empty-hint">{t("尚無對話。例如：「這段比較像在講工作量，應該歸哪一類？」", "No messages yet. e.g. “This seems to be about workload — which category fits?”")}</p>}
                  {activeMessages.map((m) => (
                    <div key={m.message_id} className={`review-message review-message--${m.role}`}>
                      <b>{m.role === "user" ? t("管理員", "Admin") : "AI"}</b>
                      <p>{m.content}</p>
                      {m.role === "assistant" && m.candidate_sub_category && (
                        <p className="review-candidate-chip">
                          {t("AI 建議：", "AI suggests: ")}{m.candidate_main_category} / {m.candidate_sub_category}
                          {m.candidate_secondary_sub_category ? `（${t("次要", "secondary")}：${m.candidate_secondary_sub_category}）` : ""}
                          <button type="button" disabled={isConflict || busyAction !== ""}
                            onClick={() => { setManualSub(m.candidate_sub_category); setManualSecondary(m.candidate_secondary_sub_category || ""); setManualReason(m.candidate_reasoning || ""); }}>
                            {t("套用到選擇", "Use this")}
                          </button>
                        </p>
                      )}
                    </div>
                  ))}
                  {pendingMessage && (
                    <>
                      <div className="review-message review-message--user"><b>{t("管理員", "Admin")}</b><p>{pendingMessage}</p></div>
                      <div className="review-message review-message--assistant"><b>AI</b><p><i className="ri-loader-4-line ri-spin" /> {t("AI 思考中…", "AI is thinking…")}</p></div>
                    </>
                  )}
                  <div ref={messageEndRef} />
                </div>

                {aiNotice?.failure && <FailureNotice failure={aiNotice.failure} />}
                {aiNotice?.rejected && (
                  <p className="review-flag-badge">{t("AI 這次建議的分類不在清單裡，已忽略；請再描述一次，或直接在左邊選擇分類。", "The AI suggested a category that is not in the list, so it was ignored. Rephrase or pick a category on the left.")}</p>
                )}

                <div className="review-message-input">
                  <textarea
                    value={messageText}
                    onChange={(e) => setMessageText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder={t("輸入你對這筆分類的意見（Enter 送出，Shift+Enter 換行）…", "Type your feedback (Enter to send, Shift+Enter for a new line)…")}
                    disabled={isConflict || sending || options.length === 0}
                    rows={3}
                  />
                  <button onClick={handleSendMessage} disabled={isConflict || sending || !messageText.trim() || options.length === 0}>
                    {sending ? t("AI 回覆中…", "Waiting for AI…") : t("送出訊息", "Send message")}
                  </button>
                </div>
              </section>
            </div>
          </div>

          <div className="review-bottom-actions">
            <button
              className="review-btn-primary"
              onClick={handleKeepOriginal}
              disabled={isConflict || busyAction !== "" || (discussedInSession && !aiOriginalInOptions)}
              title={discussedInSession
                ? t("已討論過，會記為「已修改」（最終分類＝AI 原始分類）", "Already discussed: recorded as Modified with the AI's original category")
                : t("直接接受 AI 原始分類（已確認）", "Accept the AI's original classification (Confirmed)")}
            >
              {busyAction === "keep-original" ? t("處理中…", "Working…") : t("維持 AI 原始分類", "Keep AI's original classification")}
            </button>
            <button
              onClick={handleConfirmCandidate}
              disabled={isConflict || busyAction !== "" || !latestCandidateMessage}
              title={!latestCandidateMessage ? t("AI 還沒有提出建議分類", "The AI has not suggested a category yet") : undefined}
            >
              {busyAction === "confirm-candidate" ? t("處理中…", "Working…") : t("採用 AI 最新建議", "Adopt AI's latest suggestion")}
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