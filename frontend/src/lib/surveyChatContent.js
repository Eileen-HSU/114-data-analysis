function normalizeSurveyDetail(survey = {}, questions, responses) {
  const code = survey.code || survey.access_code || "";
  return {
    ...survey,
    id: survey.id || survey.template_id || code,
    title: survey.title || survey.survey_name || (typeof getLang === "function" && getLang() === "en" ? "Untitled survey" : "未命名問卷"),
    code,
    createdAt: survey.createdAt || survey.created_at || "",
    questions: Array.isArray(questions)
      ? questions
      : Array.isArray(survey.questions)
        ? survey.questions
        : [],
    responses: Array.isArray(responses)
      ? responses
      : Array.isArray(survey.responses)
        ? survey.responses
        : [],
  };
}

function getLang() {
  try {
    const v = localStorage.getItem("dataanalysis_language");
    if (v) return v;
    const nav = (navigator.language || navigator.userLanguage || "").toLowerCase();
    return nav.startsWith("zh") ? "zh" : "en";
  } catch (e) {
    return "en";
  }
}

function t(zh, en) {
  return getLang() === "en" ? en : zh;
}

function hasAnswerValue(answer) {
  if (Array.isArray(answer)) return answer.length > 0;
  return answer !== undefined && answer !== null && String(answer).trim() !== "";
}

function displayAnswer(answer) {
  if (Array.isArray(answer)) return answer.join("、");
  return String(answer);
}

export function buildSurveyChatContent(survey, questions, responses) {
  const detail = normalizeSurveyDetail(survey, questions, responses);
  const ratingQuestions = detail.questions.filter((q) => (q.type || q.question_type) === "rating");
  const textQuestions = detail.questions.filter((q) => (q.type || q.question_type) !== "rating");
  const lines = [];

  lines.push(`${t("📋 問卷名稱：","📋 Survey Title:")} ${detail.title}`);
  lines.push(`${t("🔑 問卷代碼：","🔑 Survey Code:")} ${detail.code}`);
  lines.push(`${t("🗓 建立日期：","🗓 Created At:")} ${detail.createdAt}`);
  lines.push(`${t("👥 回覆人數：","👥 Responses:")} ${detail.responses.length}`);
  lines.push(`${t("❓ 題目數量：","❓ Questions:")} ${detail.questions.length}`);
  lines.push("");

  if (ratingQuestions.length > 0) {
    lines.push("── 評分題統計 ──");
    ratingQuestions.forEach((question) => {
      const qId = question.id !== undefined ? question.id : question.question_id;
      let total = 0;
      let count = 0;

      detail.responses.forEach((response) => {
        const rawAnswer = response.answers?.[qId];
        const value = Number(rawAnswer);
        if (hasAnswerValue(rawAnswer) && !Number.isNaN(value)) {
          total += value;
          count += 1;
        }
      });

      const average = count > 0 ? (total / count).toFixed(1) : t("無資料","No data");
      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || (getLang() === "en" ? "Untitled question" : "未命名題目")}`);
      lines.push(`${t("平均分：","Average:")} ${average} / 5 (${count} ${t("人作答","responses")})`);
    });
    lines.push("");
  }

  if (textQuestions.length > 0) {
    lines.push(t("── 問答題回覆 ──","── Open-ended Responses ──"));
    textQuestions.forEach((question) => {
      const qId = question.id !== undefined ? question.id : question.question_id;
      const answers = detail.responses
        .map((response) => ({
          answer: response.answers?.[qId],
          respondentIdentity: response.respondentIdentity || response.respondent_identity,
        }))
        .filter(({ answer }) => hasAnswerValue(answer));

      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || (getLang() === "en" ? "Untitled question" : "未命名題目")}`);
      lines.push(`(${answers.length} ${t("人回答","responses")})`);
      answers.forEach(({ answer, respondentIdentity }, index) => {
        const identityLabel = respondentIdentity ? `${respondentIdentity}：` : "";
        lines.push(`${index + 1}. ${identityLabel}${displayAnswer(answer)}`);
      });
      lines.push("");
    });
  }

  lines.push(t("請協助我分析這份問卷的回答趨勢、可能洞察與後續建議。","Please help me analyze trends, insights, and follow-up suggestions for this survey."));
  return lines.join("\n");
}
