import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 5 },
    { duration: "20s", target: 5 },
    { duration: "10s", target: 10 },
    { duration: "20s", target: 10 },
    { duration: "10s", target: 20 },
    { duration: "20s", target: 20 },
    { duration: "10s", target: 50 },
    { duration: "20s", target: 50 },
  ],
};

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:5001";
const EMAIL = __ENV.TEST_EMAIL;
const PASSWORD = __ENV.TEST_PASSWORD;

export default function () {
  const loginRes = http.post(
    `${BASE_URL}/api/login`,
    JSON.stringify({
      email: EMAIL,
      password: PASSWORD,
    }),
    {
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  check(loginRes, {
    "login 200": (r) => r.status === 200,
  });

  const body = loginRes.json();
  const token = body.token;

  if (!token) return;

  const workspaceRes = http.get(`${BASE_URL}/api/workspace/user`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  check(workspaceRes, {
    "workspace 200": (r) => r.status === 200,
  });

  sleep(1);
}
