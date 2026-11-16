import os
import threading
import webbrowser

from .app import config
from .app.server import AppServer
from .app.service import Session


def main() -> None:
    session = Session(home=config.data_dir())
    server = AppServer(session)
    print(f"인사발령장 자동생성기가 시작되었습니다: {server.base_url}", flush=True)
    print("이 창을 닫으면 프로그램이 종료됩니다.", flush=True)
    if not os.environ.get("INSA_TONGJI_NO_BROWSER"):
        threading.Timer(0.5, lambda: webbrowser.open(server.start_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
