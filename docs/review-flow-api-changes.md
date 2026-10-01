# 審核流程改版：後端 API 變更說明（給前端）

這次後端改了三件事：

1. **高信心結果自動通過**：分析完成時，信心 ≥ 0.75、類別在**已發布**分類架構內、沒有其他問題的結果，直接變成「已確認」，不用 Admin 手動確認。
2. **新類別一鍵採用**：「採用」會一次完成加入分類架構、發布新版本、這組回答全部確認。
3. **防止誤按**：新類別不能用快速確認／批次確認直接通過；需要人工判斷的結果不能批次確認。

AI 自動建立的主題（只有暫定分類架構、沒有已發布版本）**不會**自動通過，也不會被一鍵發布，行為維持原樣。

---

## 1. 新欄位：`auto_confirmed`

分類結果多了一個布林欄位 `auto_confirmed`，出現在：

| API | 位置 |
|---|---|
| `GET /api/admin/ai/classifications` | 每一筆 `classifications[]` |
| `GET /api/classification/<id>/review` | `classification` |
| `POST /api/classification/upload`、問卷分析 | 每一筆 `classifications[]` |
| `GET /api/admin/ai/topics/<topic_key>/answers` | 每一筆 `items[]`，另有 `auto_confirmed_count` |

判讀方式：

| `review_status` | `auto_confirmed` | 意思 | 建議顯示 |
|---|---|---|---|
| `confirmed` | `true` | 系統自動通過 | 「自動通過」（跟人工確認區分） |
| `confirmed` | `false` | 人工確認 | 「已確認」 |
| 其他 | 一律 `false` | 跟以前一樣 | 跟以前一樣 |

自動通過的結果 `reviewed_by_admin_id` 是 `null`。

## 2. 自動通過的結果可以直接處理

對單筆審核動作來說，自動通過的結果**不需要先「重新開啟」**：

| 動作 | 對自動通過的結果 |
|---|---|
| `confirm-original`（快速確認） | 變成人工確認（`auto_confirmed=false`、記錄審核人） |
| `confirm-manual`（手動指定類別） | 直接改，變成 `modified` |
| `exclude`（排除） | 直接排除 |
| `start`（開始審核對話） | **自動重新開啟**：回到 `pending_review` 並建立對話 |
| `reopen` | 照舊 |
| `batch-confirm` | **跳過**（回報 `ALREADY_FINALIZED`），避免一次把大量自動結果蓋上人工確認 |

所以前端在自動通過的結果上，可以跟待審的一樣顯示「確認／修改／排除／審核」按鈕。

## 3. Admin 清單：篩選自動通過

`GET /api/admin/ai/classifications` 新增參數：

- `auto_confirmed=true`：只看自動通過的（給「抽查」用）
- `auto_confirmed=false`：排除自動通過的

回應新增 `auto_confirmed_count`（套用 topic / needs_human_review 篩選後、自動通過的總筆數）。

## 4. 批次確認的新規則

`POST /api/classification/review/batch-confirm` 的 `skipped[]` 多了兩種 `code`：

| code | 原因 | 建議提示 |
|---|---|---|
| `NEEDS_HUMAN_JUDGEMENT` | 低信心、分類不完整等需要人看的 | 「需要逐筆確認」 |
| `NEW_CATEGORY_NEEDS_DECISION` | AI 提出的新類別 | 「請到新類別候選處理」 |

## 5. 快速確認新類別會被擋

`POST /api/classification/<id>/review/confirm-original` 對 AI 新類別（`status=new_category`）回：

```
409 { "code": "NEW_CATEGORY_NEEDS_DECISION", "message": "這筆是 AI 提出的新類別，不能直接確認。…" }
```

建議畫面上對新類別隱藏「快速確認」，改成導到「新類別候選」頁。`confirm-manual`（改成既有類別）和 `exclude` 仍然可以用。

## 6. 新類別一鍵採用

`POST /api/admin/ai/new-categories/adopt`，body 不變：`{topic_key, main_category, sub_category, definition?}`

回應 201：

```json
{
  "published": true,
  "taxonomy_version": { "version_id": 12, "version_number": 3, "status": "published", ... },
  "category": { ... },
  "confirmed_ids": [101, 102],
  "confirmed_count": 2,
  "skipped": [],
  "message": "已加入並發布 v3，2 筆回答已確認。"
}
```

- `published: false`：主題沒有已發布的分類架構（AI 自動主題），**只加進草稿**，回答維持待處理。請顯示 `message`。
- `skipped[]`：個別回答沒能確認（例如別的 Admin 正在審核），回答仍是待處理。
- `definition` 沒填時，後端會用「當回覆主要涉及「X」相關內容時，歸入此類別。」當預設定義。建議讓 Admin 有機會填寫，因為它會直接進入 AI 的分類規則。

錯誤：

| HTTP | code | 意思 |
|---|---|---|
| 409 | `DRAFT_IN_PROGRESS` | 這個主題有尚未發布的草稿，請先到分類架構頁發布或刪除 |
| 409 | `CATEGORY_EXISTS` | 已發布的架構已經有這個類別，請改用合併 |
| 409 | `ADOPT_FAILED` | 發布失敗，分類架構和回答都維持原樣 |
| 404 | `NOTHING_TO_ADOPT` | 這組已經沒有待處理的回答 |

## 7. 既有資料補做自動通過（新 API）

功能上線前已經分析好的資料不會自動改變。Admin 可以用這支 API 補做：

`POST /api/admin/ai/classifications/auto-confirm`

- body `{}` 或 `{"dry_run": true}`：**只預覽**，回 `eligible_count` 和前 500 筆 `classification_ids`，不寫入
- body `{"dry_run": false}`：實際執行，逐筆寫 audit（`auto_confirm_backfill`），相關報告標成過期

不會動到：低信心等需要人看的、正在審核或進過審核對話的、沒有分類架構版本的舊資料、暫定（未發布）分類架構的結果。重複執行是安全的。

建議做成 Admin 頁面上的一個按鈕：先預覽「將有 N 筆自動通過」，確認後再執行。

## 8. 報告

- 自動通過的結果**會進入報告**（跟人工確認一樣）。
- 報告完成度（readiness）新增 `auto_confirmed`：`confirmed` 之中由系統自動通過的筆數。

## 9. 其他後端行為（前端不用改，但要知道）

- 自動通過的結果**不會**被當成「人工審核範例」回饋給 AI。
- 自動通過的結果**可以**重新分析（人工確認的才受保護）。
- 緊急開關：後端環境變數 `AUTO_CONFIRM_HIGH_CONFIDENCE=0` 可以關閉新資料的自動通過。
