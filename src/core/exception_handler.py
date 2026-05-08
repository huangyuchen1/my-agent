"""
Kimi API 异常处理模块
提供统一的异常分类、重试机制和错误格式化
"""
import functools
import time
from enum import Enum
from typing import Any, Callable, Optional, Tuple


class ErrorCode(Enum):
    BAD_REQUEST = 400
    AUTH_ERROR = 401
    PERMISSION_DENIED = 403
    NOT_FOUND = 404
    RATE_LIMIT = 429
    SERVER_ERROR = 500


ERROR_CODES = {
    400: "请求错误",
    401: "认证错误",
    403: "权限错误",
    404: "资源不存在",
    429: "限流/额度不足",
    500: "服务端错误"
}

ERROR_MESSAGES = {
    "content_filter": "内容涉及敏感信息，请调整输入内容",
    "invalid_request": "请求格式错误，请检查参数",
    "token_too_long": "输入内容过长，请缩短或分段处理",
    "invalid_authentication": "API Key 无效，请检查配置",
    "incorrect_api_key": "API Key 错误，注意 platform.kimi.ai 和 platform.kimi.com 的 Key 不能混用",
    "permission_denied": "权限不足，该 API 可能未对您开放",
    "resource_not_found": "资源不存在，可能是模型名称错误",
    "engine_overloaded": "服务繁忙，请稍后重试",
    "quota_exceeded": "账户额度不足，请检查余额",
    "rate_limit_reached": "请求过于频繁，请降低频率",
    "server_error": "Kimi 服务器内部错误，请稍后重试",
}


def _extract_status_code(error_str: str) -> Optional[int]:
    for code in [400, 401, 403, 404, 429, 500]:
        if str(code) in error_str:
            return code
    return None


def _classify_by_message(error_str: str) -> Tuple[str, str]:
    error_lower = error_str.lower()

    if "401" in error_str or "authentication" in error_lower or "api_key" in error_lower:
        if "incorrect" in error_lower:
            return "incorrect_api_key", ERROR_MESSAGES["incorrect_api_key"]
        return "invalid_authentication", ERROR_MESSAGES["invalid_authentication"]

    if "403" in error_str or "permission" in error_lower:
        return "permission_denied", ERROR_MESSAGES["permission_denied"]

    if "404" in error_str or "not found" in error_lower:
        return "resource_not_found", ERROR_MESSAGES["resource_not_found"]

    if "429" in error_str or "rate_limit" in error_lower or "overload" in error_lower:
        if "quota" in error_lower or "exceeded" in error_lower or "suspended" in error_lower:
            return "quota_exceeded", ERROR_MESSAGES["quota_exceeded"]
        if "concurrency" in error_lower or "rpm" in error_lower or "tpm" in error_lower or "tpd" in error_lower:
            return "rate_limit_reached", ERROR_MESSAGES["rate_limit_reached"]
        return "engine_overloaded", ERROR_MESSAGES["engine_overloaded"]

    if "500" in error_str or "server_error" in error_lower:
        return "server_error", ERROR_MESSAGES["server_error"]

    if "400" in error_str or "invalid_request" in error_lower:
        if "token" in error_lower and ("too long" in error_lower or "exceeded" in error_lower):
            return "token_too_long", ERROR_MESSAGES["token_too_long"]
        if "content_filter" in error_lower or "high risk" in error_lower:
            return "content_filter", ERROR_MESSAGES["content_filter"]
        return "invalid_request", ERROR_MESSAGES["invalid_request"]

    return "unknown", f"未知错误: {error_str[:100]}"


def classify_error(error: Exception) -> Tuple[str, str, bool, Optional[int]]:
    """
    分类异常并返回处理信息。
    返回: (error_category, user_message, can_retry, status_code)
    """
    error_str = str(error)
    status_code = _extract_status_code(error_str)

    if status_code:
        if status_code == 429:
            category, msg = _classify_by_message(error_str)
            return category, msg, True, status_code
        elif status_code == 500:
            return "server_error", ERROR_MESSAGES["server_error"], True, status_code
        elif status_code == 401:
            category, msg = _classify_by_message(error_str)
            return category, msg, False, status_code
        elif status_code in (400, 403, 404):
            category, msg = _classify_by_message(error_str)
            return category, msg, False, status_code

    category, msg = _classify_by_message(error_str)
    can_retry = category in ("engine_overloaded", "rate_limit_reached", "server_error")
    return category, msg, can_retry, status_code


def format_error_for_display(error: Exception, show_technical: bool = False) -> str:
    """格式化错误信息用于显示"""
    category, user_msg, can_retry, status_code = classify_error(error)
    parts = []
    if status_code:
        error_name = ERROR_CODES.get(status_code, "未知错误")
        parts.append(f"[{status_code}] {error_name}")
    parts.append(user_msg)
    if show_technical:
        parts.append(f"\n技术详情: {str(error)[:200]}")
    return " | ".join(parts)


def _get_retry_delay(attempt: int, base_delay: float = 2.0) -> float:
    return base_delay * (1.5 ** attempt)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 2.0,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
    on_max_retries_exceeded: Optional[Callable[[Exception], None]] = None
):
    """重试装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    category, user_msg, can_retry, status_code = classify_error(e)
                    if not can_retry:
                        raise
                    if attempt >= max_retries - 1:
                        if on_max_retries_exceeded:
                            on_max_retries_exceeded(e)
                        raise
                    delay = _get_retry_delay(attempt, base_delay)
                    if on_retry:
                        on_retry(e, attempt + 1, delay)
                    time.sleep(delay)
            if last_error:
                raise last_error
        return wrapper
    return decorator


class KimiAPIError(Exception):
    def __init__(self, message: str, category: str = "unknown",
                 status_code: Optional[int] = None, can_retry: bool = False):
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code
        self.can_retry = can_retry

    def to_user_message(self) -> str:
        return format_error_for_display(self)


class RateLimitError(KimiAPIError):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message=message, category="rate_limit", status_code=429, can_retry=True)
        self.retry_after = retry_after


class AuthError(KimiAPIError):
    def __init__(self, message: str):
        super().__init__(message=message, category="authentication", status_code=401, can_retry=False)


class BadRequestError(KimiAPIError):
    def __init__(self, message: str):
        super().__init__(message=message, category="bad_request", status_code=400, can_retry=False)


class ServerError(KimiAPIError):
    def __init__(self, message: str):
        super().__init__(message=message, category="server_error", status_code=500, can_retry=True)


class PermissionError(KimiAPIError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message=message, category="permission_denied", status_code=status_code, can_retry=False)


def create_api_error(error: Exception) -> KimiAPIError:
    category, user_msg, can_retry, status_code = classify_error(error)
    original_message = str(error)

    if status_code == 429:
        return RateLimitError(original_message)
    elif status_code == 401:
        return AuthError(original_message)
    elif status_code == 400:
        return BadRequestError(original_message)
    elif status_code == 500:
        return ServerError(original_message)
    elif status_code in (403, 404):
        return PermissionError(original_message, status_code)
    else:
        return KimiAPIError(message=original_message, category=category,
                             status_code=status_code, can_retry=can_retry)
