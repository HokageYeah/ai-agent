"""
浏览器自动化工具模块

本模块实现了 BrowserTool 类，为 Agent 提供基于 Playwright 的网页自动化能力。

功能特点：
1. 支持浏览器会话复用，多个工具调用共享同一页面状态
2. 支持网页导航、点击、输入、下拉选择、悬停、按键、滚动、执行 JS
3. 支持页面文本快照提取，适合给 LLM 低成本阅读网页内容
4. 支持截图与 PDF 导出，并自动落地到项目工作目录
5. 使用项目既有 Tool/ToolHub 架构，能够直接进入工具白名单与 function calling 链路
6. 提供详细中文日志，方便排查 Agent 在浏览器阶段的执行卡点

设计说明：
1. 不在 import 阶段直接依赖 Playwright 浏览器对象，避免测试环境未安装浏览器二进制时模块导入失败。
2. 工具实例由 ToolHub 单例注册，因此浏览器状态天然可在一次任务执行中跨步骤复用。
3. 输出统一返回结构化 dict，便于 ExecutionEngine、ToolCallingGateway 与前端日志统一消费。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from colorama import Fore, Style
from loguru import logger

from app.tools.base import ToolSchema
from app.tools.builtin.file import BaseFileTool
from app.utils.resource_path import get_project_root


class BrowserTool(BaseFileTool):
    """
    浏览器自动化工具。

    继承 BaseFileTool 的原因：
    1. 截图 / PDF 导出本质上是文件写入行为，直接复用既有路径校验逻辑更安全。
    2. 与 file_write / archive_extract 等工具保持一致的路径规范，降低 Agent 误写路径风险。
    """

    def __init__(
        self,
        screenshot_dir: str | Path | None = None,
        headless: bool = True,
        default_timeout_ms: int = 10_000,
        allow_full_paths: Optional[bool] = None,
    ) -> None:
        super().__init__(allow_full_paths=allow_full_paths)
        self._name = "browser"
        self._description = (
            "基于 Playwright 的浏览器自动化工具。支持网页导航、点击、输入、"
            "文本快照、截图保存、PDF 导出与关闭会话。适合需要真实浏览器渲染和交互的网站任务。"
        )
        self._headless = headless
        self._default_timeout_ms = default_timeout_ms
        self._artifact_dir = (
            Path(screenshot_dir).expanduser()
            if screenshot_dir
            else get_project_root() / "workspace" / "artifacts" / "browser"
        )

        # 运行时状态：由 ToolHub 维护单实例，因此同一任务内可复用会话。
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._session_lock = asyncio.Lock()

        logger.info(
            f"{Fore.GREEN}[BrowserTool] 浏览器工具初始化完成 | "
            f"headless={self._headless} | artifact_dir={self._artifact_dir}{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称。"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """获取浏览器工具 Schema。"""
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["navigate", "act", "snapshot", "screenshot", "pdf_save", "close"],
                        "description": "要执行的操作。navigate=打开网页，act=页面交互，snapshot=抓取页面文本快照，screenshot=保存截图，pdf_save=导出 PDF，close=关闭浏览器会话",
                    },
                    "url": {
                        "type": "string",
                        "description": "目标网页 URL，仅 navigate 时必填，当前仅允许 http/https 协议",
                    },
                    "act_type": {
                        "type": "string",
                        "enum": ["click", "fill", "select", "hover", "press", "scroll", "evaluate"],
                        "description": "当 action=act 时的具体交互类型",
                    },
                    "selector": {
                        "type": "string",
                        "description": "页面元素选择器，例如 '#login'、'input[name=q]' 或 'text=登录'",
                    },
                    "text": {
                        "type": "string",
                        "description": "fill/press/select 时使用的文本、按键或选项值",
                    },
                    "script": {
                        "type": "string",
                        "description": "act_type=evaluate 时执行的 JavaScript 表达式或函数",
                    },
                    "path": {
                        "type": "string",
                        "description": "截图或 PDF 的输出路径；不传时自动保存到 workspace/artifacts/browser 目录",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "单次操作超时时间，单位毫秒，默认 10000",
                        "default": 10000,
                        "minimum": 1000,
                        "maximum": 120000,
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                        "description": "navigate 等待页面到达的状态，默认 domcontentloaded",
                        "default": "domcontentloaded",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "截图时是否截取整页，默认 false",
                        "default": False,
                    },
                    "scroll_x": {
                        "type": "integer",
                        "description": "act_type=scroll 时横向滚动像素，默认 0",
                        "default": 0,
                    },
                    "scroll_y": {
                        "type": "integer",
                        "description": "act_type=scroll 时纵向滚动像素，默认 500",
                        "default": 500,
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行浏览器操作。

        统一入口设计原因：
        1. 便于与当前 ToolCallingGateway 的 JSON 参数校验模型对齐。
        2. 保留旧版 browser.py 的 action 分发习惯，降低迁移后的提示词改造成本。
        """
        action = str(params.get("action") or params.get("operation") or "").strip().lower()
        if not action:
            logger.warning("[BrowserTool] 缺少 action 参数")
            return self._error("unknown", "action 不能为空")

        timeout = self._normalize_timeout(params.get("timeout"))
        logger.info(
            f"{Fore.CYAN}[BrowserTool] 收到操作请求: action={action}, timeout={timeout}ms, params={params}{Style.RESET_ALL}"
        )

        async with self._session_lock:
            if action == "navigate":
                return await self._navigate(params=params, timeout=timeout)
            if action == "act":
                return await self._act(params=params, timeout=timeout)
            if action == "snapshot":
                return await self._snapshot()
            if action == "screenshot":
                return await self._screenshot(params=params)
            if action == "pdf_save":
                return await self._pdf_save(params=params)
            if action == "close":
                return await self._close()

            logger.warning(f"[BrowserTool] 未知操作: {action}")
            return self._error(action, f"未知操作: {action}")

    def _normalize_timeout(self, timeout: Any) -> int:
        """规范化超时参数，避免 LLM 传入非法类型导致 Playwright 报错信息过于底层。"""
        try:
            normalized = int(timeout or self._default_timeout_ms)
        except (TypeError, ValueError):
            normalized = self._default_timeout_ms
        return max(1000, min(normalized, 120_000))

    def _validate_web_url(self, url: str) -> tuple[bool, str]:
        """校验 URL，仅允许 http/https，避免工具被滥用于本地协议访问。"""
        if not url or not url.strip():
            return False, "navigate 需要提供 url"

        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            return False, f"仅支持 http/https 协议，当前为: {parsed.scheme or '无协议'}"
        if not parsed.netloc:
            return False, "URL 缺少有效域名"
        return True, ""

    async def _ensure_browser(self, timeout: int) -> tuple[bool, str]:
        """
        懒加载浏览器会话。

        说明：
        - 浏览器会话只在首次需要时创建；
        - 后续点击、截图、快照都复用同一页面，符合 Agent 多步操作场景。
        """
        if self._page is not None:
            try:
                self._page.set_default_timeout(timeout)
            except Exception:
                logger.debug("[BrowserTool] 更新默认超时失败，忽略并继续使用现有值")
            return True, ""

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.exception("[BrowserTool] Playwright Python 包未安装")
            return False, "Playwright 未安装，请使用 Poetry 环境并执行 `poetry install`"

        try:
            logger.info(f"{Fore.BLUE}[BrowserTool] 正在启动 Chromium 浏览器会话...{Style.RESET_ALL}")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 960},
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()
            self._page.set_default_timeout(timeout)
            logger.info(f"{Fore.GREEN}[BrowserTool] 浏览器会话启动成功{Style.RESET_ALL}")
            return True, ""
        except Exception as exc:
            logger.exception(f"[BrowserTool] 启动浏览器失败: {exc}")
            await self._cleanup_runtime()
            error_text = str(exc)
            if "Executable doesn't exist" in error_text or "browserType.launch" in error_text:
                return False, (
                    "Playwright 浏览器二进制尚未安装，请执行 "
                    "`poetry run playwright install chromium` 后再重试"
                )
            return False, f"启动浏览器失败: {error_text}"

    async def _navigate(self, params: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """导航到目标网页。"""
        url = str(params.get("url") or "").strip()
        wait_until = str(params.get("wait_until") or "domcontentloaded").strip()

        is_valid, error_msg = self._validate_web_url(url)
        if not is_valid:
            logger.warning(f"[BrowserTool] URL 校验失败: {error_msg}")
            return self._error("navigate", error_msg)

        ok, browser_error = await self._ensure_browser(timeout=timeout)
        if not ok:
            return self._error("navigate", browser_error, url=url)

        try:
            response = await self._page.goto(url, timeout=timeout, wait_until=wait_until)
            title = await self._page.title()
            status = response.status if response else None

            logger.info(
                f"{Fore.GREEN}[BrowserTool] 页面导航完成 | url={url} | "
                f"title={title} | status={status}{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "action": "navigate",
                "url": self._page.url,
                "title": title,
                "status": status,
                "message": f"已成功导航到页面: {title or self._page.url}",
            }
        except Exception as exc:
            logger.exception(f"[BrowserTool] 页面导航失败: {exc}")
            return self._error("navigate", f"导航失败: {exc}", url=url)

    async def _act(self, params: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行页面交互。"""
        if self._page is None:
            logger.warning("[BrowserTool] act 前未初始化页面")
            return self._error("act", "请先执行 navigate 打开网页")

        act_type = str(params.get("act_type") or "").strip().lower()
        selector = str(params.get("selector") or "").strip()
        text = str(params.get("text") or params.get("value") or "").strip()
        script = str(params.get("script") or "").strip()

        if not act_type:
            return self._error("act", "act 需要提供 act_type")

        try:
            if act_type == "click":
                if not selector:
                    return self._error("act", "click 需要提供 selector", act_type=act_type)
                await self._page.click(selector, timeout=timeout)
                return self._success("act", act_type=act_type, selector=selector, message=f"已点击元素: {selector}")

            if act_type == "fill":
                if not selector:
                    return self._error("act", "fill 需要提供 selector", act_type=act_type)
                await self._page.fill(selector, text, timeout=timeout)
                return self._success("act", act_type=act_type, selector=selector, text=text, message=f"已填写元素: {selector}")

            if act_type == "select":
                if not selector:
                    return self._error("act", "select 需要提供 selector", act_type=act_type)
                await self._page.select_option(selector, text, timeout=timeout)
                return self._success("act", act_type=act_type, selector=selector, text=text, message=f"已选择下拉项: {text}")

            if act_type == "hover":
                if not selector:
                    return self._error("act", "hover 需要提供 selector", act_type=act_type)
                await self._page.hover(selector, timeout=timeout)
                return self._success("act", act_type=act_type, selector=selector, message=f"已悬停元素: {selector}")

            if act_type == "press":
                key = text or "Enter"
                if selector:
                    await self._page.press(selector, key, timeout=timeout)
                else:
                    await self._page.keyboard.press(key)
                return self._success("act", act_type=act_type, selector=selector or None, text=key, message=f"已发送按键: {key}")

            if act_type == "scroll":
                scroll_x = self._safe_int(params.get("scroll_x"), default=0)
                scroll_y = self._safe_int(params.get("scroll_y"), default=500)
                await self._page.evaluate(
                    "(payload) => window.scrollBy(payload.x, payload.y)",
                    {"x": scroll_x, "y": scroll_y},
                )
                return self._success(
                    "act",
                    act_type=act_type,
                    scroll_x=scroll_x,
                    scroll_y=scroll_y,
                    message=f"页面已滚动 x={scroll_x}, y={scroll_y}",
                )

            if act_type == "evaluate":
                if not script:
                    return self._error("act", "evaluate 需要提供 script", act_type=act_type)
                result = await self._page.evaluate(script)
                return self._success(
                    "act",
                    act_type=act_type,
                    result=result,
                    result_preview=self._preview_json(result),
                    message="JavaScript 执行成功",
                )

            return self._error("act", f"未知 act_type: {act_type}", act_type=act_type)
        except Exception as exc:
            logger.exception(f"[BrowserTool] 页面交互失败: {exc}")
            return self._error(
                "act",
                f"页面交互失败: {exc}",
                act_type=act_type,
                selector=selector or None,
            )

    async def _snapshot(self) -> Dict[str, Any]:
        """提取页面文本快照，尽量降低 token 消耗。"""
        if self._page is None:
            logger.warning("[BrowserTool] snapshot 前未初始化页面")
            return self._error("snapshot", "请先执行 navigate 打开网页")

        try:
            title = await self._page.title()
            url = self._page.url
            text = await self._page.evaluate(
                """() => {
                    const body = document.body;
                    if (!body) return "";
                    const cloned = body.cloneNode(true);
                    cloned.querySelectorAll("script,style,noscript,svg,canvas").forEach(node => node.remove());
                    return (cloned.innerText || cloned.textContent || "").trim();
                }"""
            )
            text = (text or "").strip()
            truncated = False
            if len(text) > 4000:
                text = text[:4000] + "\n...（内容已截断）"
                truncated = True

            logger.info(
                f"{Fore.GREEN}[BrowserTool] 页面快照提取成功 | title={title} | "
                f"chars={len(text)} | truncated={truncated}{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "action": "snapshot",
                "title": title,
                "url": url,
                "content": text,
                "truncated": truncated,
                "message": "页面文本快照提取成功",
            }
        except Exception as exc:
            logger.exception(f"[BrowserTool] 页面快照失败: {exc}")
            return self._error("snapshot", f"页面快照失败: {exc}")

    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """截图保存到本地文件。"""
        if self._page is None:
            logger.warning("[BrowserTool] screenshot 前未初始化页面")
            return self._error("screenshot", "请先执行 navigate 打开网页")

        try:
            output_path = self._resolve_output_path(
                raw_path=str(params.get("path") or "").strip(),
                default_prefix="screenshot",
                suffix=".png",
            )
            full_page = bool(params.get("full_page", False))

            await self._page.screenshot(path=str(output_path), type="png", full_page=full_page)
            size = output_path.stat().st_size if output_path.exists() else 0

            logger.info(
                f"{Fore.GREEN}[BrowserTool] 截图保存成功: {output_path} | size={size}{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "action": "screenshot",
                "path": str(output_path),
                "size": size,
                "full_page": full_page,
                "message": "页面截图已保存",
            }
        except Exception as exc:
            logger.exception(f"[BrowserTool] 页面截图失败: {exc}")
            return self._error("screenshot", f"页面截图失败: {exc}")

    async def _pdf_save(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """将当前页面导出为 PDF。"""
        if self._page is None:
            logger.warning("[BrowserTool] pdf_save 前未初始化页面")
            return self._error("pdf_save", "请先执行 navigate 打开网页")

        try:
            output_path = self._resolve_output_path(
                raw_path=str(params.get("path") or params.get("pdf_path") or "").strip(),
                default_prefix="page",
                suffix=".pdf",
            )
            await self._page.pdf(path=str(output_path), format="A4", print_background=True)
            size = output_path.stat().st_size if output_path.exists() else 0

            logger.info(
                f"{Fore.GREEN}[BrowserTool] PDF 导出成功: {output_path} | size={size}{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "action": "pdf_save",
                "path": str(output_path),
                "size": size,
                "message": "页面 PDF 已导出",
            }
        except Exception as exc:
            logger.exception(f"[BrowserTool] 页面 PDF 导出失败: {exc}")
            return self._error("pdf_save", f"页面 PDF 导出失败: {exc}")

    async def _close(self) -> Dict[str, Any]:
        """关闭浏览器会话并清理运行时对象。"""
        await self._cleanup_runtime()
        logger.info(f"{Fore.GREEN}[BrowserTool] 浏览器会话已关闭{Style.RESET_ALL}")
        return {
            "success": True,
            "action": "close",
            "message": "浏览器会话已关闭",
        }

    async def _cleanup_runtime(self) -> None:
        """统一关闭页面、上下文、浏览器和 Playwright 运行时。"""
        close_steps = [
            ("page", self._page, "close"),
            ("context", self._context, "close"),
            ("browser", self._browser, "close"),
            ("playwright", self._playwright, "stop"),
        ]
        for obj_name, obj, method_name in close_steps:
            if obj is None:
                continue
            try:
                await getattr(obj, method_name)()
            except Exception as exc:
                logger.warning(f"[BrowserTool] 关闭 {obj_name} 失败，已忽略: {exc}")

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _resolve_output_path(self, raw_path: str, default_prefix: str, suffix: str) -> Path:
        """
        解析输出文件路径。

        设计原因：
        1. LLM 常常不主动传 path，因此这里自动生成稳定路径，减少工具调用失败。
        2. 若用户传入相对路径，也统一解析成绝对路径，便于后续 file_read / send_message 复用。
        """
        if raw_path:
            candidate = Path(self._expand_user_and_env(raw_path))
        else:
            filename = f"{default_prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{suffix}"
            candidate = self._artifact_dir / filename

        if candidate.suffix.lower() != suffix:
            candidate = candidate.with_suffix(suffix)

        is_valid, resolved_path, error_msg = self._validate_path(str(candidate))
        if not is_valid:
            raise ValueError(error_msg)

        resolved = Path(resolved_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def _safe_int(self, value: Any, default: int) -> int:
        """容错解析整数，避免 LLM 传错类型时直接抛异常。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _preview_json(self, value: Any, max_chars: int = 1000) -> str:
        """将 evaluate 结果序列化为可读文本，超长时截断。"""
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
        if len(text) > max_chars:
            return text[:max_chars] + "...（结果已截断）"
        return text

    def _success(self, action: str, **payload: Any) -> Dict[str, Any]:
        """构造统一成功响应。"""
        return {"success": True, "action": action, **payload}

    def _error(self, action: str, error: str, **payload: Any) -> Dict[str, Any]:
        """构造统一失败响应。"""
        return {"success": False, "action": action, "error": error, **payload}
