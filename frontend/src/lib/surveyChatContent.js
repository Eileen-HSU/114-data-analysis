function normalizeSurveyDetail(survey = {}, questions, responses) {
  const code = survey.code || survey.access_code || "";
  return {
    ...survey,
    id: survey.id || survey.template_id || code,
    title: survey.title || survey.survey_name || "Untitled survey",
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

  lines.push(`📋 Survey title: ${detail.title}`);
  lines.push(`🔑 Survey code: ${detail.code}`);
  lines.push(`🗓 Created: ${detail.createdAt}`);
  lines.push(`👥 Responses: ${detail.responses.length}  respondents`);
  lines.push(`❓ Questions: ${detail.questions.length}  questions`);
  lines.push("");

  if (ratingQuestions.length > 0) {
    lines.push("── Rating summary ──");
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

      const average = count > 0 ? (total / count).toFixed(1) : "No data";
      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || "Untitled question"}`);
      lines.push(`Average score: ${average} / 5（${count}  respondents)`);
    });
    lines.push("");
  }

  if (textQuestions.length > 0) {
    lines.push("── Open-ended responses ──");
    textQuestions.forEach((question) => {
      const qId = question.id !== undefined ? question.id : question.question_id;
      const answers = detail.responses
        .map((response) => ({
          answer: response.answers?.[qId],
          respondentIdentity: response.respondentIdentity || response.respondent_identity,
        }))
        .filter(({ answer }) => hasAnswerValue(answer));

      lines.push(`Q${detail.questions.indexOf(question) + 1}. ${question.title || question.question_title || "Untitled question"}`);
      lines.push(`（${answers.length}  responses)`);
      answers.forEach(({ answer, respondentIdentity }, index) => {
        const identityLabel = respondentIdentity ? `${respondentIdentity}：` : "";
        lines.push(`${index + 1}. ${identityLabel}${displayAnswer(answer)}`);
      });
      lines.push("");
    });
  }

  lines.push("Please analyze response trends, potential insights, and recommended next steps for this survey.");
  return lines.join("\n");
}
