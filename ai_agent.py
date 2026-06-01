"""Entry point: run `python ai_agent.py` from the project root."""
import sys
from src.core.agent import main

if __name__ == "__main__":
    # 支持 --web 参数启动 Web UI
    if "--web" in sys.argv:
        from src.web.server import run_web_server

        # 解析端口参数
        port = 8000
        if "--port" in sys.argv:
            try:
                idx = sys.argv.index("--port")
                port = int(sys.argv[idx + 1])
            except (IndexError, ValueError):
                pass

        # 解析 host 参数
        host = "127.0.0.1"
        if "--host" in sys.argv:
            try:
                idx = sys.argv.index("--host")
                host = sys.argv[idx + 1]
            except IndexError:
                pass

        run_web_server(host=host, port=port)
    else:
        main()
