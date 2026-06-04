"""
日志配置工具。
统一全项目日志格式，方便追踪多Agent调度流程中的每一步。
"""

from loguru import logger
import sys


def setup_logger(log_file: str = "logs/agent.log", level: str = "INFO"):
    """
    初始化日志。
    输出到：控制台（带颜色）+ 文件（持久化）。
    """
    logger.remove()  # 清除默认配置

    # 控制台输出（带颜色 & 自定义格式）
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{message}</cyan>"
        ),
        enqueue=True,
    )

    # 文件输出（持久化，按大小滚动）
    logger.add(
        log_file,
        rotation="10 MB",
        retention="30 days",
        level=level,
        enqueue=True,
    )

    return logger
