"""
订单系统测试数据初始化模块
================================

本模块负责在 SQLite 内存数据库中创建订单管理系统所需的表结构，
并插入完整的测试数据，供 Agent 进行真实业务场景的数据查询测试。

数据库表设计：
1. customers    - 客户信息表
2. products     - 商品信息表
3. orders       - 订单主表（订单号从 1001 开始）
4. order_items  - 订单明细表
5. refunds      - 退款申请表

测试数据覆盖场景：
- 订单状态：待付款、已付款、已发货、已完成、已取消
- 退款状态：待审核、已通过、已驳回、已退款
- 多商品订单、单商品订单
- 不同客户的订单
- 包含退款订单

作者: AI Agent Team
创建时间: 2026-02-24
"""

import sqlite3
from loguru import logger
from colorama import Fore, Style


# =============================================================================
# 建表 DDL
# =============================================================================

CREATE_CUSTOMERS_TABLE = """
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    phone       TEXT    NOT NULL,
    email       TEXT,
    address     TEXT,
    level       TEXT    DEFAULT 'normal',
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
)
"""

CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    price       REAL    NOT NULL,
    cost_price  REAL,
    stock       INTEGER DEFAULT 0,
    unit        TEXT    DEFAULT '件',
    description TEXT
)
"""

CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY,
    customer_id      INTEGER NOT NULL,
    total_amount     REAL    NOT NULL,
    paid_amount      REAL    DEFAULT 0,
    discount_amount  REAL    DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT 'pending',
    payment_status   TEXT    NOT NULL DEFAULT 'unpaid',
    payment_method   TEXT,
    shipping_address TEXT    NOT NULL,
    tracking_number  TEXT,
    remark           TEXT,
    created_at       TEXT    DEFAULT (datetime('now', 'localtime')),
    shipped_at       TEXT,
    delivered_at     TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
)
"""

CREATE_ORDER_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL,
    product_id   INTEGER NOT NULL,
    product_name TEXT    NOT NULL,
    quantity     INTEGER NOT NULL,
    unit_price   REAL    NOT NULL,
    total_price  REAL    NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
)
"""

CREATE_REFUNDS_TABLE = """
CREATE TABLE IF NOT EXISTS refunds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL,
    amount       REAL    NOT NULL,
    reason       TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',
    refund_type  TEXT    DEFAULT 'refund_only',
    apply_at     TEXT    DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT,
    remark       TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
)
"""


# =============================================================================
# 测试数据（覆盖完整业务场景）
# =============================================================================

# 5 位客户
CUSTOMERS_DATA = [
    # (id, name, phone, email, address, level)
    (1, "张伟",   "13800138001", "zhangwei@example.com",   "北京市朝阳区建国路88号", "svip"),
    (2, "李娜",   "13900139002", "lina@example.com",       "上海市浦东新区张江路100号", "vip"),
    (3, "王磊",   "13700137003", "wanglei@example.com",    "广州市天河区珠江新城", "normal"),
    (4, "陈静",   "13600136004", "chenjing@example.com",   "深圳市南山区科技园", "vip"),
    (5, "刘阳",   "13500135005", "liuyang@example.com",    "成都市高新区天府大道", "normal"),
]

# 8 款商品
PRODUCTS_DATA = [
    # (id, name, category, price, cost_price, stock, unit, description)
    (1, "苹果 iPhone 15 Pro 256GB", "手机",    8999.00, 6500.00, 50,  "台", "苹果最新旗舰手机，A17 Pro 芯片"),
    (2, "华为 Mate 60 Pro 512GB",   "手机",    7499.00, 5200.00, 30,  "台", "华为旗舰，支持卫星通话"),
    (3, "小米电视 65寸 4K",          "电视",   3299.00, 2100.00, 20,  "台", "65寸4K超高清，144Hz"),
    (4, "戴尔 XPS 15 笔记本",        "电脑",   9999.00, 7200.00, 15,  "台", "OLED屏，i9处理器，32GB内存"),
    (5, "AirPods Pro 2代",          "耳机",    1799.00, 900.00,  100, "副", "主动降噪，Apple H2芯片"),
    (6, "飞利浦 咖啡机",             "家电",    599.00,  280.00,  80,  "台", "全自动研磨，意式浓缩"),
    (7, "安踏运动鞋 2026款",         "鞋服",    399.00,  150.00,  200, "双", "专业跑鞋，碳板科技"),
    (8, "瑜伽垫 加厚防滑",           "运动",    129.00,  45.00,   500, "块", "10mm加厚，天然橡胶材质"),
]

# 10 条订单（订单号 1001-1010，覆盖所有状态）
ORDERS_DATA = [
    # (id, customer_id, total_amount, paid_amount, discount_amount, status, payment_status,
    #  payment_method, shipping_address, tracking_number, remark, created_at, shipped_at, delivered_at)
    (1001, 1, 8999.00, 8999.00, 0.00,    "delivered",  "paid",     "alipay",     "北京市朝阳区建国路88号",  "SF1234567890", "请放前台",      "2026-02-01 10:00:00", "2026-02-02 14:00:00", "2026-02-04 11:00:00"),
    (1002, 2, 7499.00, 7499.00, 0.00,    "shipped",    "paid",     "wechat",     "上海市浦东新区张江路100号","YT9876543210", None,            "2026-02-10 09:30:00", "2026-02-11 16:00:00", None),
    (1003, 3, 3499.00, 3199.00, 300.00,  "delivered",  "refunded", "alipay",     "广州市天河区珠江新城",    "ZT5566778899", "618活动优惠",   "2026-02-05 14:00:00", "2026-02-06 10:00:00", "2026-02-08 15:00:00"),
    (1004, 4, 11798.00,11798.00,0.00,    "confirmed",  "paid",     "creditcard", "深圳市南山区科技园",       None,           "两件商品",      "2026-02-15 11:00:00", None,                  None),
    (1005, 5, 1799.00, 1799.00, 0.00,    "delivered",  "paid",     "wechat",     "成都市高新区天府大道",    "SF2233445566", None,            "2026-02-08 16:00:00", "2026-02-09 10:00:00", "2026-02-11 14:00:00"),
    (1006, 1, 9999.00, 9999.00, 0.00,    "shipped",    "paid",     "alipay",     "北京市朝阳区建国路88号",  "JT7788990011", "加急配送",      "2026-02-18 08:00:00", "2026-02-19 09:00:00", None),
    (1007, 2, 598.00,  598.00,  0.00,    "delivered",  "paid",     "wechat",     "上海市浦东新区张江路100号","YT1122334455", None,            "2026-02-12 13:00:00", "2026-02-13 11:00:00", "2026-02-15 16:00:00"),
    (1008, 3, 528.00,  0.00,    0.00,    "cancelled",  "unpaid",   None,         "广州市天河区珠江新城",    None,           "超时未付款自动取消", "2026-02-14 20:00:00", None,                  None),
    (1009, 4, 399.00,  359.00,  40.00,   "pending",    "paid",     "alipay",     "深圳市南山区科技园",       None,           "会员折扣",      "2026-02-22 10:00:00", None,                  None),
    (1010, 5, 129.00,  129.00,  0.00,    "delivered",  "paid",     "wechat",     "成都市高新区天府大道",    "SF3344556677", None,            "2026-02-16 09:00:00", "2026-02-17 14:00:00", "2026-02-19 10:00:00"),
]

# 订单明细（与订单对应）
ORDER_ITEMS_DATA = [
    # (order_id, product_id, product_name, quantity, unit_price, total_price)
    (1001, 1, "苹果 iPhone 15 Pro 256GB", 1, 8999.00, 8999.00),
    (1002, 2, "华为 Mate 60 Pro 512GB",   1, 7499.00, 7499.00),
    (1003, 3, "小米电视 65寸 4K",         1, 3499.00, 3499.00),
    (1004, 1, "苹果 iPhone 15 Pro 256GB", 1, 8999.00, 8999.00),
    (1004, 2, "华为 Mate 60 Pro 512GB",   1, 2799.00, 2799.00),  # 促销价
    (1005, 5, "AirPods Pro 2代",          1, 1799.00, 1799.00),
    (1006, 4, "戴尔 XPS 15 笔记本",       1, 9999.00, 9999.00),
    (1007, 6, "飞利浦 咖啡机",            1,  599.00,  599.00),
    (1008, 6, "飞利浦 咖啡机",            1,  599.00,  599.00),
    (1008, 8, "瑜伽垫 加厚防滑",          1,  129.00,  129.00),
    (1009, 7, "安踏运动鞋 2026款",        1,  399.00,  399.00),
    (1010, 8, "瑜伽垫 加厚防滑",          1,  129.00,  129.00),
]

# 3 条退款记录（关联订单 1003、1007、1004）
REFUNDS_DATA = [
    # (order_id, amount, reason, status, refund_type, apply_at, processed_at, remark)
    (1003, 3199.00, "电视屏幕存在亮点，质量问题",   "completed", "return_refund",
     "2026-02-09 10:00:00", "2026-02-10 14:00:00", "已核实，全额退款"),
    (1007, 599.00,  "咖啡机噪音过大，与描述不符",   "approved",  "return_refund",
     "2026-02-16 09:00:00", "2026-02-17 10:00:00", "退款已打款，等待商品寄回"),
    (1004, 2799.00, "华为手机颜色不喜欢，申请退款", "pending",   "refund_only",
     "2026-02-20 15:00:00", None,                   "待客服审核"),
]


def seed_database(conn: sqlite3.Connection) -> None:
    """
    向指定的 SQLite 连接中初始化订单系统表结构并插入测试数据。

    该函数是幂等的：使用 INSERT OR IGNORE 防止重复插入。
    调用顺序：建表 → 插入客户 → 插入商品 → 插入订单 → 插入明细 → 插入退款

    Args:
        conn: SQLite 数据库连接（通常是 DatabaseQueryTool 的共享内存连接）
    """
    logger.info(f"{Fore.BLUE}[数据库初始化] 开始创建订单系统表结构...{Style.RESET_ALL}")
    cursor = conn.cursor()

    try:
        # ── 建表 ──────────────────────────────────────────────
        cursor.execute(CREATE_CUSTOMERS_TABLE)
        logger.debug(f"{Fore.CYAN}[数据库初始化] 创建 customers 表完成{Style.RESET_ALL}")

        cursor.execute(CREATE_PRODUCTS_TABLE)
        logger.debug(f"{Fore.CYAN}[数据库初始化] 创建 products 表完成{Style.RESET_ALL}")

        cursor.execute(CREATE_ORDERS_TABLE)
        logger.debug(f"{Fore.CYAN}[数据库初始化] 创建 orders 表完成{Style.RESET_ALL}")

        cursor.execute(CREATE_ORDER_ITEMS_TABLE)
        logger.debug(f"{Fore.CYAN}[数据库初始化] 创建 order_items 表完成{Style.RESET_ALL}")

        cursor.execute(CREATE_REFUNDS_TABLE)
        logger.debug(f"{Fore.CYAN}[数据库初始化] 创建 refunds 表完成{Style.RESET_ALL}")

        # ── 插入客户数据 ─────────────────────────────────────
        cursor.executemany(
            "INSERT OR IGNORE INTO customers (id, name, phone, email, address, level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            CUSTOMERS_DATA
        )
        logger.info(f"{Fore.GREEN}[数据库初始化] 已插入 {len(CUSTOMERS_DATA)} 条客户数据{Style.RESET_ALL}")

        # ── 插入商品数据 ─────────────────────────────────────
        cursor.executemany(
            "INSERT OR IGNORE INTO products "
            "(id, name, category, price, cost_price, stock, unit, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            PRODUCTS_DATA
        )
        logger.info(f"{Fore.GREEN}[数据库初始化] 已插入 {len(PRODUCTS_DATA)} 条商品数据{Style.RESET_ALL}")

        # ── 插入订单数据 ─────────────────────────────────────
        cursor.executemany(
            "INSERT OR IGNORE INTO orders "
            "(id, customer_id, total_amount, paid_amount, discount_amount, status, "
            "payment_status, payment_method, shipping_address, tracking_number, "
            "remark, created_at, shipped_at, delivered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ORDERS_DATA
        )
        logger.info(f"{Fore.GREEN}[数据库初始化] 已插入 {len(ORDERS_DATA)} 条订单数据（订单号 1001-1010）{Style.RESET_ALL}")

        # ── 插入订单明细 ─────────────────────────────────────
        cursor.executemany(
            "INSERT INTO order_items "
            "(order_id, product_id, product_name, quantity, unit_price, total_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ORDER_ITEMS_DATA
        )
        logger.info(f"{Fore.GREEN}[数据库初始化] 已插入 {len(ORDER_ITEMS_DATA)} 条订单明细{Style.RESET_ALL}")

        # ── 插入退款记录 ─────────────────────────────────────
        cursor.executemany(
            "INSERT INTO refunds "
            "(order_id, amount, reason, status, refund_type, apply_at, processed_at, remark) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            REFUNDS_DATA
        )
        logger.info(f"{Fore.GREEN}[数据库初始化] 已插入 {len(REFUNDS_DATA)} 条退款数据{Style.RESET_ALL}")

        conn.commit()
        logger.info(
            f"{Fore.GREEN}[数据库初始化] ✅ 订单测试数据库初始化完成！"
            f"包含 {len(CUSTOMERS_DATA)} 位客户, "
            f"{len(PRODUCTS_DATA)} 款商品, "
            f"{len(ORDERS_DATA)} 条订单 (1001-1010){Style.RESET_ALL}"
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"{Fore.RED}[数据库初始化] ❌ 数据初始化失败: {e}{Style.RESET_ALL}")
        raise


def print_data_summary(conn: sqlite3.Connection) -> None:
    """
    打印数据库数据摘要，方便调试时快速了解数据内容。

    Args:
        conn: SQLite 数据库连接
    """
    cursor = conn.cursor()
    logger.info(f"{Fore.CYAN}{'─'*50}{Style.RESET_ALL}")
    logger.info(f"{Fore.CYAN}[数据库] 当前测试数据概览：{Style.RESET_ALL}")

    tables = ["customers", "products", "orders", "order_items", "refunds"]
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            logger.info(f"{Fore.CYAN}  - {table:<15} {count} 条记录{Style.RESET_ALL}")
        except Exception:
            pass

    # 展示订单状态分布
    try:
        cursor.execute(
            "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status ORDER BY cnt DESC"
        )
        rows = cursor.fetchall()
        status_info = ", ".join(f"{r[0]}({r[1]})" for r in rows)
        logger.info(f"{Fore.CYAN}  - 订单状态分布: {status_info}{Style.RESET_ALL}")
    except Exception:
        pass

    logger.info(f"{Fore.CYAN}{'─'*50}{Style.RESET_ALL}")
