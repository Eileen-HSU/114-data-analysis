import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 1 },
    { duration: "20s", target: 1 },
    { duration: "10s", target: 3 },
    { duration: "20s", target: 3 },
    { duration: "10s", target: 5 },
    { duration: "20s", target: 5 },
  ],
};

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:5001";
const EMAIL = __ENV.ADMIN_EMAIL;
const PASSWORD = __ENV.ADMIN_PASSWORD;

export function setup() {
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
    "admin login 200": (r) => r.status === 200,
  });

  if (loginRes.status !== 200) {
    console.error(`Login failed: ${loginRes.status} ${loginRes.body}`);
    throw new Error("Admin login failed");
  }

  return {
    token: loginRes.json().token,
  };
}

export default function (data) {
  const headers = {
    Authorization: `Bearer ${data.token}`,
  };

  const responses = http.batch([
    [
      "GET",
      `${BASE_URL}/api/admin/ai/overview`,
      null,
      { headers, tags: { name: "admin_overview" } },
    ],
    [
      "GET",
      `${BASE_URL}/api/admin/ai/system/status`,
      null,
      { headers, tags: { name: "admin_status" } },
    ],
    [
      "GET",
      `${BASE_URL}/api/admin/ai/reports?page=1&page_size=1&needs_regeneration=true`,
      null,
      { headers, tags: { name: "admin_reports" } },
    ],
  ]);

  check(responses[0], {
    "overview 200": (r) => r.status === 200,
  });

  check(responses[1], {
    "status 200": (r) => r.status === 200,
  });

  check(responses[2], {
    "reports 200": (r) => r.status === 200,
  });

  sleep(1);
}