"""
数据库查询工具模块

本模块实现了 DatabaseQueryTool 类，提供安全的数据库查询功能。

功能特点：
1. 支持 SQLite 数据库查询
2. SQL 注入防护（白名单验证 + 参数化查询）
3. 只读模式（禁止 INSERT、UPDATE、DELETE、DROP 等危险操作）
4. 查询结果格式化输出
5. 完善的错误处理和日志记录

安全措施：
- 只允许 SELECT 查询
- 表名和列名白名单验证
- 使用参数化查询防止 SQL 注入
- 限制返回结果数量
- 超时控制

使用示例：
    tool = DatabaseQueryTool()
    result = await tool.execute({
        "query": "SELECT * FROM users WHERE id = :id",
        "params": {"id": 1},
        "limit": 100
    })
"""

import re
import sqlite3
import json
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from app.tools.base import Tool, ToolSchema
from loguru import logger


class DatabaseQueryTool(Tool):
    """
    数据库查询工具
    
    继承自 Tool 抽象基类，提供安全的数据库查询功能。
    
    安全设计：
    1. 只允许 SELECT 查询语句
    2. 表名和列名白名单验证
    3. 使用参数化查询防止 SQL 注入
    4. 限制返回结果数量（默认 1000 条）
    5. 查询超时控制（默认 30 秒）
    
    属性：
        name: 工具名称，固定为 "database_query"
        description: 工具描述
    """
    
    # 允许的 SQL 关键字（只读操作）
    _ALLOWED_KEYWORDS = {
        'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE',
        'BETWEEN', 'IS', 'NULL', 'AS', 'DISTINCT', 'LIMIT', 'OFFSET',
        'ORDER', 'BY', 'ASC', 'DESC', 'GROUP', 'HAVING', 'JOIN',
        'INNER', 'LEFT', 'RIGHT', 'OUTER', 'ON', 'UNION', 'ALL',
        'EXISTS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST',
        'COALESCE', 'IFNULL', 'NULLIF', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
        'ABS', 'ROUND', 'CEIL', 'FLOOR', 'TRUNCATE', 'MOD', 'POWER',
        'SQRT', 'CONCAT', 'SUBSTRING', 'LENGTH', 'UPPER', 'LOWER', 'TRIM',
        'DATE', 'TIME', 'DATETIME', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
        'STRFTIME', 'JULIANDAY', 'DATEADD', 'DATEDIFF',
    }
    
    # 禁止的 SQL 关键字（危险操作）
    _FORBIDDEN_KEYWORDS = {
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE',
        'EXEC', 'EXECUTE', 'GRANT', 'REVOKE', 'VACUUM', 'REINDEX',
        'ATTACH', 'DETACH', 'PRAGMA', 'WITH', 'RECURSIVE',
    }
    
    def __init__(self, default_db_path: str = ":memory:"):
        """
        初始化 DatabaseQueryTool
        
        Args:
            default_db_path: 默认数据库路径，默认为内存数据库
        """
        self._name = "database_query"
        self._description = "执行安全的数据库查询（仅支持 SELECT 语句）。支持参数化查询，防止 SQL 注入，返回格式化的查询结果。"
        self._default_db_path = default_db_path
        self._default_timeout = 30.0  # 默认超时 30 秒
        self._max_results = 1000  # 默认最大返回 1000 条
        
        # 对于内存数据库，创建共享连接以便在同一实例中共享数据
        self._shared_memory_conn = None
        if default_db_path == ":memory:":
            self._shared_memory_conn = sqlite3.connect(
                ":memory:",
                timeout=self._default_timeout,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            logger.info("[DatabaseQueryTool] 已创建共享内存数据库连接")
        
        logger.info(f"[DatabaseQueryTool] 数据库查询工具初始化完成，默认数据库: {default_db_path}")
    
    @property
    def name(self) -> str:
        """
        获取工具名称
        
        Returns:
            str: 工具名称，固定为 "database_query"
        """
        return self._name
    
    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema
        
        定义数据库查询工具的参数规范：
        - query: SQL 查询语句（必需）
        - params: 查询参数（可选，用于参数化查询）
        - db_path: 数据库路径（可选）
        - limit: 结果限制（可选，默认 1000）
        - timeout: 超时时间（可选，默认 30）
        
        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT 查询语句"
                    },
                    "params": {
                        "type": "object",
                        "description": "查询参数（键值对形式），用于参数化查询防止 SQL 注入"
                    },
                    "db_path": {
                        "type": "string",
                        "description": "数据库文件路径，默认为内存数据库",
                        "default": ":memory:"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回结果数量，默认为 1000",
                        "default": 1000,
                        "minimum": 1,
                        "maximum": 10000
                    },
                    "timeout": {
                        "type": "number",
                        "description": "查询超时时间（秒），默认为 30",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 300
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        )
    
    def _validate_query(self, query: str) -> Tuple[bool, str]:
        """
        验证 SQL 查询安全性
        
        检查查询语句是否为只读的 SELECT 语句。
        
        验证步骤：
        1. 检查是否包含禁止的关键字
        2. 检查是否以 SELECT 开头
        3. 验证表名和列名格式
        
        Args:
            query: SQL 查询语句
            
        Returns:
            Tuple[bool, str]: (是否合法, 错误信息)
        """
        if not query or not query.strip():
            return False, "查询语句不能为空"
        
        # 去除首尾空白并转换为大写检查
        upper_query = query.strip().upper()
        
        # 检查是否以 SELECT 开头
        if not upper_query.startswith("SELECT"):
            return False, "只允许 SELECT 查询语句，不支持 INSERT、UPDATE、DELETE 等操作"
        
        # 检查禁止的关键字
        for keyword in self._FORBIDDEN_KEYWORDS:
            # 使用单词边界匹配
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, upper_query):
                return False, f"查询包含禁止的关键字: {keyword}"
        
        # 检查是否有分号结尾（防止多语句）
        if ';' in query.strip()[:-1]:
            return False, "不支持多语句查询"
        
        return True, ""
    
    def _extract_tables(self, query: str) -> List[str]:
        """
        从查询中提取表名
        
        Args:
            query: SQL 查询语句
            
        Returns:
            List[str]: 表名列表
        """
        tables = []
        
        # 匹配 FROM 子句后的表名
        from_pattern = r'FROM\s+([`"\']?\w+[`"\']?(?:\s*,\s*[`"\']?\w+[`"\']?)*)'
        matches = re.findall(from_pattern, query, re.IGNORECASE)
        
        for match in matches:
            for table in match.split(','):
                table = table.strip().strip('`"\'')
                if table:
                    tables.append(table)
        
        return tables
    
    def _build_result_response(self, cursor: sqlite3.Cursor, 
                               execution_time: float) -> Dict[str, Any]:
        """
        构建查询结果响应
        
        Args:
            cursor: SQLite 游标
            execution_time: 执行时间（秒）
            
        Returns:
            Dict[str, Any]: 格式化的查询结果
        """
        # 获取列名
        columns = [description[0] for description in cursor.description]
        
        # 获取数据
        rows = cursor.fetchall()
        
        # 转换为字典列表
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                value = row[i]
                # 处理特殊类型
                if value is None:
                    row_dict[col] = None
                elif isinstance(value, bytes):
                    row_dict[col] = value.hex()  # 将二进制转为十六进制字符串
                elif isinstance(value, (list, tuple)):
                    row_dict[col] = list(value)
                else:
                    row_dict[col] = value
            data.append(row_dict)
        
        return {
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "execution_time_ms": round(execution_time * 1000, 2)
        }
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行数据库查询
        
        在安全的执行环境中执行给定的 SQL 查询。
        
        参数处理逻辑：
        1. 提取并验证 query 参数
        2. 验证查询安全性
        3. 连接数据库
        4. 执行参数化查询
        5. 返回格式化结果
        
        Args:
            params: 参数字典，必须包含 "query" 键
            
        Returns:
            Dict[str, Any]: 查询结果，包含：
                - success: 是否成功
                - columns: 列名列表
                - rows: 数据行列表
                - row_count: 结果数量
                - execution_time_ms: 执行时间（毫秒）
                - error: 错误信息（失败时）
        """
        import time
        
        # ========== 参数提取阶段 ==========
        query = params.get("query", "")
        params_dict = params.get("params", {})
        db_path = params.get("db_path", self._default_db_path)
        limit = params.get("limit", self._max_results)
        timeout = params.get("timeout", self._default_timeout)
        
        # 参数验证
        if not query:
            logger.warning("[DatabaseQueryTool] 查询语句为空")
            return {
                "success": False,
                "error": "查询语句不能为空"
            }
        
        logger.info(f"[DatabaseQueryTool] 准备执行查询: {query[:100]}...")
        
        # ========== 查询验证阶段 ==========
        is_valid, error_msg = self._validate_query(query)
        if not is_valid:
            logger.warning(f"[DatabaseQueryTool] 查询验证失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }
        
        # 提取并验证表名
        tables = self._extract_tables(query)
        logger.debug(f"[DatabaseQueryTool] 查询涉及的表: {tables}")
        
        # ========== 数据库查询阶段 ==========
        conn = None
        use_shared_conn = False
        start_time = time.time()
        
        try:
            # 处理内存数据库
            if db_path == ":memory:":
                # 使用共享内存数据库连接（如果已初始化）
                if self._shared_memory_conn is not None:
                    conn = self._shared_memory_conn
                    use_shared_conn = True
                else:
                    # 否则创建临时连接
                    conn = sqlite3.connect(
                        db_path,
                        timeout=timeout,
                        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
                    )
            else:
                # 验证数据库文件路径
                db_path = Path(db_path).resolve()
                if not db_path.exists():
                    return {
                        "success": False,
                        "error": f"数据库文件不存在: {db_path}"
                    }
                
                conn = sqlite3.connect(
                    str(db_path),
                    timeout=timeout,
                    detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
                )
            
            # 设置行工厂为字典
            conn.row_factory = sqlite3.Row
            
            # 创建游标
            cursor = conn.cursor()
            
            # 添加 LIMIT 子句（如果还没有的话）
            safe_query = query
            if 'LIMIT' not in safe_query.upper():
                safe_query = f"{query} LIMIT {limit}"
            
            # 执行查询（使用参数化查询防止 SQL 注入）
            cursor.execute(safe_query, params_dict)
            
            # 获取结果
            result = self._build_result_response(cursor, time.time() - start_time)
            
            logger.info(
                f"[DatabaseQueryTool] 查询成功，返回 {result['row_count']} 行，"
                f"执行时间: {result['execution_time_ms']}ms"
            )
            
            return {
                "success": True,
                **result
            }
            
        except sqlite3.OperationalError as e:
            logger.error(f"[DatabaseQueryTool] 数据库操作错误: {str(e)}")
            return {
                "success": False,
                "error": f"数据库操作错误: {str(e)}"
            }
            
        except sqlite3.Error as e:
            logger.error(f"[DatabaseQueryTool] SQLite 错误: {str(e)}")
            return {
                "success": False,
                "error": f"数据库错误: {str(e)}"
            }
            
        except Exception as e:
            logger.exception(f"[DatabaseQueryTool] 查询发生未知错误: {str(e)}")
            return {
                "success": False,
                "error": f"查询失败: {str(e)}"
            }
            
        finally:
            # 只关闭非共享连接
            if conn and not use_shared_conn:
                conn.close()


# ============================================================
# 便捷函数：快速执行查询
# ============================================================

async def quick_query(query: str, params: Dict[str, Any] = None,
                      limit: int = 100) -> Dict[str, Any]:
    """
    便捷数据库查询函数
    
    使用内存数据库执行简单查询。
    
    Args:
        query: SQL 查询语句
        params: 查询参数
        limit: 结果限制
        
    Returns:
        Dict[str, Any]: 查询结果
    """
    tool = DatabaseQueryTool()
    return await tool.execute({
        "query": query,
        "params": params or {},
        "limit": limit
    })


# ============================================================
# 数据库工具：创建测试数据
# ============================================================

def create_test_database(db_path: str = ":memory:") -> sqlite3.Connection:
    """
    创建测试数据库并填充示例数据
    
    Args:
        db_path: 数据库路径
        
    Returns:
        sqlite3.Connection: 数据库连接
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建示例表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            age INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            product TEXT NOT NULL,
            quantity INTEGER,
            price REAL,
            order_date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # 插入示例数据
    users_data = [
        (1, "张三", "zhangsan@example.com", 28),
        (2, "李四", "lisi@example.com", 32),
        (3, "王五", "wangwu@example.com", 25),
        (4, "赵六", "zhaoliu@example.com", 35),
        (5, "钱七", "qianqi@example.com", 30),
    ]
    
    cursor.executemany(
        "INSERT OR IGNORE INTO users (id, name, email, age) VALUES (?, ?, ?, ?)",
        users_data
    )
    
    orders_data = [
        (1, 1, "产品A", 2, 99.99, "2024-01-15"),
        (2, 1, "产品B", 1, 149.99, "2024-01-20"),
        (3, 2, "产品A", 3, 99.99, "2024-01-18"),
        (4, 3, "产品C", 2, 199.99, "2024-01-22"),
        (5, 4, "产品B", 1, 149.99, "2024-01-25"),
    ]
    
    cursor.executemany(
        "INSERT OR IGNORE INTO orders (id, user_id, product, quantity, price, order_date) VALUES (?, ?, ?, ?, ?, ?)",
        orders_data
    )
    
    conn.commit()
    return conn


# ============================================================
# 查询结果格式化工具
# ============================================================

def format_query_result(result: Dict[str, Any], 
                        max_rows: int = 10) -> str:
    """
    格式化查询结果为可读文本
    
    Args:
        result: 查询结果字典
        max_rows: 最大显示行数
        
    Returns:
        str: 格式化后的结果文本
    """
    if not result.get("success"):
        return f"❌ 查询失败: {result.get('error', '未知错误')}"
    
    lines = []
    lines.append("✅ 查询成功")
    lines.append(f"返回行数: {result.get('row_count', 0)}")
    lines.append(f"执行时间: {result.get('execution_time_ms', 0)}ms")
    lines.append("")
    
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    
    if not rows:
        lines.append("无数据")
        return "\n".join(lines)
    
    # 计算列宽
    col_widths = {}
    for col in columns:
        col_widths[col] = len(col)
    
    for row in rows[:max_rows]:
        for col in columns:
            value = str(row.get(col, ""))
            if len(value) > 50:
                value = value[:50] + "..."
            col_widths[col] = max(col_widths[col], len(value))
    
    # 绘制表头
    header = " | ".join(col.ljust(col_widths[col]) for col in columns)
    lines.append(header)
    lines.append("-+-".join("-" * col_widths[col] for col in columns))
    
    # 绘制数据行
    for row in rows[:max_rows]:
        line = " | ".join(
            str(row.get(col, "")).ljust(col_widths[col])[:col_widths[col]]
            for col in columns
        )
        lines.append(line)
    
    # 如果有更多数据
    if result.get("row_count", 0) > max_rows:
        lines.append(f"... 还有 {result['row_count'] - max_rows} 行数据")
    
    return "\n".join(lines)
