#!/usr/bin/env node
/**
 * Production RAG Agent Asset Optimization & Build Pipeline
 *
 * Optimizes CSS, JavaScript, and HTML templates into a dedicated distribution
 * directory (`app/static/dist` and `app/templates_dist`) without modifying source files.
 *
 * Features:
 * - Bundles and minifies multi-file CSS into single cached bundle.min.css
 * - Bundles and minifies multi-module JS into bundle.min.js with sourcemaps
 * - Generates standalone minified modules (pricing.min.js)
 * - Produces Gzip (.gz) and Brotli (.br) pre-compressed assets for 0-CPU static serving
 * - Generates manifest.json with content hashes for immutable cache busting
 * - Jinja2-safe HTML template minification (removes comments & collapses redundant whitespace)
 * - Supports --watch mode for live incremental developer builds
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');

const SRC_STATIC = path.join(ROOT_DIR, 'app', 'static');
const DIST_STATIC = path.join(SRC_STATIC, 'dist');
const SRC_TEMPLATES = path.join(ROOT_DIR, 'app', 'templates');
const DIST_TEMPLATES = path.join(ROOT_DIR, 'app', 'templates_dist');

// Dynamic import for esbuild
let esbuild;
try {
  esbuild = await import('esbuild');
} catch (e) {
  console.warn('[Build] esbuild not found, falling back to built-in minifier.');
}

// Ordered CSS sources for bundle
const CSS_SOURCES = [
  'css/variables.css',
  'css/sidebar.css',
  'css/chat.css',
  'css/modals.css',
  'css/responsive.css',
  'css/app.css',
  'css/audit_risk.css',
  'css/theme.css',
];

// Ordered JS sources for main app bundle
const JS_SOURCES = [
  'js/api/tokens.js',
  'js/api/client.js',
  'js/api/endpoints.js',
  'js/api.js',
  'js/sse.js',
  'js/modules/utils.js',
  'js/modules/validator/validator_rules.js',
  'js/modules/validator/validator_files.js',
  'js/modules/validator/validator_ui.js',
  'js/modules/validator.js',
  'js/modules/markdown.js',
  'js/modules/auth/auth_ui.js',
  'js/modules/auth/auth_actions.js',
  'js/modules/auth/auth_events.js',
  'js/modules/auth.js',
  'js/modules/rooms/rooms_list.js',
  'js/modules/rooms/rooms_members.js',
  'js/modules/rooms/rooms_crud.js',
  'js/modules/rooms.js',
  'js/modules/documents/documents_list.js',
  'js/modules/documents/documents_upload.js',
  'js/modules/documents/documents_actions.js',
  'js/modules/documents.js',
  'js/modules/memory.js',
  'js/modules/history.js',
  'js/modules/evidence.js',
  'js/modules/settings.js',
  'js/modules/organizations.js',
  'js/modules/chat.js',
  'js/modules/agents.js',
  'js/modules/audit_risk.js',
  'js/modules/theme.js',
  'js/app.js',
];

// Standalone JS bundles (e.g. pricing)
const STANDALONE_JS_MODULES = [
  {
    sources: [
      'js/modules/pricing/pricing_state.js',
      'js/modules/pricing/pricing_api.js',
      'js/modules/pricing/pricing_ui.js',
      'js/modules/pricing/pricing_checkout.js',
      'js/modules/pricing/pricing_invoices.js',
      'js/modules/pricing.js',
    ],
    dist: 'pricing.min.js',
  },
];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function computeHash(content) {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 10);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

// Fallback CSS minifier if esbuild is not available
function fallbackMinifyCss(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, '') // remove comments
    .replace(/\s+/g, ' ')             // collapse whitespace
    .replace(/\s*([{}:;,>+~])\s*/g, '$1') // remove spaces around punctuation
    .replace(/;}/g, '}')              // remove trailing semicolons
    .trim();
}

// Fallback JS minifier if esbuild is not available
function fallbackMinifyJs(js) {
  return js
    .replace(/\/\*[\s\S]*?\*\//g, '') // remove multi-line comments
    .replace(/\/\/[^\n\r]*/g, '')      // remove single-line comments
    .replace(/^\s+|\s+$/gm, '')        // trim line spaces
    .replace(/\n+/g, '\n')             // collapse empty lines
    .trim();
}

// Jinja2 safe HTML minifier
function minifyHtml(html) {
  // Strip HTML comments, but preserve Jinja2 syntax {# ... #} removal
  let minified = html.replace(/<!--(?!\[if)[\s\S]*?-->/g, '');
  minified = minified.replace(/\{#[\s\S]*?#\}/g, '');
  // Collapse spaces between tags
  minified = minified.replace(/>\s{2,}</g, '>\n<');
  return minified;
}

// Pre-compress using Gzip and Brotli
function precompress(filePath, contentBuffer) {
  try {
    const gz = zlib.gzipSync(contentBuffer, { level: 9 });
    fs.writeFileSync(`${filePath}.gz`, gz);

    const br = zlib.brotliCompressSync(contentBuffer, {
      params: {
        [zlib.constants.BROTLI_PARAM_QUALITY]: 11,
      },
    });
    fs.writeFileSync(`${filePath}.br`, br);

    return {
      gzSize: gz.length,
      brSize: br.length,
    };
  } catch (err) {
    console.warn(`[Build] Compression warning for ${path.basename(filePath)}:`, err.message);
    return { gzSize: 0, brSize: 0 };
  }
}

async function build() {
  const startTime = Date.now();
  ensureDir(DIST_STATIC);
  ensureDir(DIST_TEMPLATES);

  const manifest = {
    version: '1.0.0',
    build_timestamp: new Date().toISOString(),
    files: {},
  };

  const report = [];

  // =========================================================================
  // 1. Build CSS Bundle
  // =========================================================================
  let combinedCss = '';
  let originalCssBytes = 0;
  for (const relPath of CSS_SOURCES) {
    const fullPath = path.join(SRC_STATIC, relPath);
    if (fs.existsSync(fullPath)) {
      const content = fs.readFileSync(fullPath, 'utf8');
      originalCssBytes += Buffer.byteLength(content, 'utf8');
      combinedCss += `/* ${relPath} */\n${content}\n`;
    } else {
      console.warn(`[Build] Warning: CSS file not found: ${relPath}`);
    }
  }

  let minifiedCss = '';
  if (esbuild) {
    const result = await esbuild.transform(combinedCss, {
      loader: 'css',
      minify: true,
      legalComments: 'none',
    });
    minifiedCss = result.code;
  } else {
    minifiedCss = fallbackMinifyCss(combinedCss);
  }

  const cssHash = computeHash(minifiedCss);
  const cssOutPath = path.join(DIST_STATIC, 'bundle.min.css');
  fs.writeFileSync(cssOutPath, minifiedCss, 'utf8');

  const cssBuffer = Buffer.from(minifiedCss, 'utf8');
  const cssCompression = precompress(cssOutPath, cssBuffer);

  manifest.files['bundle.min.css'] = {
    path: '/static/dist/bundle.min.css',
    hash: cssHash,
    versioned_path: `/static/dist/bundle.min.css?v=${cssHash}`,
    original_size: originalCssBytes,
    minified_size: cssBuffer.length,
    gzip_size: cssCompression.gzSize,
    brotli_size: cssCompression.brSize,
    savings_pct: ((1 - cssBuffer.length / originalCssBytes) * 100).toFixed(1) + '%',
  };

  report.push({
    name: 'bundle.min.css',
    original: formatBytes(originalCssBytes),
    minified: formatBytes(cssBuffer.length),
    gzip: formatBytes(cssCompression.gzSize),
    brotli: formatBytes(cssCompression.brSize),
    savings: manifest.files['bundle.min.css'].savings_pct,
  });

  // =========================================================================
  // 2. Build Main JS Bundle
  // =========================================================================
  let combinedJs = '/* Production RAG Agent Main Bundle */\n';
  let originalJsBytes = 0;
  for (const relPath of JS_SOURCES) {
    const fullPath = path.join(SRC_STATIC, relPath);
    if (fs.existsSync(fullPath)) {
      const content = fs.readFileSync(fullPath, 'utf8');
      originalJsBytes += Buffer.byteLength(content, 'utf8');
      combinedJs += `\n/* --- ${relPath} --- */\n${content}\n`;
    } else {
      console.warn(`[Build] Warning: JS file not found: ${relPath}`);
    }
  }

  let minifiedJs = '';
  let jsSourceMap = '';
  if (esbuild) {
    const result = await esbuild.transform(combinedJs, {
      loader: 'js',
      minify: true,
      sourcemap: true,
      legalComments: 'none',
      target: 'es2020',
    });
    minifiedJs = result.code;
    jsSourceMap = result.map;
  } else {
    minifiedJs = fallbackMinifyJs(combinedJs);
  }

  const jsHash = computeHash(minifiedJs);
  const jsOutPath = path.join(DIST_STATIC, 'bundle.min.js');
  fs.writeFileSync(jsOutPath, minifiedJs, 'utf8');
  if (jsSourceMap) {
    fs.writeFileSync(path.join(DIST_STATIC, 'bundle.min.js.map'), jsSourceMap, 'utf8');
  }

  const jsBuffer = Buffer.from(minifiedJs, 'utf8');
  const jsCompression = precompress(jsOutPath, jsBuffer);

  manifest.files['bundle.min.js'] = {
    path: '/static/dist/bundle.min.js',
    hash: jsHash,
    versioned_path: `/static/dist/bundle.min.js?v=${jsHash}`,
    original_size: originalJsBytes,
    minified_size: jsBuffer.length,
    gzip_size: jsCompression.gzSize,
    brotli_size: jsCompression.brSize,
    savings_pct: ((1 - jsBuffer.length / originalJsBytes) * 100).toFixed(1) + '%',
  };

  report.push({
    name: 'bundle.min.js',
    original: formatBytes(originalJsBytes),
    minified: formatBytes(jsBuffer.length),
    gzip: formatBytes(jsCompression.gzSize),
    brotli: formatBytes(jsCompression.brSize),
    savings: manifest.files['bundle.min.js'].savings_pct,
  });

  // =========================================================================
  // 3. Standalone Modules (e.g. pricing.js)
  // =========================================================================
  for (const mod of STANDALONE_JS_MODULES) {
    let combinedContent = `/* Production Bundle: ${mod.dist} */\n`;
    let origBytes = 0;

    for (const relPath of mod.sources) {
      const srcPath = path.join(SRC_STATIC, relPath);
      if (fs.existsSync(srcPath)) {
        const fileContent = fs.readFileSync(srcPath, 'utf8');
        origBytes += Buffer.byteLength(fileContent, 'utf8');
        combinedContent += `\n/* --- ${relPath} --- */\n${fileContent}\n`;
      }
    }

    if (origBytes === 0) continue;

    let minCode = '';
    let mapCode = '';

    if (esbuild) {
      const result = await esbuild.transform(combinedContent, {
        loader: 'js',
        minify: true,
        sourcemap: true,
        legalComments: 'none',
        target: 'es2020',
      });
      minCode = result.code;
      mapCode = result.map;
    } else {
      minCode = fallbackMinifyJs(combinedContent);
    }

    const modHash = computeHash(minCode);
    const modOutPath = path.join(DIST_STATIC, mod.dist);
    fs.writeFileSync(modOutPath, minCode, 'utf8');
    if (mapCode) {
      fs.writeFileSync(`${modOutPath}.map`, mapCode, 'utf8');
    }

    const modBuffer = Buffer.from(minCode, 'utf8');
    const modCompression = precompress(modOutPath, modBuffer);

    manifest.files[mod.dist] = {
      path: `/static/dist/${mod.dist}`,
      hash: modHash,
      versioned_path: `/static/dist/${mod.dist}?v=${modHash}`,
      original_size: origBytes,
      minified_size: modBuffer.length,
      gzip_size: modCompression.gzSize,
      brotli_size: modCompression.brSize,
      savings_pct: ((1 - modBuffer.length / origBytes) * 100).toFixed(1) + '%',
    };

    report.push({
      name: mod.dist,
      original: formatBytes(origBytes),
      minified: formatBytes(modBuffer.length),
      gzip: formatBytes(modCompression.gzSize),
      brotli: formatBytes(modCompression.brSize),
      savings: manifest.files[mod.dist].savings_pct,
    });
  }

  // =========================================================================
  // 4. HTML Template Optimization (Jinja2 safe)
  // =========================================================================
  function processTemplatesDir(srcDir, outDir) {
    ensureDir(outDir);
    const entries = fs.readdirSync(srcDir, { withFileTypes: true });
    for (const entry of entries) {
      const srcFile = path.join(srcDir, entry.name);
      const outFile = path.join(outDir, entry.name);
      if (entry.isDirectory()) {
        processTemplatesDir(srcFile, outFile);
      } else if (entry.name.endsWith('.html')) {
        const rawHtml = fs.readFileSync(srcFile, 'utf8');
        const optHtml = minifyHtml(rawHtml);
        fs.writeFileSync(outFile, optHtml, 'utf8');
      }
    }
  }

  let origTplBytes = 0;
  let optTplBytes = 0;
  function calculateTplBytes(dir) {
    let bytes = 0;
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) bytes += calculateTplBytes(p);
      else if (entry.name.endsWith('.html')) bytes += fs.statSync(p).size;
    }
    return bytes;
  }

  origTplBytes = calculateTplBytes(SRC_TEMPLATES);
  processTemplatesDir(SRC_TEMPLATES, DIST_TEMPLATES);
  optTplBytes = calculateTplBytes(DIST_TEMPLATES);

  report.push({
    name: 'templates_dist (HTML)',
    original: formatBytes(origTplBytes),
    minified: formatBytes(optTplBytes),
    gzip: 'N/A',
    brotli: 'N/A',
    savings: ((1 - optTplBytes / origTplBytes) * 100).toFixed(1) + '%',
  });

  // Write manifest.json
  const manifestPath = path.join(DIST_STATIC, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');

  const duration = Date.now() - startTime;

  // Print Summary Table
  console.log('\n================================================================================');
  console.log('  ⚡ RAG AGENT ASSET BUILD & OPTIMIZATION PIPELINE');
  console.log('================================================================================');
  console.table(report);
  console.log(`\n  ✅ Dist output: ${path.relative(ROOT_DIR, DIST_STATIC)}`);
  console.log(`  ✅ Manifest:    ${path.relative(ROOT_DIR, manifestPath)}`);
  console.log(`  ✅ Completed in ${duration}ms\n`);
}

// Watch mode
if (process.argv.includes('--watch')) {
  console.log('👀 Watching static assets for changes...');
  await build();
  fs.watch(SRC_STATIC, { recursive: true }, async (eventType, filename) => {
    if (filename && !filename.startsWith('dist')) {
      console.log(`[Watch] File changed: ${filename}. Rebuilding...`);
      try {
        await build();
      } catch (e) {
        console.error('[Watch] Build error:', e);
      }
    }
  });
} else {
  build().catch((err) => {
    console.error('[Build Failed]', err);
    process.exit(1);
  });
}
