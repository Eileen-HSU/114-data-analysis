"""
測試腳本：routes/auth/pwd.py 的 send_email_via_brevo()。

用假的 sib_api_v3_sdk 取代真正的 Brevo SDK，不連網、不需要真的 API key，
驗證：
    1. 沒設定 BREVO_API_KEY / BREVO_FROM_EMAIL 時明確報錯
    2. 寄件者、收件者、主旨、純文字與 HTML 內容正確組出
    3. HTML 內容有跳脫，換行轉成 <br>
    4. Brevo 回錯誤時轉成 RuntimeError

執行方式：
    cd backend
    python3 tests/test_brevo_mail.py
"""

import os
import sys
import types

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

FAILED = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    if status == "FAIL":
        FAILED.append(label)
    print(f"[{status}] {label}")


# ── 假的 sib_api_v3_sdk ──
sent = []
fail_next = {"value": False}


class _FakeApiException(Exception):
    pass


class _FakeConfiguration:
    def __init__(self):
        self.api_key = {}


class _FakeApiClient:
    def __init__(self, configuration):
        self.configuration = configuration


class _FakeTransactionalEmailsApi:
    def __init__(self, api_client):
        self.api_client = api_client

    def send_transac_email(self, email):
        if fail_next["value"]:
            fail_next["value"] = False
            raise _FakeApiException("400 Bad Request")
        sent.append(email)


class _FakeSendSmtpEmail:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


fake_sdk = types.ModuleType("sib_api_v3_sdk")
fake_sdk.Configuration = _FakeConfiguration
fake_sdk.ApiClient = _FakeApiClient
fake_sdk.TransactionalEmailsApi = _FakeTransactionalEmailsApi
fake_sdk.SendSmtpEmail = _FakeSendSmtpEmail
fake_rest = types.ModuleType("sib_api_v3_sdk.rest")
fake_rest.ApiException = _FakeApiException
fake_sdk.rest = fake_rest
sys.modules["sib_api_v3_sdk"] = fake_sdk
sys.modules["sib_api_v3_sdk.rest"] = fake_rest

from routes.auth import pwd  # noqa: E402


def reset(api_key="", from_email="", from_name=None):
    pwd._brevo_client = None
    pwd._brevo_sender = None
    os.environ["BREVO_API_KEY"] = api_key
    os.environ["BREVO_FROM_EMAIL"] = from_email
    if from_name is None:
        os.environ.pop("BREVO_FROM_NAME", None)
    else:
        os.environ["BREVO_FROM_NAME"] = from_name


def raises(fn, text):
    try:
        fn()
    except RuntimeError as exc:
        return text in str(exc)
    return False


print("========== 1. 缺少設定 ==========")
reset(api_key="", from_email="noreply@example.com")
check("沒有 BREVO_API_KEY -> RuntimeError",
      raises(lambda: pwd.send_email_via_brevo("a@example.com", "s", "b"), "BREVO_API_KEY"))
reset(api_key="xkeysib-test", from_email="")
check("沒有 BREVO_FROM_EMAIL -> RuntimeError",
      raises(lambda: pwd.send_email_via_brevo("a@example.com", "s", "b"), "BREVO_FROM_EMAIL"))
check("缺少設定時沒有送出任何信", sent == [])

print("========== 2. 正常寄出 ==========")
reset(api_key="xkeysib-test", from_email="noreply@example.com")
pwd.send_email_via_brevo("user@example.com", "登入驗證碼", "驗證碼：123456\n<b>請勿轉寄</b>")
check("送出一封信", len(sent) == 1)
mail = sent[-1]
check("API key 放在 api-key 欄位",
      pwd._brevo_client.api_client.configuration.api_key.get("api-key") == "xkeysib-test")
check("收件者正確", mail.to == [{"email": "user@example.com"}])
check("寄件者預設名稱 DataAnalysis", mail.sender == {"email": "noreply@example.com", "name": "DataAnalysis"})
check("主旨正確", mail.subject == "登入驗證碼")
check("純文字內容保持原樣", mail.text_content == "驗證碼：123456\n<b>請勿轉寄</b>")
check("HTML 內容有跳脫且換行轉 <br>",
      mail.html_content == "<p>驗證碼：123456<br>&lt;b&gt;請勿轉寄&lt;/b&gt;</p>")

reset(api_key="xkeysib-test", from_email="noreply@example.com", from_name="問卷分析")
pwd.send_email_via_brevo("user@example.com", "s", "b")
check("BREVO_FROM_NAME 生效", sent[-1].sender["name"] == "問卷分析")

print("========== 3. Brevo 回錯誤 ==========")
fail_next["value"] = True
check("ApiException 轉成 RuntimeError",
      raises(lambda: pwd.send_email_via_brevo("user@example.com", "s", "b"), "Brevo 寄信失敗"))

print()
print("=" * 50)
if FAILED:
    print(f"共 {len(FAILED)} 項測試失敗：")
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
print("全部測試通過！")
