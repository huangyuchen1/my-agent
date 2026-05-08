"""
模型配置文件
支持多种 AI 模型配置，通过模型名称选择对应的配置
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from pathlib import Path


@dataclass
class ModelConfig:
    """模型配置数据类"""
    name: str                           # 模型名称
    api_key: str                        # API 密钥
    base_url: str                       # API 基础地址
    model_id: str                       # 模型 ID
    max_tokens: int = 32768             # 最大 token 数
    thinking_type: str = "disabled"    # 思考类型
    system_prompt: str = ""             # 系统提示词模板
    extra_params: Dict[str, Any] = field(default_factory=dict)  # 其他额外参数


class Config:
    """配置管理器"""
    DEFAULT_CONFIG_FILE = "config.json"

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径，默认使用 config.json
        """
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self._models: Dict[str, ModelConfig] = {}
        self._current_model: Optional[str] = None
        self._load_config()

    def _get_default_config_path(self) -> Path:
        """获取默认配置文件路径"""
        return Path(__file__).parent / self.config_file

    def _get_config_path(self) -> Path:
        """获取配置文件路径"""
        path = Path(self.config_file)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        return path

    def _load_config(self) -> None:
        """加载配置文件"""
        config_path = self._get_config_path()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"\033[31m[错误] 配置文件格式错误: {e}\033[0m")

        # 加载所有模型配置
        models_data = data.get("models", {})
        for model_name, model_data in models_data.items():
            self._models[model_name] = ModelConfig(
                name=model_name,
                api_key=model_data.get("api_key", ""),
                base_url=model_data.get("base_url", ""),
                model_id=model_data.get("model_id", ""),
                max_tokens=model_data.get("max_tokens", 32768),
                thinking_type=model_data.get("thinking_type", "disabled"),
                system_prompt=model_data.get("system_prompt", ""),
                extra_params=model_data.get("extra_params", {}),
            )

        # 设置当前模型
        self._current_model = data.get("current_model")

    def _create_default_config(self, config_path: Path) -> None:
        """创建默认配置文件"""
        default_config = {
            "current_model": "kimi",
            "models": {
                "kimi": {
                    "api_key": os.environ.get("MOONSHOT_API_KEY", "your-api-key"),
                    "base_url": "https://api.moonshot.cn/v1",
                    "model_id": "kimi-k2.5",
                    "max_tokens": 32768,
                    "thinking_type": "disabled",
                    "system_prompt": "You are a coding agent. Use bash to solve tasks. Act, don't explain."
                },
                "deepseek": {
                    "api_key": os.environ.get("DEEPSEEK_API_KEY", "your-api-key"),
                    "base_url": "https://api.deepseek.com/v1",
                    "model_id": "deepseek-chat",
                    "max_tokens": 8192,
                    "thinking_type": "disabled",
                    "system_prompt": "You are a coding agent. Use bash to solve tasks. Act, don't explain."
                },
                "qwen": {
                    "api_key": os.environ.get("DASHSCOPE_API_KEY", "your-api-key"),
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model_id": "qwen-plus",
                    "max_tokens": 8192,
                    "thinking_type": "disabled",
                    "system_prompt": "You are a coding agent. Use bash to solve tasks. Act, don't explain."
                },
                "openai": {
                    "api_key": os.environ.get("OPENAI_API_KEY", "your-api-key"),
                    "base_url": "https://api.openai.com/v1",
                    "model_id": "gpt-4o",
                    "max_tokens": 16384,
                    "thinking_type": "disabled",
                    "system_prompt": "You are a coding agent. Use bash to solve tasks. Act, don't explain."
                },
                "ollama": {
                    "api_key": "ollama",  # ollama 不需要 API key
                    "base_url": "http://localhost:11434/v1",
                    "model_id": "llama3",
                    "max_tokens": 4096,
                    "thinking_type": "disabled",
                    "system_prompt": "You are a coding agent. Use bash to solve tasks. Act, don't explain."
                }
            }
        }

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)

    @property
    def current_model_config(self) -> ModelConfig:
        """获取当前模型配置"""
        if not self._current_model or self._current_model not in self._models:
            # 默认返回第一个模型
            first_model = next(iter(self._models.values()))
            return first_model
        return self._models[self._current_model]

    @property
    def available_models(self) -> list:
        """获取可用的模型列表"""
        return list(self._models.keys())

    def set_model(self, model_name: str) -> bool:
        """
        切换当前模型

        Args:
            model_name: 模型名称

        Returns:
            是否切换成功
        """
        if model_name in self._models:
            self._current_model = model_name
            return True
        return False

    def get_model_config(self, model_name: str) -> Optional[ModelConfig]:
        """获取指定模型的配置"""
        return self._models.get(model_name)

    def save(self) -> None:
        """保存当前配置到文件"""
        config_path = self._get_config_path()
        models_data = {}
        for name, config in self._models.items():
            models_data[name] = {
                "api_key": config.api_key,
                "base_url": config.base_url,
                "model_id": config.model_id,
                "max_tokens": config.max_tokens,
                "thinking_type": config.thinking_type,
                "system_prompt": config.system_prompt,
                "extra_params": config.extra_params,
            }

        data = {
            "current_model": self._current_model,
            "models": models_data
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def reload(self) -> None:
        """重新加载配置"""
        self._models.clear()
        self._load_config()


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例（单例模式）"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def init_config(config_file: Optional[str] = None) -> Config:
    """
    初始化配置

    Args:
        config_file: 配置文件路径

    Returns:
        配置实例
    """
    global _config
    _config = Config(config_file)
    return _config


def list_available_models() -> list:
    """列出所有可用的模型"""
    return get_config().available_models


def switch_model(model_name: str) -> bool:
    """切换当前模型"""
    return get_config().set_model(model_name)


# 便捷访问函数
def get_current_model_config() -> ModelConfig:
    """获取当前模型配置"""
    return get_config().current_model_config
