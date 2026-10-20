#!/usr/bin/env python3
"""Production RAG Agent Python Asset Optimization & Build Script.

Generates bundle.min.css, bundle.min.js, pricing.min.js, precompressed .gz and .br files,
and manifest.json in app/static/dist without touching original source files.
"""

import gzip
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_STATIC = ROOT_DIR / "app" / "static"
DIST_STATIC = SRC_STATIC / "dist"
SRC_TEMPLATES = ROOT_DIR / "app" / "templates"
DIST_TEMPLATES = ROOT_DIR / "app" / "templates_dist"

CSS_SOURCES = [
    "css/variables.css",
    "css/sidebar.css",
    "css/chat.css",
    "css/modals.css",
    "css/responsive.css",
    "css/app.css",
]

JS_SOURCES = [
    "js/api/tokens.js",
    "js/api/client.js",
    "js/api/endpoints.js",
    "js/api.js",
    "js/sse.js",
    "js/modules/utils.js",
    "js/modules/validator/validator_rules.js",
    "js/modules/validator/validator_files.js",
    "js/modules/validator/validator_ui.js",
    "js/modules/validator.js",
    "js/modules/markdown.js",
    "js/modules/auth/auth_ui.js",
    "js/modules/auth/auth_actions.js",
    "js/modules/auth/auth_events.js",
    "js/modules/auth.js",
    "js/modules/rooms/rooms_list.js",
    "js/modules/rooms/rooms_members.js",
    "js/modules/rooms/rooms_crud.js",
    "js/modules/rooms.js",
    "js/modules/documents/documents_list.js",
    "js/modules/documents/documents_upload.js",
    "js/modules/documents/documents_actions.js",
    "js/modules/documents.js",
    "js/modules/memory.js",
    "js/modules/history.js",
    "js/modules/evidence.js",
    "js/modules/settings.js",
    "js/modules/organizations.js",
    "js/modules/chat.js",
    "js/modules/agents.js",
    "js/app.js",
]

STANDALONE_JS_MODULES = [
    {
        "sources": [
            "js/modules/pricing/pricing_state.js",
            "js/modules/pricing/pricing_api.js",
            "js/modules/pricing/pricing_ui.js",
            "js/modules/pricing/pricing_checkout.js",
            "js/modules/pricing/pricing_invoices.js",
            "js/modules/pricing.js",
        ],
        "dist": "pricing.min.js",
    },
]


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def minify_css(css: str) -> str:
    """Minify CSS by stripping comments and redundant whitespace."""
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{}:;,>+~])\s*", r"\1", css)
    css = css.replace(";}", "}")
    return css.strip()


def minify_js(js: str) -> str:
    """Minify JS safely preserving strings and syntax."""
    # Strip multi-line comments
    js = re.sub(r"/\*[\s\S]*?\*/", "", js)
    # Strip single-line comments that are on their own line or follow whitespace
    js = re.sub(r"(?m)^\s*//.*$", "", js)
    # Strip trailing whitespace and collapse consecutive empty lines
    lines = [line.strip() for line in js.splitlines() if line.strip()]
    return "\n".join(lines)


def minify_html(html: str) -> str:
    """Minify HTML while preserving Jinja2 syntax."""
    html = re.sub(r"<!--(?!\[if)[\s\S]*?-->", "", html)
    html = re.sub(r"\{#[\s\S]*?#\}", "", html)
    html = re.sub(r">\s{2,}<", ">\n<", html)
    return html.strip()


def precompress(file_path: Path, data: bytes):
    """Write .gz and .br precompressed files."""
    gz_path = file_path.with_suffix(file_path.suffix + ".gz")
    with gzip.open(gz_path, "wb", compresslevel=9) as f:
        f.write(data)
    gz_size = gz_path.stat().st_size

    br_size = 0
    try:
        import brotli
        br_path = file_path.with_suffix(file_path.suffix + ".br")
        compressed_br = brotli.compress(data, quality=11)
        br_path.write_bytes(compressed_br)
        br_size = len(compressed_br)
    except ImportError:
        pass

    return gz_size, br_size


def build():
    start_time = time.time()
    DIST_STATIC.mkdir(parents=True, exist_ok=True)
    DIST_TEMPLATES.mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": "1.0.0",
        "build_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {},
    }

    # 1. CSS Bundle
    combined_css = ""
    orig_css_bytes = 0
    for rel_path in CSS_SOURCES:
        p = SRC_STATIC / rel_path
        if p.exists():
            content = p.read_text(encoding="utf-8")
            orig_css_bytes += len(content.encode("utf-8"))
            combined_css += f"/* {rel_path} */\n" + content + "\n"

    min_css = minify_css(combined_css)
    css_bytes = min_css.encode("utf-8")
    css_hash = hashlib.sha256(css_bytes).hexdigest()[:10]
    css_out = DIST_STATIC / "bundle.min.css"
    css_out.write_bytes(css_bytes)
    css_gz, css_br = precompress(css_out, css_bytes)

    manifest["files"]["bundle.min.css"] = {
        "path": "/static/dist/bundle.min.css",
        "hash": css_hash,
        "versioned_path": f"/static/dist/bundle.min.css?v={css_hash}",
        "original_size": orig_css_bytes,
        "minified_size": len(css_bytes),
        "gzip_size": css_gz,
        "brotli_size": css_br,
    }

    # 2. JS Bundle
    combined_js = ""
    orig_js_bytes = 0
    for rel_path in JS_SOURCES:
        p = SRC_STATIC / rel_path
        if p.exists():
            content = p.read_text(encoding="utf-8")
            orig_js_bytes += len(content.encode("utf-8"))
            combined_js += f"\n/* {rel_path} */\n" + content + "\n"

    min_js = minify_js(combined_js)
    js_bytes = min_js.encode("utf-8")
    js_hash = hashlib.sha256(js_bytes).hexdigest()[:10]
    js_out = DIST_STATIC / "bundle.min.js"
    js_out.write_bytes(js_bytes)
    js_gz, js_br = precompress(js_out, js_bytes)

    manifest["files"]["bundle.min.js"] = {
        "path": "/static/dist/bundle.min.js",
        "hash": js_hash,
        "versioned_path": f"/static/dist/bundle.min.js?v={js_hash}",
        "original_size": orig_js_bytes,
        "minified_size": len(js_bytes),
        "gzip_size": js_gz,
        "brotli_size": js_br,
    }

    # 3. Standalone Modules
    for mod in STANDALONE_JS_MODULES:
        combined_content = f"/* Production Bundle: {mod['dist']} */\n"
        orig_bytes = 0
        for rel_path in mod["sources"]:
            p = SRC_STATIC / rel_path
            if p.exists():
                c = p.read_text(encoding="utf-8")
                orig_bytes += len(c.encode("utf-8"))
                combined_content += f"\n/* --- {rel_path} --- */\n" + c + "\n"

        if orig_bytes == 0:
            continue

        min_mod = minify_js(combined_content)
        mod_bytes = min_mod.encode("utf-8")
        mod_hash = hashlib.sha256(mod_bytes).hexdigest()[:10]
        mod_out = DIST_STATIC / mod["dist"]
        mod_out.write_bytes(mod_bytes)
        mod_gz, mod_br = precompress(mod_out, mod_bytes)

        manifest["files"][mod["dist"]] = {
            "path": f"/static/dist/{mod['dist']}",
            "hash": mod_hash,
            "versioned_path": f"/static/dist/{mod['dist']}?v={mod_hash}",
            "original_size": orig_bytes,
            "minified_size": len(mod_bytes),
            "gzip_size": mod_gz,
            "brotli_size": mod_br,
        }

    # 4. HTML Templates
    for root, _, files in os.walk(SRC_TEMPLATES):
        rel = Path(root).relative_to(SRC_TEMPLATES)
        out_dir = DIST_TEMPLATES / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith(".html"):
                raw = (Path(root) / f).read_text(encoding="utf-8")
                opt = minify_html(raw)
                (out_dir / f).write_text(opt, encoding="utf-8")

    # Write Manifest
    manifest_file = DIST_STATIC / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    elapsed = int((time.time() - start_time) * 1000)
    print("\n" + "=" * 70)
    print("  ⚡ RAG AGENT ASSET BUILD & OPTIMIZATION PIPELINE (PYTHON)")
    print("=" * 70)
    for fname, data in manifest["files"].items():
        orig = format_bytes(data["original_size"])
        mini = format_bytes(data["minified_size"])
        gz = format_bytes(data["gzip_size"])
        pct = (1 - data["minified_size"] / max(1, data["original_size"])) * 100
        print(f"  • {fname:<18} | Orig: {orig:<9} | Min: {mini:<9} | Gzip: {gz:<9} | Saved: {pct:.1f}%")
    print("-" * 70)
    print(f"  ✅ Dist Output: {DIST_STATIC}")
    print(f"  ✅ Completed in {elapsed}ms\n")


if __name__ == "__main__":
    build()
