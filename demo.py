"""One-command local demonstration of the two consistency judges."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_ROOT = ROOT / "Agent"
sys.path.insert(0, str(APP_ROOT))

from hw9_agent.webapp import ExerciseWebApp, serve  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动双一致性教师演示页面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = ExerciseWebApp(
        project_root=APP_ROOT,
        exercise_dir=APP_ROOT / "exercises" / "follow_user",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
    )
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"双一致性演示：{url}")
    print("页面右侧选择案例 A/B/C，点击“运行双检测”。按 Ctrl+C 停止。")
    serve(app, args.host, args.port)


if __name__ == "__main__":
    main()
