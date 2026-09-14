function normalizeSurveyDetail(survey = {}, questions, responses) {
  const code = survey.code || survey.access_code || "";
  return {
    ...survey,
    id: survey.id || survey.template_id || code,
    title: survey.title || survey.survey_name || "未命名問卷",
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

  lines.push(`📋 問卷名稱：${detail.title}`);
  lines.push(`🔑 問卷代碼：${detail.code}`);
  lines.push(`🗓 建立日期：${detail.createdAt}`);
  lines.push(`👥 回覆人數：${detail.responses.length} 人`);
  lines.push(`❓ 題目數量：${detail.questions.length} 道`);
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

      const average = count > 0 ? (total / count).toFixed(1) : "無資料";
      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || "未命名題目"}`);
      lines.push(`平均分：${average} / 5（${count} 人作答）`);
    });
    lines.push("");
  }

  if (textQuestions.length > 0) {
    lines.push("── 問答題回覆 ──");
    textQuestions.forEach((question) => {
      const qId = question.id !== undefined ? question.id : question.question_id;
      const answers = detail.responses
        .map((response) => ({
          answer: response.answers?.[qId],
          respondentIdentity: response.respondentIdentity || response.respondent_identity,
        }))
        .filter(({ answer }) => hasAnswerValue(answer));

      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || "未命名題目"}`);
      lines.push(`（${answers.length} 人回答）`);
      answers.forEach(({ answer, respondentIdentity }, index) => {
        const identityLabel = respondentIdentity ? `${respondentIdentity}：` : "";
        lines.push(`${index + 1}. ${identityLabel}${displayAnswer(answer)}`);
      });
      lines.push("");
    });
  }

  lines.push("請協助我分析這份問卷的回答趨勢、可能洞察與後續建議。");
  return lines.join("\n");
}
