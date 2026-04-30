"""
UI Utils - 状态显示工具模块
提供状态动画、spinner 等终端 UI 效果
"""
import sys
import time
import threading


_status_stop_event = threading.Event()
_status_thread = None


def get_spinner_chars() -> list:
    """返回不同平台的转圈字符"""
    if sys.platform == "win32":
        return ["-", "\\", "|", "/"]
    return ["◐", "◓", "◑", "◒"]


def show_status(message: str, delay: float = 0.15):
    """
    在后台线程中显示状态动画
    使用 \\r 回到行首覆盖显示
    """
    global _status_stop_event
    spinners = get_spinner_chars()
    idx = 0

    sys.stdout.write("\033[?25l")  # 隐藏光标
    sys.stdout.flush()

    while not _status_stop_event.is_set():
        spinner = spinners[idx % len(spinners)]
        sys.stdout.write(f"\r\033[36m[{spinner}]\033[0m {message}")
        sys.stdout.flush()
        time.sleep(delay)
        idx += 1

    sys.stdout.write("\r" + " " * (len(message) + 10) + "\r")
    sys.stdout.flush()
    sys.stdout.write("\033[?25h")  # 恢复光标
    sys.stdout.flush()


def start_status(message: str) -> threading.Thread:
    """启动状态显示线程"""
    global _status_stop_event, _status_thread
    _status_stop_event.clear()
    _status_thread = threading.Thread(target=show_status, args=(message,))
    _status_thread.daemon = True
    _status_thread.start()
    return _status_thread


def stop_status(success: bool = True, final_msg: str = ""):
    """停止状态显示"""
    global _status_stop_event
    _status_stop_event.set()
    if _status_thread:
        _status_thread.join(timeout=0.5)

    if final_msg:
        icon = "\033[32m✓\033[0m" if success else "\033[31m✗\033[0m"
        print(f"{icon} {final_msg}")
