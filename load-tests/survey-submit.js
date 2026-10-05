import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 10 },
    { duration: "20s", target: 10 },
    { duration: "10s", target: 20 },
    { duration: "20s", target: 20 },
    { duration: "10s", target: 50 },
    { duration: "20s", target: 50 },
    { duration: "10s", target: 100 },
    { duration: "20s", target: 100 },
  ],
};

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:5001";
const SURVEY_CODE = __ENV.SURVEY_CODE;

export default function () {
  const surveyRes = http.get(
    `${BASE_URL}/api/public/surveys/${SURVEY_CODE}`
  );

  check(surveyRes, {
    "survey load 200": (r) => r.status === 200,
  });

  const payload = {
    answers: {
      "1": "壓力測試測試回答",
    },
  };

  const submitRes = http.post(
    `${BASE_URL}/api/surveys/${SURVEY_CODE}/responses`,
    JSON.stringify(payload),
    {
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  check(submitRes, {
    "survey submit success": (r) =>
      r.status === 200 || r.status === 201,
  });

  sleep(1);
}
