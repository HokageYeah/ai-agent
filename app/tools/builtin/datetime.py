"""
日期时间工具模块

本模块实现了 DateTimeTool 类，提供日期时间相关功能。

功能特点：
1. 获取当前日期时间
2. 获取当前日期
3. 获取当前时间
4. 日期时间格式化（支持自定义格式）
5. 日期时间解析
6. 日期时间加减计算
7. 获取时间戳
8. 获取时区信息
9. 计算两个日期之间的差异
10. 获取星期几、月份名称等

使用示例：
    tool = DateTimeTool()
    
    # 获取当前日期时间
    result = await tool.execute({"operation": "now"})
    
    # 获取当前日期
    result = await tool.execute({"operation": "today"})
    
    # 格式化日期时间
    result = await tool.execute({
        "operation": "format",
        "datetime": "2024-01-15 10:30:00",
        "format": "%Y年%m月%d日 %H:%M:%S"
    })
    
    # 日期加减
    result = await tool.execute({
        "operation": "add",
        "datetime": "2024-01-15",
        "days": 7
    })
    
    # 计算日期差
    result = await tool.execute({
        "operation": "diff",
        "date1": "2024-01-01",
        "date2": "2024-01-15"
    })
"""

import re
from datetime import datetime, date, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from app.tools.base import Tool, ToolSchema
from loguru import logger


class DateTimeTool(Tool):
    """
    日期时间工具
    
    继承自 Tool 抽象基类，提供日期时间相关的各种功能。
    
    支持的操作：
    - now: 获取当前日期时间
    - today: 获取当前日期
    - current_time: 获取当前时间
    - timestamp: 获取当前时间戳
    - format: 格式化日期时间
    - parse: 解析日期时间字符串
    - add: 日期时间加减
    - subtract: 日期时间相减
    - diff: 计算两个日期的差
    - weekday: 获取星期几
    - month_name: 获取月份名称
    - timezone_info: 获取时区信息
    - is_valid: 验证日期时间字符串
    
    属性：
        name: 工具名称，固定为 "datetime"
        description: 工具描述
    """
    
    # 星期名称映射
    _WEEKDAY_NAMES = {
        'en': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
        'zh': ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    }
    
    # 月份名称映射
    _MONTH_NAMES = {
        'en': ['January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December'],
        'zh': ['一月', '二月', '三月', '四月', '五月', '六月',
               '七月', '八月', '九月', '十月', '十一月', '十二月']
    }
    
    # 常用日期时间格式
    _COMMON_FORMATS = {
        'iso': '%Y-%m-%dT%H:%M:%S',
        'iso_milli': '%Y-%m-%dT%H:%M:%S.%f',
        'date': '%Y-%m-%d',
        'time': '%H:%M:%S',
        'datetime': '%Y-%m-%d %H:%M:%S',
        'chinese': '%Y年%m月%d日 %H:%M:%S',
        'chinese_date': '%Y年%m月%d日',
        'slash': '%Y/%m/%d',
        'dot': '%Y.%m.%d',
        'us': '%m/%d/%Y',
        'eu': '%d/%m/%Y',
        'friendly': '%Y年%m月%d日 %A',
        'rfc822': '%a, %d %b %Y %H:%M:%S %z',
    }
    
    def __init__(self, default_timezone: str = "UTC"):
        """
        初始化 DateTimeTool
        
        Args:
            default_timezone: 默认时区
        """
        self._name = "datetime"
        self._description = "获取和操作日期时间。支持获取当前时间、格式化、解析、日期加减、计算差值等功能。"
        self._default_timezone = default_timezone
        logger.info(f"[DateTimeTool] 日期时间工具初始化完成，默认时区: {default_timezone}")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "datetime"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义日期时间工具的参数规范：
        - operation: 操作类型（必需）
        - format: 日期时间格式（可选）
        - datetime: 日期时间字符串（可选）
        - days/hours/minutes/seconds: 时间增量（可选）
        - date1/date2: 用于计算差值的日期（可选）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "now", "today", "current_time", "timestamp",
                            "format", "parse", "add", "subtract", "diff",
                            "weekday", "month_name", "timezone_info", "is_valid"
                        ],
                        "description": "操作类型"
                    },
                    "datetime": {
                        "type": "string",
                        "description": "日期时间字符串"
                    },
                    "format": {
                        "type": "string",
                        "description": "日期时间格式，支持常用格式名称或 strftime 格式字符串"
                    },
                    "days": {
                        "type": "integer",
                        "description": "天数增量（可正可负）"
                    },
                    "hours": {
                        "type": "integer",
                        "description": "小时增量（可正可负）"
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "分钟增量（可正可负）"
                    },
                    "seconds": {
                        "type": "integer",
                        "description": "秒数增量（可正可负）"
                    },
                    "date1": {
                        "type": "string",
                        "description": "第一个日期（用于计算差值）"
                    },
                    "date2": {
                        "type": "string",
                        "description": "第二个日期（用于计算差值）"
                    },
                    "timezone": {
                        "type": "string",
                        "description": "时区，默认为 UTC",
                        "default": "UTC"
                    },
                    "lang": {
                        "type": "string",
                        "description": "语言，'zh' 或 'en'，默认为 'zh'",
                        "default": "zh"
                    }
                },
                "required": ["operation"],
                "additionalProperties": False
            }
        )
    
    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """
        智能解析日期时间字符串
        
        尝试多种常见格式进行解析。
        
        Args:
            datetime_str: 日期时间字符串
            
        Returns:
            datetime: 解析后的 datetime 对象，失败返回 None
        """
        if not datetime_str:
            return None
        
        # 尝试常见格式
        formats_to_try = [
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d',
            '%Y.%m.%d %H:%M:%S',
            '%Y.%m.%d',
            '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y',
        ]
        
        for fmt in formats_to_try:
            try:
                return datetime.strptime(datetime_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """
        智能解析日期字符串
        
        Args:
            date_str: 日期字符串
            
        Returns:
            date: 解析后的 date 对象，失败返回 None
        """
        dt = self._parse_datetime(date_str)
        if dt:
            return dt.date()
        return None
    
    def _get_timezone(self, tz_name: str) -> timezone:
        """
        获取时区对象
        
        Args:
            tz_name: 时区名称
            
        Returns:
            timezone: 时区对象
        """
        tz_name = tz_name or self._default_timezone
        
        # 常见时区
        tz_map = {
            'UTC': timezone.utc,
            'CST': timezone(timedelta(hours=8)),  # 中国标准时间
            'EST': timezone(timedelta(hours=-5)),
            'EDT': timezone(timedelta(hours=-4)),
            'PST': timezone(timedelta(hours=-8)),
            'PDT': timezone(timedelta(hours=-7)),
            'GMT': timezone.utc,
            'CET': timezone(timedelta(hours=1)),
            'CEST': timezone(timedelta(hours=2)),
        }
        
        if tz_name in tz_map:
            return tz_map[tz_name]
        
        # 尝试使用 pytz 或 zoneinfo（如果可用）
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except ImportError:
            pass
        
        # 默认返回 UTC
        return timezone.utc
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行日期时间操作
        
        根据指定的 operation 执行相应的日期时间操作。
        
        Args:
            params: 参数字典，必须包含 "operation" 键
            
        Returns:
            Dict[str, Any]: 操作结果，包含：
                - success: 是否成功
                - result: 操作结果
                - operation: 执行的操作
                - error: 错误信息（失败时）
        """
        # ========== 参数提取阶段 ==========
        operation = params.get("operation", "")
        lang = params.get("lang", "zh")
        timezone_name = params.get("timezone", self._default_timezone)
        
        # 参数验证
        if not operation:
            logger.warning("[DateTimeTool] 操作类型为空")
            return {
                "success": False,
                "error": "操作类型不能为空"
            }
        
        logger.info(f"[DateTimeTool] 执行操作: {operation}")
        
        # 获取时区
        tz = self._get_timezone(timezone_name)
        
        try:
            # ========== 根据操作类型执行 ==========
            
            # ----- now: 获取当前日期时间 -----
            if operation == "now":
                now = datetime.now(tz)
                return {
                    "success": True,
                    "result": now.isoformat(),
                    "datetime": now,
                    "operation": "now"
                }
            
            # ----- today: 获取当前日期 -----
            elif operation == "today":
                today = date.today()
                return {
                    "success": True,
                    "result": today.isoformat(),
                    "date": today,
                    "operation": "today"
                }
            
            # ----- current_time: 获取当前时间 -----
            elif operation == "current_time":
                now = datetime.now(tz).time()
                return {
                    "success": True,
                    "result": now.isoformat(),
                    "time": now,
                    "operation": "current_time"
                }
            
            # ----- timestamp: 获取时间戳 -----
            elif operation == "timestamp":
                import time
                now = datetime.now(tz)
                return {
                    "success": True,
                    "result": now.timestamp(),
                    "timestamp": now.timestamp(),
                    "operation": "timestamp"
                }
            
            # ----- format: 格式化日期时间 -----
            elif operation == "format":
                datetime_str = params.get("datetime", "")
                format_str = params.get("format", "%Y-%m-%d %H:%M:%S")
                
                if not datetime_str:
                    return {
                        "success": False,
                        "error": "请提供要格式化的日期时间",
                        "operation": "format"
                    }
                
                # 检查是否是常用格式名称
                if format_str in self._COMMON_FORMATS:
                    format_str = self._COMMON_FORMATS[format_str]
                
                # 解析日期时间
                dt = self._parse_datetime(datetime_str)
                if not dt:
                    return {
                        "success": False,
                        "error": f"无法解析日期时间: {datetime_str}",
                        "operation": "format"
                    }
                
                # 格式化
                formatted = dt.strftime(format_str)
                
                return {
                    "success": True,
                    "result": formatted,
                    "formatted": formatted,
                    "operation": "format"
                }
            
            # ----- parse: 解析日期时间 -----
            elif operation == "parse":
                datetime_str = params.get("datetime", "")
                
                if not datetime_str:
                    return {
                        "success": False,
                        "error": "请提供要解析的日期时间字符串",
                        "operation": "parse"
                    }
                
                dt = self._parse_datetime(datetime_str)
                if not dt:
                    return {
                        "success": False,
                        "error": f"无法解析日期时间: {datetime_str}",
                        "operation": "parse"
                    }
                
                return {
                    "success": True,
                    "result": dt.isoformat(),
                    "datetime": dt.isoformat(),
                    "year": dt.year,
                    "month": dt.month,
                    "day": dt.day,
                    "hour": dt.hour,
                    "minute": dt.minute,
                    "second": dt.second,
                    "weekday": dt.weekday() + 1,  # 1-7，1 为星期一
                    "operation": "parse"
                }
            
            # ----- add: 日期时间加减 -----
            elif operation == "add":
                datetime_str = params.get("datetime", "")
                days = params.get("days", 0)
                hours = params.get("hours", 0)
                minutes = params.get("minutes", 0)
                seconds = params.get("seconds", 0)
                
                if not datetime_str:
                    # 如果没有提供 datetime，使用当前时间
                    dt = datetime.now(tz)
                else:
                    dt = self._parse_datetime(datetime_str)
                    if not dt:
                        return {
                            "success": False,
                            "error": f"无法解析日期时间: {datetime_str}",
                            "operation": "add"
                        }
                
                # 计算时间增量
                delta = timedelta(
                    days=days,
                    hours=hours,
                    minutes=minutes,
                    seconds=seconds
                )
                
                new_dt = dt + delta
                
                return {
                    "success": True,
                    "result": new_dt.isoformat(),
                    "datetime": new_dt.isoformat(),
                    "operation": "add"
                }
            
            # ----- subtract: 日期时间相减 -----
            elif operation == "subtract":
                datetime_str = params.get("datetime", "")
                days = params.get("days", 0)
                hours = params.get("hours", 0)
                minutes = params.get("minutes", 0)
                seconds = params.get("seconds", 0)
                
                if not datetime_str:
                    dt = datetime.now(tz)
                else:
                    dt = self._parse_datetime(datetime_str)
                    if not dt:
                        return {
                            "success": False,
                            "error": f"无法解析日期时间: {datetime_str}",
                            "operation": "subtract"
                        }
                
                delta = timedelta(
                    days=-days,
                    hours=-hours,
                    minutes=-minutes,
                    seconds=-seconds
                )
                
                new_dt = dt + delta
                
                return {
                    "success": True,
                    "result": new_dt.isoformat(),
                    "datetime": new_dt.isoformat(),
                    "operation": "subtract"
                }
            
            # ----- diff: 计算两个日期的差 -----
            elif operation == "diff":
                date1_str = params.get("date1", "")
                date2_str = params.get("date2", "")
                
                if not date1_str or not date2_str:
                    return {
                        "success": False,
                        "error": "请提供两个日期进行比较",
                        "operation": "diff"
                    }
                
                d1 = self._parse_date(date1_str)
                d2 = self._parse_date(date2_str)
                
                if not d1 or not d2:
                    return {
                        "success": False,
                        "error": f"无法解析日期: {date1_str} 或 {date2_str}",
                        "operation": "diff"
                    }
                
                delta = d2 - d1
                
                return {
                    "success": True,
                    "result": delta.days,
                    "days": delta.days,
                    "seconds": delta.total_seconds(),
                    "hours": delta.total_seconds() / 3600,
                    "operation": "diff"
                }
            
            # ----- weekday: 获取星期几 -----
            elif operation == "weekday":
                datetime_str = params.get("datetime", "")
                
                if datetime_str:
                    dt = self._parse_datetime(datetime_str)
                    if not dt:
                        return {
                            "success": False,
                            "error": f"无法解析日期时间: {datetime_str}",
                            "operation": "weekday"
                        }
                    weekday_num = dt.weekday()  # 0-6，0 为星期一
                else:
                    weekday_num = date.today().weekday()
                
                weekday_names = self._WEEKDAY_NAMES.get(lang, self._WEEKDAY_NAMES['en'])
                
                return {
                    "success": True,
                    "result": weekday_names[weekday_num],
                    "weekday_num": weekday_num + 1,  # 1-7
                    "weekday_name": weekday_names[weekday_num],
                    "operation": "weekday"
                }
            
            # ----- month_name: 获取月份名称 -----
            elif operation == "month_name":
                month = params.get("month")
                
                if month is None:
                    month = date.today().month
                else:
                    month = int(month)
                    if month < 1 or month > 12:
                        return {
                            "success": False,
                            "error": "月份必须在 1-12 之间",
                            "operation": "month_name"
                        }
                
                month_names = self._MONTH_NAMES.get(lang, self._MONTH_NAMES['en'])
                
                return {
                    "success": True,
                    "result": month_names[month - 1],
                    "month_num": month,
                    "month_name": month_names[month - 1],
                    "operation": "month_name"
                }
            
            # ----- timezone_info: 获取时区信息 -----
            elif operation == "timezone_info":
                tz = self._get_timezone(timezone_name)
                now = datetime.now(tz)
                
                # 计算与 UTC 的偏移
                utc_offset = now.utcoffset()
                if utc_offset:
                    offset_hours = utc_offset.total_seconds() / 3600
                    offset_str = f"+{int(offset_hours):02d}:00" if offset_hours >= 0 else f"{int(offset_hours):03d}:00"
                else:
                    offset_str = "Z"
                
                return {
                    "success": True,
                    "result": offset_str,
                    "timezone": timezone_name,
                    "utc_offset": offset_str,
                    "current_time": now.isoformat(),
                    "operation": "timezone_info"
                }
            
            # ----- is_valid: 验证日期时间字符串 -----
            elif operation == "is_valid":
                datetime_str = params.get("datetime", "")
                
                if not datetime_str:
                    return {
                        "success": False,
                        "error": "请提供要验证的日期时间字符串",
                        "operation": "is_valid"
                    }
                
                dt = self._parse_datetime(datetime_str)
                
                return {
                    "success": True,
                    "result": dt is not None,
                    "is_valid": dt is not None,
                    "operation": "is_valid"
                }
            
            else:
                return {
                    "success": False,
                    "error": f"不支持的操作类型: {operation}",
                    "operation": operation
                }
                
        except Exception as e:
            logger.exception(f"[DateTimeTool] 操作发生错误: {str(e)}")
            return {
                "success": False,
                "error": f"操作失败: {str(e)}",
                "operation": operation
            }


# ============================================================
# 便捷函数：快速获取日期时间
# ============================================================

async def get_now(timezone: str = "UTC") -> Dict[str, Any]:
    """
    便捷函数：获取当前日期时间
    
    Args:
        timezone: 时区
        
    Returns:
        Dict[str, Any]: 当前日期时间
    """
    tool = DateTimeTool()
    return await tool.execute({"operation": "now", "timezone": timezone})


async def get_today() -> Dict[str, Any]:
    """
    便捷函数：获取当前日期
    
    Returns:
        Dict[str, Any]: 当前日期
    """
    tool = DateTimeTool()
    return await tool.execute({"operation": "today"})


async def format_datetime(datetime_str: str, 
                          fmt: str = "%Y-%m-%d %H:%M:%S") -> Dict[str, Any]:
    """
    便捷函数：格式化日期时间
    
    Args:
        datetime_str: 日期时间字符串
        fmt: 格式
        
    Returns:
        Dict[str, Any]: 格式化结果
    """
    tool = DateTimeTool()
    return await tool.execute({
        "operation": "format",
        "datetime": datetime_str,
        "format": fmt
    })


# ============================================================
# 日期时间结果格式化工具
# ============================================================

def format_datetime_result(result: Dict[str, Any]) -> str:
    """
    格式化日期时间结果为可读文本
    
    Args:
        result: 操作结果字典
        
    Returns:
        str: 格式化后的结果文本
    """
    if not result.get("success"):
        return f"❌ 操作失败: {result.get('error', '未知错误')}"
    
    operation = result.get("operation", "")
    lines = []
    lines.append(f"✅ 操作成功 ({operation})")
    lines.append(f"结果: {result.get('result', 'N/A')}")
    
    return "\n".join(lines)


# ============================================================
# 支持的日期时间格式示例
# ============================================================

FORMAT_EXAMPLES = """
支持的日期时间格式：

常用格式名称:
  iso         => 2024-01-15T10:30:00
  iso_milli   => 2024-01-15T10:30:00.123456
  date        => 2024-01-15
  time        => 10:30:00
  datetime    => 2024-01-15 10:30:00
  chinese     => 2024年01月15日 10:30:00
  slash       => 2024/01/15
  dot         => 2024.01.15
  us          => 01/15/2024
  eu          => 15/01/2024

strftime 格式:
  %Y          => 2024 (年份，4位数)
  %y          => 24 (年份，2位数)
  %m          => 01 (月份，01-12)
  %d          => 15 (日期，01-31)
  %H          => 10 (小时，00-23)
  %M          => 30 (分钟，00-59)
  %S          => 00 (秒数，00-59)
  %A          => Monday (星期几，全名)
  %a          => Mon (星期几，简写)
  %B          => January (月份名称，全名)
  %b          => Jan (月份名称，简写)
  %f          => 123456 (微秒)
  %z          => +0800 (时区偏移)
  %j          => 015 (一年中的第几天)
  %U          => 02 (一年中的第几周，星期日为首)
  %W          => 02 (一年中的第几周，星期一为首)

示例:
  %Y年%m月%d日 %H:%M:%S  => 2024年01月15日 10:30:00
  %Y/%m/%d %A           => 2024/01/15 Monday
  %B %d, %Y             => January 15, 2024
"""
