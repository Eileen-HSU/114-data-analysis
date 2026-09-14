// Translate only application-generated activity labels from older releases.
// Captured project/survey names are kept verbatim.
const fixedLabels = {
  "進入工作區": "Opened workspace", "查看專案管理": "Viewed Project Management",
  "查看最近刪除": "Viewed Recently deleted", "查看個人資料": "Viewed profile",
  "進入問卷調查": "Opened surveys", "建立問卷頁面": "Opened survey creation",
  "填寫問卷頁面": "Opened survey response page", "更新個人資料": "Updated profile",
  "關閉雙因子驗證": "Disabled two-factor authentication",
};
const namedLabels = [
  [/^新增工作區 Chat「(.*)」$/s, 'Created workspace chat: '],
  [/^刪除工作區 Chat「(.*)」$/s, 'Deleted workspace chat: '],
  [/^刪除資料夾「(.*)」$/s, 'Deleted folder: '],
  [/^建立資料夾「(.*)」$/s, 'Created folder: '],
  [/^還原「(.*)」$/s, 'Restored: '],
  [/^建立問卷「(.*)」$/s, 'Created survey: '],
  [/^建立 AI 教材問卷「(.*)」$/s, 'Created AI-generated survey: '],
  [/^提交問卷回覆「(.*)」$/s, 'Submitted response to survey: '],
  [/^修改問卷「(.*)」截止時間$/s, 'Updated the deadline for survey: '],
  [/^重新命名資料夾為「(.*)」$/s, 'Renamed folder to: '],
  [/^重新命名檔案為「(.*)」$/s, 'Renamed file to: '],
];
export function englishActivityText(text) {
  if (fixedLabels[text]) return fixedLabels[text];
  for (const [pattern, prefix] of namedLabels) {
    const match = String(text || '').match(pattern);
    if (match) return prefix + match[1];
  }
  return text;
}
