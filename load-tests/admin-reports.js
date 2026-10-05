import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "10s", target: 1 },
    { duration: "15s", target: 1 },
    { duration: "10s", target: 3 },
    { duration: "15s", target: 3 },
    { duration: "10s", target: 5 },
    { duration: "15s", target: 5 },
  ],
};

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:5001";

export function setup() {
  const res = http.post(
    `${BASE_URL}/api/login`,
    JSON.stringify({
      email: __ENV.ADMIN_EMAIL,
      password: __ENV.ADMIN_PASSWORD,
    }),
    {
      headers: { "Content-Type": "application/json" },
    }
  );

  check(res, {
    "admin login 200": (r) => r.status === 200,
  });

  return { token: res.json().token };
}

export default function (data) {
  const res = http.get(
    `${BASE_URL}/api/admin/ai/reports?page=1&page_size=1&needs_regeneration=true`,
    {
      headers: {
        Authorization: `Bearer ${data.token}`,
      },
      timeout: "15s",
    }
  );

  check(res, {
    "reports 200": (r) => r.status === 200,
  });

  sleep(1);
}
