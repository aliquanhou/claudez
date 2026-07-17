#!/usr/bin/env node

/**
 * ClaudeZ CLI 入口 — 检测原生 Harness 二进制并启动。
 *
 * 流程：
 *   1. 检测平台对应的原生 Harness 二进制
 *   2. 如果存在 → 启动原生二进制（子进程）
 *   3. 如果不存在 → 回退到 python main.py
 */

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

// ── 平台检测 ──

function getPlatform() {
  const type = os.type();
  const arch = os.arch();

  if (type === 'Windows_NT' && arch === 'x64') return 'win32-x64';
  if (type === 'Darwin' && arch === 'arm64') return 'darwin-arm64';
  if (type === 'Darwin' && arch === 'x64') return 'darwin-arm64'; // Rosetta
  if (type === 'Linux' && arch === 'x64') return 'linux-x64';
  if (type === 'Linux' && arch === 'arm64') return 'linux-x64';   // 回退

  return null;
}

// ── 查找 Harness 二进制 ──

function findHarnessBinary() {
  const platform = getPlatform();
  if (!platform) return null;

  const binaryName = platform.startsWith('win') ? 'claudez.exe' : 'claudez';

  // 1. 检查 @claudez/harness-{platform} 包
  try {
    const pkgPath = path.join(__dirname, '..', '..', `@claudez/harness-${platform}`);
    const binaryPath = path.join(pkgPath, 'bin', binaryName);
    if (fs.existsSync(binaryPath)) return binaryPath;
  } catch (e) { /* ignore */ }

  // 2. 检查 node_modules
  try {
    const pkgPath = path.join(__dirname, '..', '..', '..', `@claudez/harness-${platform}`);
    const binaryPath = path.join(pkgPath, 'bin', binaryName);
    if (fs.existsSync(binaryPath)) return binaryPath;
  } catch (e) { /* ignore */ }

  // 3. 检查项目根目录
  const projectRoot = path.join(__dirname, '..', '..', '..');
  const binaryPath = path.join(projectRoot, 'bin', binaryName);
  if (fs.existsSync(binaryPath)) return binaryPath;

  return null;
}

// ── 查找 Python 核心 ──

function findPythonCore() {
  const searchPaths = [
    path.join(__dirname, '..', '..', '..', 'main.py'),
    path.join(__dirname, '..', '..', 'main.py'),
    path.join(process.cwd(), 'main.py'),
  ];

  for (const p of searchPaths) {
    if (fs.existsSync(p)) return p;
  }

  return null;
}

// ── 主逻辑 ──

async function main() {
  const args = process.argv.slice(2);
  const harnessBinary = findHarnessBinary();
  const pythonCore = findPythonCore();

  if (harnessBinary) {
    // 启动原生 Harness
    console.error(`[ClaudeZ] 启动原生 Harness: ${harnessBinary}`);
    const child = spawn(harnessBinary, args, {
      stdio: 'inherit',
      env: { ...process.env },
    });

    child.on('exit', (code) => {
      process.exit(code || 0);
    });
  } else if (pythonCore) {
    // 回退到 Python 模式
    console.error('[ClaudeZ] 未检测到原生 Harness，回退到 Python 模式');

    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
    const child = spawn(pythonCmd, [pythonCore, ...args], {
      stdio: 'inherit',
      env: { ...process.env },
    });

    child.on('exit', (code) => {
      process.exit(code || 0);
    });
  } else {
    console.error('[ClaudeZ] 错误: 找不到 ClaudeZ 核心文件');
    console.error('请确保在 ClaudeZ 项目目录中运行');
    console.error('');
    console.error('安装方式:');
    console.error('  npm install -g @claudez/cli        # 全局安装（含原生 Harness）');
    console.error('  pip install claudez                 # Python 模式安装');
    process.exit(1);
  }
}

main().catch(console.error);
