"""代码可执行性检查 - 方案书 3.5.1 节

使用 ast.parse 做 Python 语法检查 + 危险操作检测。
不实际执行代码，仅静态分析。
"""

import ast
import re
from typing import Optional

from loguru import logger


# 危险函数/模块名称
_DANGEROUS_NAMES = {
    "eval", "exec", "compile", "__import__",
    "globals", "locals", "vars",
    "open", "input",
}

_DANGEROUS_MODULES = {
    "os", "sys", "subprocess", "shutil",
    "pathlib", "ctypes", "multiprocessing",
    "socket", "http", "urllib", "requests",
    "pickle", "marshal",
}


def check_code_safety(code: str, lang: Optional[str] = None) -> tuple[bool, str]:
    """检查代码安全性和语法正确性

    按代码块语言区分：
      - lang="python" (```python)：真 Python 代码，严格 ast.parse 检查
      - lang="" 或无语言标记 (```)：视为伪代码/说明，跳过 AST 或只查危险调用
      - 其他语言标记：跳过

    Args:
        code: Python 代码字符串
        lang: markdown 代码块语言标记（如 "python"、""、"bash"）

    Returns:
        (is_safe, message):
            is_safe=True 时 message 为 "语法检查通过"
            is_safe=False 时 message 为具体问题描述
            (True, "伪代码，跳过 AST 检查") 表示伪代码未做语法检查但无危险调用
    """
    if not code or not code.strip():
        return True, "空代码，跳过检查"

    # 识别语言：只有 ```python 才是真 Python 代码
    code = code.strip()
    lang_normalized = lang.strip().lower() if lang else None

    # 非 Python 代码块（```bash、```javascript 等）→ 跳过
    if lang_normalized is not None and lang_normalized not in ("python", "py"):
        return True, f"非 Python 代码块 (lang={lang_normalized})，跳过检查"

    # lang=""（显式无标记的 ``` 代码块）视为伪代码 → 只查危险调用，跳过 AST 语法检查
    # lang=None（不传参，兼容旧调用）→ 按严格模式处理
    # 这样中文全角括号不会误报 SyntaxError
    is_pseudocode = (lang is not None and lang_normalized != "python" and lang_normalized != "py")

    # 去除 markdown 代码块标记（```python ... ``` 或 ``` ... ```）
    code = re.sub(r"^```(?:\w+)?\s*\n?", "", code)
    code = re.sub(r"\n?```\s*$", "", code)

    if is_pseudocode:
        # 伪代码：只查危险调用，不进行 AST 语法检查
        issues = _check_dangerous_calls_simple(code)
        if issues:
            return False, "; ".join(issues)
        return True, "伪代码，跳过 AST 检查（无危险调用）"

    # === 真 Python 代码：严格 ast.parse 检查 ===
    # 1. 语法检查
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e.msg} (行{e.lineno})"

    # 2. 危险操作检测
    issues = []
    for node in ast.walk(tree):
        # 检测函数调用
        if isinstance(node, ast.Call):
            func_name = _get_call_name(node)
            if func_name in _DANGEROUS_NAMES:
                issues.append(f"危险函数调用: {func_name} (行{node.lineno})")

        # 检测 import
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in _DANGEROUS_MODULES:
                    issues.append(f"危险模块导入: {alias.name} (行{node.lineno})")

        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _DANGEROUS_MODULES:
                issues.append(f"危险模块导入: from {node.module} import ... (行{node.lineno})")

        # 检测属性访问（如 os.system, subprocess.run）
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr in ("system", "popen", "run", "Popen", "call", "check_call", "check_output"):
                issues.append(f"潜在危险操作: .{attr}() (行{node.lineno})")

    if issues:
        return False, "; ".join(issues)

    return True, "语法检查通过"


def _check_dangerous_calls_simple(code: str) -> list[str]:
    """对伪代码做简易危险调用检测（不依赖 ast.parse）

    正则扫描常见危险关键字，避免对伪代码做完整的 AST 解析。
    """
    issues = []
    lines = code.split("\n")
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        # 跳过注释和空行
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        # 检查危险函数名
        for name in _DANGEROUS_NAMES:
            if re.search(rf'\b{re.escape(name)}\s*\(', stripped):
                issues.append(f"危险函数调用: {name} (行{lineno})")
        # 检查 import
        for mod in _DANGEROUS_MODULES:
            if re.search(rf'\bimport\s+{re.escape(mod)}\b', stripped) or \
               re.search(rf'\bfrom\s+{re.escape(mod)}\s+import', stripped):
                issues.append(f"危险模块导入: {mod} (行{lineno})")
    return issues


def _get_call_name(node: ast.Call) -> str:
    """提取函数调用的名称"""
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def check_focused_output_code(code_example: Optional[str]) -> Optional[str]:
    """检查 FocusedOutput.code_example 的安全性

    Args:
        code_example: FocusedOutput 中的 code_example 字段

    Returns:
        None 表示安全或空代码；
        字符串表示警告信息（不安全时）
    """
    if not code_example or not code_example.strip():
        return None

    is_safe, message = check_code_safety(code_example, lang="python")
    if not is_safe:
        logger.warning(f"代码安全检查未通过: {message}")
        return message
    return None


# 匹配 markdown 代码块：捕获语言标记和内容
_CODE_BLOCK_RE = re.compile(
    r"```(\w*)\s*\n(.*?)\n```",
    re.DOTALL,
)


def check_code_in_markdown(markdown: Optional[str]) -> Optional[str]:
    """检查 Markdown 正文中实际包含的代码块安全性

    讲义和实操指南都是独立 LLM 生成的，不一定引用 FocusedOutput.code_example。
    应当检查"实际展示给学生看的代码"，而非生成阶段那份 code_example。

    从 markdown 中提取所有 ```lang``` 代码块，按语言标记区分检查：
      - ```python → 真代码，严格 AST 检查
      - ```（无标记） → 伪代码/说明，跳过 AST 或只查危险调用
      - 其他语言标记 → 跳过
    这样中文伪代码里的全角括号不再误报。

    Args:
        markdown: 讲义 content_markdown / 实操指南 steps_markdown 等正文

    Returns:
        None 表示无代码块或全部安全；
        字符串表示合并的警告信息（有代码块未通过检查时）
    """
    if not markdown or not markdown.strip():
        return None

    blocks = _CODE_BLOCK_RE.findall(markdown)
    if not blocks:
        return None  # 正文里没有代码块，无需标注警告

    issues: list[str] = []
    for idx, (lang, code) in enumerate(blocks, start=1):
        if not code.strip():
            continue
        is_safe, message = check_code_safety(code, lang=lang)
        if not is_safe:
            issues.append(f"代码块{idx}: {message}")

    if not issues:
        return None

    combined = "; ".join(issues)
    logger.warning(f"Markdown 代码块安全检查未通过: {combined}")
    return combined
