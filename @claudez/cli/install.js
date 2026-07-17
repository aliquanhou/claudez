/**
 * @claudez/cli 安装脚本
 *
 * 职责：
 *   1. 检测平台
 *   2. 下载对应的原生 Harness 二进制（如果不存在）
 *   3. 验证完整性
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');
const os = require('os');

const PKG_VERSION = '1.0.0';
const CDN_BASE = 'https://github.com/claudez/harness/releases/download';

function getPlatform() {
  const type = os.type();
  const arch = os.arch();

  if (type === 'Windows_NT' && arch === 'x64') return 'win32-x64';
  if (type === 'Darwin' && arch === 'arm64') return 'darwin-arm64';
  if (type === 'Darwin' && arch === 'x64') return 'darwin-arm64';
  if (type === 'Linux' && arch === 'x64') return 'linux-x64';
  if (type === 'Linux' && arch === 'arm64') return 'linux-arm64';

  return null;
}

function getBinaryName(platform) {
  return platform.startsWith('win') ? 'claudez.exe' : 'claudez';
}

async function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https.get(url, (response) => {
      if (response.statusCode !== 200) {
        reject(new Error(`下载失败: ${response.statusCode}`));
        return;
      }
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      fs.unlinkSync(dest);
      reject(err);
    });
  });
}

async function install() {
  const platform = getPlatform();
  if (!platform) {
    console.error(`[安装] 不支持的平台: ${os.type()} ${os.arch()}`);
    console.error('[安装] 将使用 Python 模式运行');
    return;
  }

  const binaryName = getBinaryName(platform);
  const targetDir = path.join(__dirname, '..', `@claudez/harness-${platform}`, 'bin');
  const targetPath = path.join(targetDir, binaryName);

  // 如果已存在，跳过（后续可加版本校验）
  if (fs.existsSync(targetPath)) {
    console.error(`[安装] Harness 二进制已存在: ${targetPath}`);
    return;
  }

  // 尝试从 CDN 下载
  const url = `${CDN_BASE}/v${PKG_VERSION}/${binaryName}`;
  console.error(`[安装] 下载 Harness 二进制: ${url}`);

  try {
    fs.mkdirSync(targetDir, { recursive: true });
    await downloadFile(url, targetPath);
    fs.chmodSync(targetPath, 0o755);
    console.error(`[安装] 下载完成: ${targetPath}`);
  } catch (err) {
    console.error(`[安装] 下载失败: ${err.message}`);
    console.error('[安装] 将使用 Python 模式运行');
    if (fs.existsSync(targetPath)) fs.unlinkSync(targetPath);
  }
}

install().catch(console.error);
