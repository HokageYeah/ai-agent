"""
资源路径解析工具。

该模块用于将项目内的相对资源路径稳定解析为绝对路径，
避免在不同启动目录下读取资源文件失败。
"""

from pathlib import Path


def get_project_root() -> Path:
    """获取项目根目录路径。"""
    # app/utils/resource_path.py -> app/utils -> app -> project_root
    return Path(__file__).resolve().parents[2]


def get_resource_path(relative_path: str) -> str:
    """
    将资源相对路径解析为项目根目录下的绝对路径。

    Args:
        relative_path: 相对路径（如 ``prompt/plan``）或绝对路径。

    Returns:
        str: 解析后的绝对路径字符串。
    """
    path = Path(relative_path)
    if path.is_absolute():
        return str(path)
    return str((get_project_root() / path).resolve())
