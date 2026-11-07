"""Secure Code Execution Sandbox for Visualization and Mathematical Reasoning.

Provides AST-based static safety validation, prohibited module blocking,
timeout enforcement, and isolated subprocess execution for generating
charts, plots, and graphical representations.
"""

import ast
import asyncio
import base64
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.logging import logger

# Whitelisted standard/data-science modules safe for visualization
ALLOWED_MODULES: Set[str] = {
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.dates",
    "matplotlib.ticker",
    "matplotlib.colors",
    "matplotlib.patches",
    "seaborn",
    "pandas",
    "numpy",
    "math",
    "datetime",
    "collections",
    "itertools",
    "re",
    "io",
    "base64",
    "json",
    "random",
    "decimal",
    "fractions",
    "statistics",
}

# Explicitly prohibited modules that could compromise system security
FORBIDDEN_MODULES: Set[str] = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "shutil",
    "pty",
    "posix",
    "ptyprocess",
    "multiprocessing",
    "threading",
    "signal",
    "ctypes",
    "builtins",
    "importlib",
    "pip",
    "webbrowser",
    "pickle",
    "shelve",
    "dbm",
    "sqlite3",
    "inspect",
    "gc",
}

# Dangerous call targets or builtins
FORBIDDEN_CALLS: Set[str] = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "input",
    "exit",
    "quit",
}

# Forbidden attribute names (prevent sandbox breakout via introspection)
FORBIDDEN_ATTRS: Set[str] = {
    "__class__",
    "__bases__",
    "__subclasses__",
    "__mro__",
    "__code__",
    "__globals__",
    "__dict__",
    "__builtins__",
    "__import__",
}


@dataclass
class ExecutionResult:
    """Represents the outcome of a sandboxed code execution."""

    success: bool
    image_base64: Optional[str] = None
    code: str = ""
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert execution result to serializable dict."""
        return {
            "success": self.success,
            "has_image": bool(self.image_base64),
            "image_base64": self.image_base64,
            "code": self.code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }


class SafetyValidator(ast.NodeVisitor):
    """AST visitor that checks for disallowed modules, calls, and attributes."""

    def __init__(self) -> None:
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_pkg = alias.name.split(".")[0]
            if base_pkg in FORBIDDEN_MODULES:
                self.errors.append(f"Forbidden module import: '{alias.name}'")
            elif alias.name not in ALLOWED_MODULES and base_pkg not in ALLOWED_MODULES:
                self.errors.append(f"Unauthorized module import: '{alias.name}'. Only visualization libraries are allowed.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_pkg = node.module.split(".")[0]
            if base_pkg in FORBIDDEN_MODULES:
                self.errors.append(f"Forbidden module import from: '{node.module}'")
            elif node.module not in ALLOWED_MODULES and base_pkg not in ALLOWED_MODULES:
                self.errors.append(f"Unauthorized module import from: '{node.module}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct calls like eval(...), open(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                self.errors.append(f"Disallowed function call: '{node.func.id}'")
        # Check method calls like __import__(...) or obj.eval(...)
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_CALLS:
                self.errors.append(f"Disallowed method call: '{node.func.attr}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTRS:
            self.errors.append(f"Disallowed introspection attribute access: '{node.attr}'")
        self.generic_visit(node)


def validate_code_safety(code: str) -> Tuple[bool, Optional[str]]:
    """Statically analyze Python code for security violations using AST."""
    if not code or not code.strip():
        return False, "Code is empty."

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error in generated code: {e}"

    validator = SafetyValidator()
    validator.visit(tree)

    if validator.errors:
        return False, "; ".join(validator.errors)

    return True, None


def extract_python_code(raw_text: str) -> str:
    """Extract pure Python code from markdown code fences or raw string."""
    if not raw_text:
        return ""

    # Look for ```python ... ``` or ``` ... ```
    if "```python" in raw_text:
        start = raw_text.find("```python") + len("```python")
        end = raw_text.find("```", start)
        if end != -1:
            return raw_text[start:end].strip()
        return raw_text[start:].strip()
    elif "```" in raw_text:
        start = raw_text.find("```") + 3
        # If language identifier on first line, skip it
        newline = raw_text.find("\n", start)
        if newline != -1:
            start = newline + 1
        end = raw_text.find("```", start)
        if end != -1:
            return raw_text[start:end].strip()
        return raw_text[start:].strip()

    return raw_text.strip()


def _prepare_headless_script(code: str) -> str:
    """Inject headless matplotlib configuration and auto-save figure hooks."""
    prologue = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
    )

    epilogue = (
        "\n\n# Auto-save figure if opened\n"
        "import matplotlib.pyplot as plt\n"
        "if plt.get_fignums():\n"
        "    plt.savefig('output.png', bbox_inches='tight', dpi=150)\n"
        "    plt.close('all')\n"
    )

    return f"{prologue}\n{code}\n{epilogue}"


def _execute_subprocess(script_path: Path, work_dir: Path, timeout: float) -> Tuple[bool, str, str, Optional[str]]:
    """Execute python script inside temporary workspace with strict timeout."""
    python_bin = sys.executable

    # Inherit system environment for OS dynamic linker while scrubbing API keys and secrets
    clean_env = os.environ.copy()
    sensitive_keys = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "SECRET_KEY",
        "DATABASE_URL",
        "RAZORPAY_KEY",
        "RAZORPAY_SECRET",
        "LANGCHAIN_API_KEY",
    ]
    for key in sensitive_keys:
        clean_env.pop(key, None)

    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    clean_env["MPLBACKEND"] = "Agg"

    try:
        proc = subprocess.run(
            [python_bin, str(script_path)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env,
        )
        return (
            proc.returncode == 0,
            proc.stdout,
            proc.stderr,
            None if proc.returncode == 0 else f"Process exited with return code {proc.returncode}",
        )
    except subprocess.TimeoutExpired:
        return False, "", "", f"Execution timed out after {timeout} seconds."
    except Exception as e:
        return False, "", "", f"Subprocess launch error: {str(e)}"


async def execute_code_safely(
    code: str,
    timeout: float = 10.0,
) -> ExecutionResult:
    """Validate, isolate, and execute visualization code to generate a chart.

    Args:
        code: Python source code (raw or extracted from markdown).
        timeout: Maximum wall-clock time allowed in seconds.

    Returns:
        ExecutionResult with status, base64 image data, stdout/stderr, and timing.
    """
    clean_code = extract_python_code(code)
    start_time = time.monotonic()

    # Step 1: AST Safety Check
    is_safe, error_msg = validate_code_safety(clean_code)
    if not is_safe:
        elapsed = (time.monotonic() - start_time) * 1000.0
        logger.warning(f"Sandbox security rejection: {error_msg}")
        return ExecutionResult(
            success=False,
            code=clean_code,
            error=f"Security Policy Violation: {error_msg}",
            execution_time_ms=elapsed,
        )

    # Step 2: Execute in ephemeral temporary directory
    def _run_in_sandbox() -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="rag_sandbox_") as tmp_dir:
            work_path = Path(tmp_dir)
            script_file = work_path / "script.py"
            wrapped_code = _prepare_headless_script(clean_code)
            script_file.write_text(wrapped_code, encoding="utf-8")

            success, stdout, stderr, run_error = _execute_subprocess(
                script_file, work_path, timeout=timeout
            )

            # Check if output image was produced
            image_base64 = None
            out_img = work_path / "output.png"
            if out_img.exists() and out_img.stat().st_size > 0:
                raw_bytes = out_img.read_bytes()
                b64_str = base64.b64encode(raw_bytes).decode("ascii")
                image_base64 = f"data:image/png;base64,{b64_str}"

            elapsed_ms = (time.monotonic() - start_time) * 1000.0

            if not success and not run_error:
                run_error = stderr.strip() or "Script failed with non-zero exit status."

            return ExecutionResult(
                success=success and (image_base64 is not None or not run_error),
                image_base64=image_base64,
                code=clean_code,
                stdout=stdout,
                stderr=stderr,
                error=run_error,
                execution_time_ms=elapsed_ms,
            )

    return await asyncio.to_thread(_run_in_sandbox)
