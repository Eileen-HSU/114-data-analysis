"""
一次跑完 backend/tests/test_*.py（本專案的測試是「一支檔案一支腳本」，
失敗時以非 0 結束），給本機與 GitHub Actions 共用。

執行方式：
    cd backend
    python3 tests/run_all.py            # 全部
    python3 tests/run_all.py survey     # 只跑檔名含 survey 的

需要真實外部服務的測試（Gemini、MySQL、DATABASE_URL）在沒有設定對應
環境變數時會自己印 SKIP 並以 0 結束，這裡會把它們另外列出來。
"""

import glob
import os
import subprocess
import sys
import time

TIMEOUT_SECONDS = 300

# 已知偶發失敗、尚未修好的測試：最多重跑幾次，並在輸出中明確標示。
# 修好之後請從這裡移除。
KNOWN_FLAKY = {
    # SQLite 會忽略 SELECT ... FOR UPDATE，兩條 thread 的讀取也不在同一個
    # 快照裡；若一方在另一方查詢 published 版本前就 commit，後者會正常
    # archive 掉前者並發布，測試預期的「恰好一方得到 conflict」就不成立。
    "test_taxonomy_publish_concurrency": 3,
}

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_one(path):
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, path],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        output = proc.stdout + proc.stderr
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
        output += f"\nTIMEOUT after {TIMEOUT_SECONDS}s"
        code = -1
    return code, output, time.time() - start


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    paths = sorted(glob.glob(os.path.join(BACKEND_DIR, "tests", "test_*.py")))
    paths = [p for p in paths if pattern in os.path.basename(p)]

    failed, skipped, flaky_passed = [], [], []
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        attempts = KNOWN_FLAKY.get(name, 1)
        for attempt in range(1, attempts + 1):
            code, output, elapsed = run_one(path)
            if code == 0:
                break
            if attempt < attempts:
                print(f"::warning::{name} 失敗（已知偶發），重跑第 {attempt + 1}/{attempts} 次")

        if code != 0:
            failed.append(name)
            print(f"FAIL  {name} ({elapsed:.1f}s)")
            print("::group::" + name + " 輸出")
            print(output[-6000:])
            print("::endgroup::")
            continue

        is_skip = output.lstrip().startswith("SKIP")
        if is_skip:
            skipped.append(name)
            print(f"SKIP  {name}: {output.strip().splitlines()[0]}")
        else:
            print(f"PASS  {name} ({elapsed:.1f}s)" + (f"（第 {attempt} 次才通過）" if attempt > 1 else ""))
        if attempt > 1:
            flaky_passed.append(name)

    print()
    print("=" * 50)
    print(f"共 {len(paths)} 支：通過 {len(paths) - len(failed) - len(skipped)}、"
          f"略過 {len(skipped)}、失敗 {len(failed)}")
    for name in flaky_passed:
        print(f"::warning::{name} 重跑後才通過，這支測試需要修成穩定的版本")
    if failed:
        print("失敗：" + ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
