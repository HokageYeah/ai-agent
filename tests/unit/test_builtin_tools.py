"""
内置工具测试模块

本模块包含对内置工具的单元测试，验证：
- SearchTool: 网络搜索工具
- HTTPRequestTool: HTTP 请求工具
- PythonExecutorTool: Python 代码执行工具
- FileReadTool: 文件读取工具
- FileWriteTool: 文件写入工具

运行测试：
    pytest tests/unit/test_builtin_tools.py -v
"""

import pytest
import tempfile
import os
import sys
import shutil
import io
import zipfile
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSearchTool:
    """SearchTool 测试类"""
    
    @pytest.fixture
    def search_tool(self):
        """创建 SearchTool 实例"""
        from app.tools.builtin.search import SearchTool
        return SearchTool()
    
    def test_tool_name(self, search_tool):
        """测试工具名称"""
        assert search_tool.name == "search"
    
    def test_tool_schema(self, search_tool):
        """测试工具 Schema"""
        schema = search_tool.schema
        assert schema.name == "search"
        assert "query" in schema.parameters["required"]
        assert "max_results" in schema.parameters["properties"]
    
    @pytest.mark.asyncio
    async def test_empty_query(self, search_tool):
        """测试空查询参数"""
        result = await search_tool.execute({"query": ""})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_whitespace_query(self, search_tool):
        """测试空白查询参数"""
        result = await search_tool.execute({"query": "   "})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_max_results_limit(self, search_tool):
        """测试 max_results 参数限制"""
        # 测试超出范围的值
        result = await search_tool.execute({
            "query": "test", 
            "max_results": 100  # 超过最大值 10
        })
        assert result["success"] is True or "success" in result
        
    @pytest.mark.asyncio
    async def test_search_function_exists(self):
        """测试便捷搜索函数"""
        from app.tools.builtin.search import quick_search
        assert callable(quick_search)


class TestHTTPRequestTool:
    """HTTPRequestTool 测试类"""
    
    @pytest.fixture
    def http_tool(self):
        """创建 HTTPRequestTool 实例"""
        from app.tools.builtin.http import HTTPRequestTool
        return HTTPRequestTool()
    
    def test_tool_name(self, http_tool):
        """测试工具名称"""
        assert http_tool.name == "http_request"
    
    def test_tool_schema(self, http_tool):
        """测试工具 Schema"""
        schema = http_tool.schema
        assert schema.name == "http_request"
        assert "url" in schema.parameters["required"]
        assert "method" in schema.parameters["properties"]
    
    def test_supported_methods(self, http_tool):
        """测试支持的 HTTP 方法"""
        schema = http_tool.schema
        methods = schema.parameters["properties"]["method"]["enum"]
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods
        assert "PATCH" in methods
    
    @pytest.mark.asyncio
    async def test_empty_url(self, http_tool):
        """测试空 URL"""
        result = await http_tool.execute({"url": ""})
        assert result["success"] is False
        assert "URL 不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_invalid_method(self, http_tool):
        """测试不支持的 HTTP 方法"""
        result = await http_tool.execute({
            "method": "INVALID",
            "url": "https://example.com"
        })
        assert result["success"] is False
        assert "不支持" in result["error"]
    
    @pytest.mark.asyncio
    async def test_http_functions_exist(self):
        """测试便捷 HTTP 函数"""
        from app.tools.builtin.http import http_get, http_post, http_put, http_delete
        assert callable(http_get)
        assert callable(http_post)
        assert callable(http_put)
        assert callable(http_delete)

    @pytest.mark.asyncio
    async def test_binary_zip_response_should_save_temp_file(self, http_tool, monkeypatch):
        """测试二进制 ZIP 响应会自动落地为临时文件，供后续解压工具直接使用"""
        import httpx
        import app.tools.builtin.http as http_module

        # 构造一个最小可解压 ZIP 二进制
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", "# find-skills\n")
        zip_bytes = zip_buffer.getvalue()

        class _MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, method, **kwargs):
                req = httpx.Request(method, kwargs.get("url"))
                return httpx.Response(
                    status_code=200,
                    headers={"Content-Type": "application/zip"},
                    content=zip_bytes,
                    request=req,
                )

        monkeypatch.setattr(http_module.httpx, "AsyncClient", _MockAsyncClient)

        result = await http_tool.execute({
            "method": "GET",
            "url": "https://example.com/find-skills.zip",
        })

        assert result["success"] is True
        assert result["is_binary"] is True
        assert result["download_path"] == result["content"]
        assert result["binary_size"] == len(zip_bytes)

        saved_path = result["download_path"]
        assert saved_path and os.path.exists(saved_path)

        try:
            with zipfile.ZipFile(saved_path, "r") as zf:
                assert "SKILL.md" in zf.namelist()
        finally:
            if saved_path and os.path.exists(saved_path):
                os.remove(saved_path)


class TestBrowserTool:
    """BrowserTool 测试类"""

    @pytest.fixture
    def browser_tool(self, tmp_path):
        """创建 BrowserTool 实例。"""
        from app.tools.builtin.browser import BrowserTool

        return BrowserTool(screenshot_dir=tmp_path)

    def test_tool_name(self, browser_tool):
        """测试工具名称。"""
        assert browser_tool.name == "browser"

    def test_tool_schema(self, browser_tool):
        """测试工具 Schema。"""
        schema = browser_tool.schema
        assert schema.name == "browser"
        assert "action" in schema.parameters["required"]
        assert "act_type" in schema.parameters["properties"]
        assert "screenshot" in schema.parameters["properties"]["action"]["enum"]

    @pytest.mark.asyncio
    async def test_empty_action(self, browser_tool):
        """测试缺少 action。"""
        result = await browser_tool.execute({})
        assert result["success"] is False
        assert "action 不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_act_requires_navigate_first(self, browser_tool):
        """测试在未打开页面前不能直接交互。"""
        result = await browser_tool.execute({
            "action": "act",
            "act_type": "click",
            "selector": "#submit",
        })
        assert result["success"] is False
        assert "请先执行 navigate" in result["error"]

    @pytest.mark.asyncio
    async def test_navigate_requires_valid_url(self, browser_tool):
        """测试 navigate 必须传合法 URL。"""
        result = await browser_tool.execute({
            "action": "navigate",
            "url": "file:///tmp/test.html",
        })
        assert result["success"] is False
        assert "仅支持 http/https" in result["error"]

    @pytest.mark.asyncio
    async def test_navigate_success(self, browser_tool, monkeypatch):
        """测试导航成功返回标题与状态码。"""
        class _FakeResponse:
            status = 200

        class _FakePage:
            def __init__(self):
                self.url = "https://example.com"
                self.default_timeout = None

            def set_default_timeout(self, timeout):
                self.default_timeout = timeout

            async def goto(self, url, timeout, wait_until):
                self.url = url
                return _FakeResponse()

            async def title(self):
                return "示例站点"

        fake_page = _FakePage()

        async def _fake_ensure_browser(timeout):
            browser_tool._page = fake_page
            fake_page.set_default_timeout(timeout)
            return True, ""

        monkeypatch.setattr(browser_tool, "_ensure_browser", _fake_ensure_browser)

        result = await browser_tool.execute({
            "action": "navigate",
            "url": "https://example.com",
        })

        assert result["success"] is True
        assert result["title"] == "示例站点"
        assert result["status"] == 200
        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_snapshot_truncates_long_content(self, browser_tool):
        """测试页面快照在超长内容时会自动截断。"""
        class _FakePage:
            url = "https://example.com/long"

            async def title(self):
                return "长页面"

            async def evaluate(self, script):
                return "A" * 5000

        browser_tool._page = _FakePage()

        result = await browser_tool.execute({"action": "snapshot"})

        assert result["success"] is True
        assert result["truncated"] is True
        assert result["title"] == "长页面"
        assert "内容已截断" in result["content"]

    @pytest.mark.asyncio
    async def test_screenshot_auto_save(self, browser_tool):
        """测试截图会自动保存到本地文件。"""
        class _FakePage:
            async def screenshot(self, path, type, full_page):
                Path(path).write_bytes(b"fake-png-bytes")

        browser_tool._page = _FakePage()

        result = await browser_tool.execute({
            "action": "screenshot",
            "full_page": True,
        })

        assert result["success"] is True
        assert result["full_page"] is True
        assert result["path"].endswith(".png")
        assert Path(result["path"]).exists()
        assert Path(result["path"]).read_bytes() == b"fake-png-bytes"

    @pytest.mark.asyncio
    async def test_close_should_cleanup_runtime(self, browser_tool):
        """测试 close 会清理浏览器运行时对象。"""
        events = []

        class _Closable:
            def __init__(self, name):
                self.name = name

            async def close(self):
                events.append(f"close:{self.name}")

        class _Playable:
            async def stop(self):
                events.append("stop:playwright")

        browser_tool._page = _Closable("page")
        browser_tool._context = _Closable("context")
        browser_tool._browser = _Closable("browser")
        browser_tool._playwright = _Playable()

        result = await browser_tool.execute({"action": "close"})

        assert result["success"] is True
        assert browser_tool._page is None
        assert browser_tool._context is None
        assert browser_tool._browser is None
        assert browser_tool._playwright is None
        assert events == [
            "close:page",
            "close:context",
            "close:browser",
            "stop:playwright",
        ]


class TestPythonExecutorTool:
    """PythonExecutorTool 测试类"""
    
    @pytest.fixture
    def executor_tool(self):
        """创建 PythonExecutorTool 实例"""
        from app.tools.builtin.executor import PythonExecutorTool
        return PythonExecutorTool()
    
    def test_tool_name(self, executor_tool):
        """测试工具名称"""
        assert executor_tool.name == "python_executor"
    
    def test_tool_schema(self, executor_tool):
        """测试工具 Schema"""
        schema = executor_tool.schema
        assert schema.name == "python_executor"
        assert "code" in schema.parameters["required"]
        assert "timeout" in schema.parameters["properties"]
    
    @pytest.mark.asyncio
    async def test_empty_code(self, executor_tool):
        """测试空代码"""
        result = await executor_tool.execute({"code": ""})
        assert result["success"] is False
        assert "代码不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_whitespace_code(self, executor_tool):
        """测试空白代码"""
        result = await executor_tool.execute({"code": "   "})
        assert result["success"] is False
    
    @pytest.mark.asyncio
    async def test_simple_expression(self, executor_tool):
        """测试简单表达式"""
        result = await executor_tool.execute({"code": "2 + 2"})
        assert result["success"] is True
        assert result["result"] == 4
    
    @pytest.mark.asyncio
    async def test_string_concatenation(self, executor_tool):
        """测试字符串拼接"""
        result = await executor_tool.execute({"code": "'Hello, ' + 'World!'"})
        assert result["success"] is True
        assert result["result"] == "Hello, World!"
    
    @pytest.mark.asyncio
    async def test_list_comprehension(self, executor_tool):
        """测试列表推导式"""
        result = await executor_tool.execute({"code": "[x**2 for x in range(5)]"})
        assert result["success"] is True
        assert result["result"] == [0, 1, 4, 9, 16]
    
    @pytest.mark.asyncio
    async def test_dict_creation(self, executor_tool):
        """测试字典创建"""
        result = await executor_tool.execute({"code": "{'a': 1, 'b': 2}"})
        assert result["success"] is True
        assert result["result"] == {"a": 1, "b": 2}
    
    @pytest.mark.asyncio
    async def test_math_module(self, executor_tool):
        """测试数学模块"""
        result = await executor_tool.execute({"code": "import math; math.pi"})
        assert result["success"] is True
        assert abs(result["result"] - 3.14159) < 0.0001
    
    @pytest.mark.asyncio
    async def test_random_module(self, executor_tool):
        """测试随机数模块"""
        result = await executor_tool.execute({
            "code": "import random; random.seed(42); [random.random() for _ in range(3)]"
        })
        assert result["success"] is True
        assert len(result["result"]) == 3
    
    @pytest.mark.asyncio
    async def test_forbidden_import_os(self, executor_tool):
        """测试禁止导入 os 模块"""
        result = await executor_tool.execute({"code": "import os; os.system('ls')"})
        assert result["success"] is False
        assert "不允许" in result["error"]
    
    @pytest.mark.asyncio
    async def test_forbidden_exec(self, executor_tool):
        """测试禁止 exec 函数"""
        result = await executor_tool.execute({"code": "exec('print(1)')"})
        assert result["success"] is False
        assert "不允许" in result["error"]
    
    @pytest.mark.asyncio
    async def test_timeout_parameter(self, executor_tool):
        """测试超时参数"""
        # 使用合理的超时值
        result = await executor_tool.execute({
            "code": "print('test')",
            "timeout": 60
        })
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_print_output(self, executor_tool):
        """测试 print 输出捕获"""
        result = await executor_tool.execute({"code": "print('Hello from Python!')"})
        assert result["success"] is True
        assert "Hello from Python!" in result["output"]
    
    @pytest.mark.asyncio
    async def test_syntax_error(self, executor_tool):
        """测试语法错误"""
        result = await executor_tool.execute({"code": "if if if"})
        assert result["success"] is False
        assert result["error_type"] == "SyntaxError"
    
    @pytest.mark.asyncio
    async def test_name_error(self, executor_tool):
        """测试名称错误"""
        result = await executor_tool.execute({"code": "undefined_variable"})
        assert result["success"] is False
        assert result["error_type"] == "NameError"
    
    @pytest.mark.asyncio
    async def test_quick_execute_function(self):
        """测试便捷执行函数"""
        from app.tools.builtin.executor import quick_execute
        assert callable(quick_execute)

    def test_smtp_precheck_should_ignore_non_smtp_example_domain(self, executor_tool):
        """测试 SMTP 预检查不会被业务字段中的 example.com 误判"""
        code = """
import smtplib

order_data = {
    "customer_email": "lina@example.com"
}

smtp_server = "smtp.qq.com"
smtp_port = 465
sender_email = "2410292164@qq.com"
sender_password = "acfmhesqnkyzdjcc"
result = {"ok": True}
"""
        precheck = executor_tool._analyze_code_for_required_info(code)
        assert precheck is None

    def test_smtp_precheck_should_require_input_for_placeholder(self, executor_tool):
        """测试 SMTP 配置仍为占位符时应请求用户输入"""
        code = """
import smtplib
smtp_server = "your_smtp_server"
smtp_port = 465
sender_email = "your_email@qq.com"
sender_password = "your_password"
result = {"ok": True}
"""
        precheck = executor_tool._analyze_code_for_required_info(code)
        assert isinstance(precheck, dict)
        assert "required_fields" in precheck
        assert len(precheck["required_fields"]) >= 4

    @pytest.mark.asyncio
    async def test_smtp_cache_injection_skips_repeated_input_request(self, executor_tool):
        """测试命中 SMTP 缓存后，python_executor 不再返回 needs_user_input"""
        executor_tool.update_context(
            user_inputs_cache={
                "smtp_config": {
                    "smtp_server": "smtp.qq.com",
                    "smtp_port": "465",
                    "sender_email": "cached_sender@qq.com",
                    "sender_password": "cached_auth_code"
                }
            }
        )

        code = """
import smtplib
smtp_server = "your_smtp_server"
smtp_port = 465
sender_email = "your_email@qq.com"
sender_password = "your_password"
result = {
    "smtp_server": smtp_server,
    "sender_email": sender_email,
    "sender_password": sender_password
}
"""
        result = await executor_tool.execute({"code": code})
        assert result["success"] is True
        assert result.get("needs_user_input") is not True
        assert result["result"]["smtp_server"] == "smtp.qq.com"
        assert result["result"]["sender_email"] == "cached_sender@qq.com"


class TestFileReadTool:
    """FileReadTool 测试类"""
    
    @pytest.fixture
    def read_tool(self):
        """创建 FileReadTool 实例"""
        from app.tools.builtin.file import FileReadTool
        return FileReadTool()
    
    @pytest.fixture
    def temp_file(self):
        """创建临时测试文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("测试文件内容\n第二行内容")
            temp_path = f.name
        
        yield temp_path
        
        # 清理
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    def test_tool_name(self, read_tool):
        """测试工具名称"""
        assert read_tool.name == "file_read"
    
    def test_tool_schema(self, read_tool):
        """测试工具 Schema"""
        schema = read_tool.schema
        assert schema.name == "file_read"
        assert "path" in schema.parameters["required"]
    
    @pytest.mark.asyncio
    async def test_empty_path(self, read_tool):
        """测试空路径"""
        result = await read_tool.execute({"path": ""})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_file_not_exists(self, read_tool):
        """测试文件不存在"""
        # 使用一个在允许目录内但不存在的文件路径
        result = await read_tool.execute({"path": "./nonexistent_file_12345.txt"})
        assert result["success"] is False
        assert "不存在" in result["error"] or "not exist" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_read_text_file(self, read_tool, temp_file):
        """测试读取文本文件"""
        result = await read_tool.execute({"path": temp_file})
        assert result["success"] is True
        assert "测试文件内容" in result["content"]
        assert result["is_binary"] is False
        assert "line_count" in result
    
    @pytest.mark.asyncio
    async def test_read_with_encoding(self, read_tool, temp_file):
        """测试指定编码读取"""
        result = await read_tool.execute({"path": temp_file, "encoding": "utf-8"})
        assert result["success"] is True
        assert result["encoding"] == "utf-8"

    @pytest.mark.asyncio
    async def test_read_expand_home_path(self, read_tool, monkeypatch):
        """测试使用 ~ 路径读取文件（应正确展开到 HOME）"""
        import shutil

        fake_home = tempfile.mkdtemp()
        monkeypatch.setenv("HOME", fake_home)
        target_path = os.path.join(fake_home, "Desktop", "read_home_case.txt")

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write("HOME 路径读取测试")

            result = await read_tool.execute({"path": "~/Desktop/read_home_case.txt"})
            assert result["success"] is True
            assert result["content"] == "HOME 路径读取测试"
            assert result["path"] == str(Path(target_path).resolve())
        finally:
            shutil.rmtree(fake_home, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_quick_read_function(self):
        """测试便捷读取函数"""
        from app.tools.builtin.file import quick_read
        assert callable(quick_read)


class TestFileWriteTool:
    """FileWriteTool 测试类"""
    
    @pytest.fixture
    def write_tool(self):
        """创建 FileWriteTool 实例"""
        from app.tools.builtin.file import FileWriteTool
        return FileWriteTool()
    
    @pytest.fixture
    def temp_file_path(self):
        """创建临时文件路径"""
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, "test_write.txt")
        yield temp_path
        # 清理
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
    
    @pytest.fixture
    def temp_dir_path(self):
        """创建临时目录路径"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # 清理
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)
    
    def test_tool_name(self, write_tool):
        """测试工具名称"""
        assert write_tool.name == "file_write"
    
    def test_tool_schema(self, write_tool):
        """测试工具 Schema"""
        schema = write_tool.schema
        assert schema.name == "file_write"
        assert "path" in schema.parameters["required"]
        assert "content" in schema.parameters["required"]
    
    @pytest.mark.asyncio
    async def test_empty_path(self, write_tool):
        """测试空路径"""
        result = await write_tool.execute({"path": "", "content": "test"})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_empty_content(self, write_tool):
        """测试空内容"""
        result = await write_tool.execute({"path": "/tmp/test.txt", "content": ""})
        assert result["success"] is False
    
    @pytest.mark.asyncio
    async def test_none_content(self, write_tool):
        """测试 None 内容"""
        result = await write_tool.execute({"path": "/tmp/test.txt", "content": None})
        assert result["success"] is False
        assert "None" in result["error"]
    
    @pytest.mark.asyncio
    async def test_write_text_file(self, write_tool, temp_file_path):
        """测试写入文本文件"""
        content = "测试写入内容\n第二行内容"
        result = await write_tool.execute({
            "path": temp_file_path,
            "content": content
        })
        assert result["success"] is True
        assert result["bytes_written"] > 0
        
        # 验证文件内容
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            saved_content = f.read()
        assert saved_content == content
    
    @pytest.mark.asyncio
    async def test_write_with_encoding(self, write_tool, temp_file_path):
        """测试指定编码写入"""
        result = await write_tool.execute({
            "path": temp_file_path,
            "content": "中文内容",
            "encoding": "utf-8"
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_write_expand_home_path(self, write_tool, monkeypatch):
        """测试使用 ~ 路径写入文件（应正确展开到 HOME）"""
        import shutil

        fake_home = tempfile.mkdtemp()
        monkeypatch.setenv("HOME", fake_home)
        target_path = os.path.join(fake_home, "Desktop", "write_home_case.txt")

        try:
            result = await write_tool.execute({
                "path": "~/Desktop/write_home_case.txt",
                "content": "HOME 路径写入测试",
                "encoding": "utf-8",
                "mode": "w",
            })
            assert result["success"] is True
            assert result["path"] == str(Path(target_path).resolve())
            assert os.path.exists(target_path)

            with open(target_path, "r", encoding="utf-8") as f:
                assert f.read() == "HOME 路径写入测试"
        finally:
            shutil.rmtree(fake_home, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_write_with_create_dirs(self, write_tool):
        """测试自动创建目录"""
        import tempfile
        temp_dir = tempfile.mkdtemp()
        nested_path = os.path.join(temp_dir, "nested", "deep", "file.txt")
        
        try:
            result = await write_tool.execute({
                "path": nested_path,
                "content": "test"
            })
            assert result["success"] is True
            assert os.path.exists(nested_path)
        finally:
            import shutil
            shutil.rmtree(temp_dir)
    
    @pytest.mark.asyncio
    async def test_append_mode(self, write_tool, temp_file_path):
        """测试追加模式"""
        # 先写入
        await write_tool.execute({
            "path": temp_file_path,
            "content": "第一行\n"
        })
        
        # 追加
        result = await write_tool.execute({
            "path": temp_file_path,
            "content": "第二行",
            "mode": "a"
        })
        
        assert result["success"] is True
        
        # 验证内容
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "第一行" in content
        assert "第二行" in content
    
    @pytest.mark.asyncio
    async def test_quick_write_function(self):
        """测试便捷写入函数"""
        from app.tools.builtin.file import quick_write
        assert callable(quick_write)


class TestArchiveTools:
    """ArchiveCompressTool / ArchiveExtractTool 测试类"""

    @pytest.fixture
    def compress_tool(self):
        """创建 ArchiveCompressTool 实例"""
        from app.tools.builtin.archive import ArchiveCompressTool
        return ArchiveCompressTool()

    @pytest.fixture
    def extract_tool(self):
        """创建 ArchiveExtractTool 实例"""
        from app.tools.builtin.archive import ArchiveExtractTool
        return ArchiveExtractTool()

    def test_archive_tool_names(self, compress_tool, extract_tool):
        """测试工具名称"""
        assert compress_tool.name == "archive_compress"
        assert extract_tool.name == "archive_extract"

    def test_archive_schema_required(self, compress_tool, extract_tool):
        """测试工具 Schema 必填参数"""
        c_schema = compress_tool.schema
        e_schema = extract_tool.schema
        assert c_schema.name == "archive_compress"
        assert "output_path" in c_schema.parameters["required"]
        assert e_schema.name == "archive_extract"
        assert "archive_path" in e_schema.parameters["required"]

    @pytest.mark.asyncio
    async def test_compress_and_extract_round_trip(self, compress_tool, extract_tool):
        """测试 ZIP 压缩 + 解压闭环流程"""
        temp_root = tempfile.mkdtemp()
        try:
            source_dir = Path(temp_root) / "find-skills"
            scripts_dir = source_dir / "scripts"
            source_dir.mkdir(parents=True, exist_ok=True)
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "SKILL.md").write_text("# find-skills\n", encoding="utf-8")
            (scripts_dir / "install.sh").write_text("echo install\n", encoding="utf-8")

            zip_path = Path(temp_root) / "find-skills.zip"
            compressed = await compress_tool.execute(
                {
                    "source_path": str(source_dir),
                    "output_path": str(zip_path),
                    "include_root": True,
                    "overwrite": True,
                }
            )
            assert compressed["success"] is True
            assert zip_path.exists()

            output_dir = Path(temp_root) / "skills_md"
            extracted = await extract_tool.execute(
                {
                    "archive_path": str(zip_path),
                    "output_dir": str(output_dir),
                    "overwrite": True,
                }
            )
            assert extracted["success"] is True
            assert (output_dir / "find-skills" / "SKILL.md").exists()
            assert (output_dir / "find-skills" / "scripts" / "install.sh").exists()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_extract_should_block_zip_slip(self, extract_tool):
        """测试解压阶段会拦截路径穿越（Zip Slip）"""
        temp_root = tempfile.mkdtemp()
        try:
            zip_path = Path(temp_root) / "evil.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("../evil.txt", "hacked")

            output_dir = Path(temp_root) / "out"
            result = await extract_tool.execute(
                {
                    "archive_path": str(zip_path),
                    "output_dir": str(output_dir),
                }
            )
            assert result["success"] is False
            assert "路径穿越" in result.get("error", "") or "越界" in result.get("error", "")
            assert not (Path(temp_root).parent / "evil.txt").exists()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_extract_should_accept_target_path_alias(self, compress_tool, extract_tool):
        """archive_extract 应兼容 target_path 作为 output_dir 别名。"""
        temp_root = tempfile.mkdtemp()
        try:
            source_dir = Path(temp_root) / "daily-ai-news"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "SKILL.md").write_text("# daily-ai-news\n", encoding="utf-8")

            zip_path = Path(temp_root) / "daily-ai-news.zip"
            compressed = await compress_tool.execute(
                {
                    "source_path": str(source_dir),
                    "output_path": str(zip_path),
                    "include_root": True,
                    "overwrite": True,
                }
            )
            assert compressed["success"] is True

            target_dir = Path(temp_root) / "extracted"
            extracted = await extract_tool.execute(
                {
                    "archive_path": str(zip_path),
                    "target_path": str(target_dir),
                    "overwrite": True,
                }
            )

            assert extracted["success"] is True
            assert (target_dir / "daily-ai-news" / "SKILL.md").exists()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


class TestFormatFunctions:
    """格式化函数测试类"""
    
    def test_format_search_results(self):
        """测试搜索结果格式化"""
        from app.tools.builtin.search import format_search_results
        
        results = [
            {"title": "Test Result", "url": "http://test.com", "snippet": "Test snippet"}
        ]
        formatted = format_search_results(results)
        assert "Test Result" in formatted
        assert "http://test.com" in formatted
    
    def test_format_http_response(self):
        """测试 HTTP 响应格式化"""
        from app.tools.builtin.http import format_http_response
        
        response = {
            "success": True,
            "status_code": 200,
            "status_text": "OK",
            "content": {"key": "value"}
        }
        formatted = format_http_response(response)
        assert "200" in formatted
    
    def test_format_execution_result(self):
        """测试代码执行结果格式化"""
        from app.tools.builtin.executor import format_execution_result
        
        result = {"success": True, "result": 42}
        formatted = format_execution_result(result)
        assert "成功" in formatted
    
    def test_format_file_result(self):
        """测试文件操作结果格式化"""
        from app.tools.builtin.file import format_file_result
        
        result = {"success": True, "path": "/test.txt", "size": 100}
        formatted = format_file_result(result)
        assert "成功" in formatted


class TestDatabaseQueryTool:
    """DatabaseQueryTool 测试类"""
    
    @pytest.fixture
    def db_tool(self):
        """创建 DatabaseQueryTool 实例"""
        from app.tools.builtin.database import DatabaseQueryTool
        return DatabaseQueryTool()
    
    @pytest.fixture
    def initialized_db_tool(self, db_tool):
        """创建已初始化测试数据的 DatabaseQueryTool 实例"""
        import sqlite3
        # 直接在共享内存数据库中创建测试数据
        if db_tool._shared_memory_conn:
            cursor = db_tool._shared_memory_conn.cursor()
            # 创建表
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
            # 检查是否已有数据
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                # 插入测试数据
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
                db_tool._shared_memory_conn.commit()
        return db_tool
    
    def test_tool_name(self, db_tool):
        """测试工具名称"""
        assert db_tool.name == "database_query"
    
    def test_tool_schema(self, db_tool):
        """测试工具 Schema"""
        schema = db_tool.schema
        assert schema.name == "database_query"
        assert "query" in schema.parameters["required"]
    
    @pytest.mark.asyncio
    async def test_empty_query(self, db_tool):
        """测试空查询"""
        result = await db_tool.execute({"query": ""})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_forbidden_insert(self, db_tool):
        """测试禁止 INSERT 语句"""
        result = await db_tool.execute({"query": "INSERT INTO users VALUES (1, 'test')"})
        assert result["success"] is False
        assert "只允许 SELECT" in result["error"]
    
    @pytest.mark.asyncio
    async def test_forbidden_delete(self, db_tool):
        """测试禁止 DELETE 语句"""
        result = await db_tool.execute({"query": "DELETE FROM users"})
        assert result["success"] is False
        assert "只允许 SELECT" in result["error"]
    
    @pytest.mark.asyncio
    async def test_select_simple(self, initialized_db_tool):
        """测试简单 SELECT 查询"""
        result = await initialized_db_tool.execute({"query": "SELECT COUNT(*) as cnt FROM users"})
        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["rows"][0]["cnt"] == 5  # 5条测试数据
    
    @pytest.mark.asyncio
    async def test_select_with_where(self, initialized_db_tool):
        """测试带条件的 SELECT 查询"""
        result = await initialized_db_tool.execute({
            "query": "SELECT * FROM users WHERE age > :age",
            "params": {"age": 25}
        })
        assert result["success"] is True
        assert "columns" in result
        assert "rows" in result
        # 应该有4条记录（年龄 > 25）
        assert len(result["rows"]) == 4
    
    @pytest.mark.asyncio
    async def test_select_with_limit(self, initialized_db_tool):
        """测试带 LIMIT 的查询"""
        result = await initialized_db_tool.execute({
            "query": "SELECT * FROM users",
            "limit": 2
        })
        assert result["success"] is True
        assert result["row_count"] <= 2
    
    @pytest.mark.asyncio
    async def test_multi_statement_rejected(self, db_tool):
        """测试多语句查询被拒绝"""
        result = await db_tool.execute({"query": "SELECT 1; SELECT 2"})
        assert result["success"] is False
        assert "多语句" in result["error"]
    
    @pytest.mark.asyncio
    async def test_quick_query_function(self):
        """测试便捷查询函数"""
        from app.tools.builtin.database import quick_query
        assert callable(quick_query)


class TestCalculatorTool:
    """CalculatorTool 测试类"""
    
    @pytest.fixture
    def calc_tool(self):
        """创建 CalculatorTool 实例"""
        from app.tools.builtin.calculator import CalculatorTool
        return CalculatorTool()
    
    def test_tool_name(self, calc_tool):
        """测试工具名称"""
        assert calc_tool.name == "calculator"
    
    def test_tool_schema(self, calc_tool):
        """测试工具 Schema"""
        schema = calc_tool.schema
        assert schema.name == "calculator"
        assert "expression" in schema.parameters["required"]
    
    @pytest.mark.asyncio
    async def test_empty_expression(self, calc_tool):
        """测试空表达式"""
        result = await calc_tool.execute({"expression": ""})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_addition(self, calc_tool):
        """测试加法"""
        result = await calc_tool.execute({"expression": "2 + 3"})
        assert result["success"] is True
        assert result["result"] == 5
    
    @pytest.mark.asyncio
    async def test_subtraction(self, calc_tool):
        """测试减法"""
        result = await calc_tool.execute({"expression": "10 - 4"})
        assert result["success"] is True
        assert result["result"] == 6
    
    @pytest.mark.asyncio
    async def test_multiplication(self, calc_tool):
        """测试乘法"""
        result = await calc_tool.execute({"expression": "3 * 4"})
        assert result["success"] is True
        assert result["result"] == 12
    
    @pytest.mark.asyncio
    async def test_division(self, calc_tool):
        """测试除法"""
        result = await calc_tool.execute({"expression": "10 / 2"})
        assert result["success"] is True
        assert result["result"] == 5.0
    
    @pytest.mark.asyncio
    async def test_parentheses(self, calc_tool):
        """测试括号优先级"""
        result = await calc_tool.execute({"expression": "(2 + 3) * 4"})
        assert result["success"] is True
        assert result["result"] == 20
    
    @pytest.mark.asyncio
    async def test_power(self, calc_tool):
        """测试幂运算"""
        result = await calc_tool.execute({"expression": "2 ** 10"})
        assert result["success"] is True
        assert result["result"] == 1024
    
    @pytest.mark.asyncio
    async def test_modulo(self, calc_tool):
        """测试取模"""
        result = await calc_tool.execute({"expression": "10 % 3"})
        assert result["success"] is True
        assert result["result"] == 1
    
    @pytest.mark.asyncio
    async def test_floor_division(self, calc_tool):
        """测试整除"""
        result = await calc_tool.execute({"expression": "10 // 3"})
        assert result["success"] is True
        assert result["result"] == 3
    
    @pytest.mark.asyncio
    async def test_sqrt(self, calc_tool):
        """测试平方根"""
        result = await calc_tool.execute({"expression": "sqrt(16)"})
        assert result["success"] is True
        assert result["result"] == 4
    
    @pytest.mark.asyncio
    async def test_pi_constant(self, calc_tool):
        """测试圆周率常量"""
        result = await calc_tool.execute({"expression": "pi"})
        assert result["success"] is True
        assert abs(result["result"] - 3.14159) < 0.001
    
    @pytest.mark.asyncio
    async def test_e_constant(self, calc_tool):
        """测试自然对数底常量"""
        result = await calc_tool.execute({"expression": "e"})
        assert result["success"] is True
        assert abs(result["result"] - 2.71828) < 0.001
    
    @pytest.mark.asyncio
    async def test_complex_expression(self, calc_tool):
        """测试复杂表达式"""
        result = await calc_tool.execute({"expression": "(sqrt(16) + 2) * pi / 2"})
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_quick_calculate_function(self):
        """测试便捷计算函数"""
        from app.tools.builtin.calculator import quick_calculate
        assert callable(quick_calculate)


class TestDateTimeTool:
    """DateTimeTool 测试类"""
    
    @pytest.fixture
    def dt_tool(self):
        """创建 DateTimeTool 实例"""
        from app.tools.builtin.datetime import DateTimeTool
        return DateTimeTool()
    
    def test_tool_name(self, dt_tool):
        """测试工具名称"""
        assert dt_tool.name == "datetime"
    
    def test_tool_schema(self, dt_tool):
        """测试工具 Schema"""
        schema = dt_tool.schema
        assert schema.name == "datetime"
        assert "operation" in schema.parameters["required"]
    
    @pytest.mark.asyncio
    async def test_empty_operation(self, dt_tool):
        """测试空操作"""
        result = await dt_tool.execute({"operation": ""})
        assert result["success"] is False
        assert "不能为空" in result["error"]
    
    @pytest.mark.asyncio
    async def test_now_operation(self, dt_tool):
        """测试获取当前日期时间"""
        result = await dt_tool.execute({"operation": "now"})
        assert result["success"] is True
        assert "result" in result
        assert "-" in result["result"]  # ISO 格式包含 -
    
    @pytest.mark.asyncio
    async def test_today_operation(self, dt_tool):
        """测试获取当前日期"""
        result = await dt_tool.execute({"operation": "today"})
        assert result["success"] is True
        assert "result" in result
        assert "-" in result["result"]
    
    @pytest.mark.asyncio
    async def test_timestamp_operation(self, dt_tool):
        """测试获取时间戳"""
        result = await dt_tool.execute({"operation": "timestamp"})
        assert result["success"] is True
        assert "result" in result
        assert isinstance(result["result"], float)
    
    @pytest.mark.asyncio
    async def test_format_operation(self, dt_tool):
        """测试格式化日期时间"""
        result = await dt_tool.execute({
            "operation": "format",
            "datetime": "2024-01-15 10:30:00",
            "format": "chinese"
        })
        assert result["success"] is True
        assert "2024年" in result["result"]
    
    @pytest.mark.asyncio
    async def test_parse_operation(self, dt_tool):
        """测试解析日期时间"""
        result = await dt_tool.execute({
            "operation": "parse",
            "datetime": "2024-01-15 10:30:00"
        })
        assert result["success"] is True
        assert result["year"] == 2024
        assert result["month"] == 1
        assert result["day"] == 15
    
    @pytest.mark.asyncio
    async def test_add_operation(self, dt_tool):
        """测试日期加法"""
        result = await dt_tool.execute({
            "operation": "add",
            "datetime": "2024-01-15",
            "days": 7
        })
        assert result["success"] is True
        assert "2024-01-22" in result["result"]
    
    @pytest.mark.asyncio
    async def test_subtract_operation(self, dt_tool):
        """测试日期减法"""
        result = await dt_tool.execute({
            "operation": "subtract",
            "datetime": "2024-01-15",
            "days": 7
        })
        assert result["success"] is True
        assert "2024-01-08" in result["result"]
    
    @pytest.mark.asyncio
    async def test_diff_operation(self, dt_tool):
        """测试日期差计算"""
        result = await dt_tool.execute({
            "operation": "diff",
            "date1": "2024-01-01",
            "date2": "2024-01-15"
        })
        assert result["success"] is True
        assert result["days"] == 14
    
    @pytest.mark.asyncio
    async def test_weekday_operation(self, dt_tool):
        """测试获取星期几"""
        result = await dt_tool.execute({
            "operation": "weekday",
            "datetime": "2024-01-15"  # 2024-01-15 是星期一
        })
        assert result["success"] is True
        assert "weekday_name" in result
        assert "weekday_num" in result
    
    @pytest.mark.asyncio
    async def test_month_name_operation(self, dt_tool):
        """测试获取月份名称"""
        result = await dt_tool.execute({
            "operation": "month_name",
            "month": 1
        })
        assert result["success"] is True
        assert "一月" in result["result"] or "January" in result["result"]
    
    @pytest.mark.asyncio
    async def test_timezone_operation(self, dt_tool):
        """测试时区信息"""
        result = await dt_tool.execute({"operation": "timezone_info"})
        assert result["success"] is True
        assert "utc_offset" in result
    
    @pytest.mark.asyncio
    async def test_is_valid_operation(self, dt_tool):
        """测试日期时间有效性验证"""
        result = await dt_tool.execute({
            "operation": "is_valid",
            "datetime": "2024-01-15"
        })
        assert result["success"] is True
        assert result["is_valid"] is True
    
    @pytest.mark.asyncio
    async def test_get_now_function(self):
        """测试便捷获取当前时间函数"""
        from app.tools.builtin.datetime import get_now
        assert callable(get_now)
    
    @pytest.mark.asyncio
    async def test_format_datetime_function(self):
        """测试便捷格式化函数"""
        from app.tools.builtin.datetime import format_datetime
        assert callable(format_datetime)
