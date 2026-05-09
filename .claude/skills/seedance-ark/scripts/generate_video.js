#!/usr/bin/env node

/**
 * Seedance Volc 视频生成脚本
 * 支持文本生成视频（T2V）、图片生成视频（I2V）、音画同步视频生成
 * 
 * 使用火山引擎 Seedance 模型，配置从 ~/.phoenixassistantai/media_config.json 读取
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { URL } = require('url');
const os = require('os');

// ==================== 配置 ====================

// 从配置文件或环境变量读取 API Key
function getApiKey() {
  // 1. 尝试从配置文件读取（火山方舟统一配置）
  const configPath = path.join(os.homedir(), '.phoenixassistantai', 'media_config.json');
  if (fs.existsSync(configPath)) {
    try {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      // 优先使用火山方舟统一配置
      if (config.volcengineArk?.apiKey) {
        return config.volcengineArk.apiKey;
      }
      // 兼容旧配置
      if (config.seedanceVolc?.apiKey) {
        return config.seedanceVolc.apiKey;
      }
    } catch (e) {
      // 配置文件解析失败，继续尝试其他方式
    }
  }
  
  // 2. 从环境变量读取
  return process.env.ARK_API_KEY || process.env.SEEDANCE_API_KEY;
}

const API_KEY = getApiKey();
const BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3';

// 默认参数
const DEFAULT_MODEL = 'doubao-seedance-1-5-pro-251215';
const DEFAULT_DURATION = 5;
const DEFAULT_RATIO = 'adaptive';
const DEFAULT_POLL_INTERVAL = 5;
const DEFAULT_TIMEOUT = 300;

// ==================== 工具函数 ====================

function printError(message) {
  console.error(`错误: ${message}`);
}

function printInfo(message, noNewline = false) {
  if (noNewline) {
    process.stderr.write(message);
  } else {
    console.error(message);
  }
}

function validateConfig() {
  if (!API_KEY) {
    printError('未配置火山方舟 API Key');
    printInfo('');
    printInfo('='.repeat(70));
    printInfo('火山方舟媒体生成服务配置指南');
    printInfo('='.repeat(70));
    printInfo('');
    printInfo('【方式一：在应用中配置（推荐）】');
    printInfo('  在 智灵助手 设置中找到「媒体生成」部分，');
    printInfo('  开启「火山方舟」并配置 API Key');
    printInfo('  该 Key 同时支持 Seedream 图片生成和 Seedance 视频生成');
    printInfo('');
    printInfo('【方式二：创建配置文件】');
    printInfo('  创建文件：~/.phoenixassistantai/media_config.json');
    printInfo('  内容如下：');
    printInfo('  {');
    printInfo('    "volcengineArk": {');
    printInfo('      "enabled": true,');
    printInfo('      "apiKey": "你的API密钥"');
    printInfo('    }');
    printInfo('  }');
    printInfo('');
    printInfo('【方式三：设置环境变量】');
    printInfo('  macOS/Linux:');
    printInfo('    export ARK_API_KEY="你的API密钥"');
    printInfo('');
    printInfo('  Windows PowerShell:');
    printInfo('    $env:ARK_API_KEY="你的API密钥"');
    printInfo('');
    printInfo('【获取 API Key】');
    printInfo('  https://console.volcengine.com/ark/region:ark+cn-beijing/apikey');
    printInfo('='.repeat(70));
    return false;
  }
  return true;
}

function validateDuration(duration, model) {
  if (model.includes('2-0') || model.includes('2.0')) {
    // Seedance 2.0: 4-15秒
    if (duration < 4 || duration > 15) {
      printError(`模型 ${model} 的 duration 必须在 4-15 秒之间`);
      return false;
    }
  } else if (model.includes('1-5-pro')) {
    // Seedance 1.5: 4-12秒
    if (duration < 4 || duration > 12) {
      printError(`模型 ${model} 的 duration 必须在 4-12 秒之间`);
      return false;
    }
  } else {
    // Seedance 1.0: 2-12秒
    if (duration < 2 || duration > 12) {
      printError(`模型 ${model} 的 duration 必须在 2-12 秒之间`);
      return false;
    }
  }
  return true;
}

// ==================== API 调用函数 ====================

function getMimeType(ext) {
  const extToMime = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff',
    '.heic': 'image/heic'
  };
  return extToMime[ext.toLowerCase()] || 'image/jpeg';
}

async function processImagePath(imagePath) {
  // 如果是HTTP/HTTPS URL，直接返回
  if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
    return imagePath;
  }

  // 如果已经是data URL，直接返回
  if (imagePath.startsWith('data:')) {
    return imagePath;
  }

  // 处理file://协议
  let filePath = imagePath;
  if (filePath.startsWith('file://')) {
    filePath = filePath.substring(7);
  }

  // 否则当作本地文件处理
  const absPath = path.resolve(filePath);

  // 检查文件是否存在
  if (!fs.existsSync(absPath)) {
    throw new Error(`图片文件不存在: ${absPath}`);
  }

  const stat = fs.statSync(absPath);
  if (!stat.isFile()) {
    throw new Error(`路径不是文件: ${absPath}`);
  }

  // 检查文件扩展名
  const ext = path.extname(absPath);
  const mimeType = getMimeType(ext);

  // 读取文件并转换为Base64
  const imageData = fs.readFileSync(absPath);
  const base64Data = imageData.toString('base64');

  return `data:${mimeType};base64,${base64Data}`;
}

async function makeRequest(method, urlStr, headers, body = null) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(urlStr);
    const isHttps = urlObj.protocol === 'https:';
    const client = isHttps ? https : http;

    const options = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: method,
      headers: {
        'User-Agent': 'SeedanceVolcVideoGenerator/1.0',
        ...headers
      },
      timeout: 120000
    };

    const req = client.request(options, (res) => {
      let data = '';

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          resolve({
            status: res.statusCode,
            data: result,
            headers: res.headers
          });
        } catch (e) {
          resolve({
            status: res.statusCode,
            data: data,
            headers: res.headers
          });
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('请求超时'));
    });

    if (body) {
      req.write(JSON.stringify(body));
    }

    req.end();
  });
}

async function downloadFile(urlStr, outputPath) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(urlStr);
    const isHttps = urlObj.protocol === 'https:';
    const client = isHttps ? https : http;

    const options = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: 'GET',
      headers: {
        'User-Agent': 'SeedanceVolcVideoGenerator/1.0'
      },
      timeout: 300000
    };

    const req = client.request(options, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`下载失败 (HTTP ${res.statusCode})`));
        return;
      }

      const totalSize = parseInt(res.headers['content-length'] || '0', 10);
      let downloaded = 0;

      const dir = path.dirname(outputPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      const file = fs.createWriteStream(outputPath);

      res.on('data', (chunk) => {
        downloaded += chunk.length;
        if (totalSize > 0) {
          const percent = Math.floor((downloaded * 100) / totalSize);
          const mbDownloaded = (downloaded / (1024 * 1024)).toFixed(1);
          const mbTotal = (totalSize / (1024 * 1024)).toFixed(1);
          printInfo(`\r  进度: ${percent}% (${mbDownloaded}/${mbTotal} MB)`, true);
        }
      });

      res.pipe(file);

      file.on('finish', () => {
        file.close();
        printInfo('');
        resolve();
      });

      file.on('error', (err) => {
        fs.unlink(outputPath, () => {});
        reject(err);
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('下载超时'));
    });

    req.end();
  });
}

async function submitVideoTask(prompt, imagePaths = null, options = {}) {
  const {
    model = DEFAULT_MODEL,
    duration = DEFAULT_DURATION,
    ratio = DEFAULT_RATIO,
    audio = false,
    noWatermark = false,
    seed = null,
    resolution = null,
    returnLastFrame = false,
    webSearch = false
  } = options;

  // 判断是否为 2.0 模型
  const is2x = model.includes('2-0') || model.includes('2.0');

  // 构建content数组
  const content = [{ type: 'text', text: prompt }];

  // 添加图片
  if (imagePaths && imagePaths.length > 0) {
    for (const img of imagePaths) {
      const processedUrl = await processImagePath(img);
      content.push({
        type: 'image_url',
        image_url: { url: processedUrl }
      });
    }
  }

  // 构建请求payload
  const payload = {
    model,
    content,
    duration,
    ratio
  };

  // 各版本通用可选参数
  if (audio) payload.generate_audio = true;
  // 2.0 默认无水印，1.x 需显式传 watermark
  if (is2x) {
    if (noWatermark === false) {
      // 2.0 默认无水印，只有明确要求水印时才传
      // 实际上 2.0 的 watermark 默认为 false
    }
  } else {
    payload.watermark = !noWatermark;
  }

  // Seedance 2.0 专属参数
  if (is2x) {
    if (seed !== null && seed !== undefined) payload.seed = seed;
    if (resolution) payload.resolution = resolution;
    if (returnLastFrame) payload.return_last_frame = true;
    if (webSearch) payload.web_search = true;
  }

  printInfo('正在提交视频生成任务...');
  printInfo(`  模型: ${model}`);
  printInfo(`  时长: ${duration}秒`);
  printInfo(`  宽高比: ${ratio}`);
  if (imagePaths && imagePaths.length > 0) {
    printInfo(`  参考图片: 1张`);
  }
  if (audio) {
    printInfo('  音画同步: 启用');
  }
  if (is2x) {
    if (seed !== null && seed !== undefined) printInfo(`  随机种子: ${seed}`);
    if (resolution) printInfo(`  分辨率: ${resolution}`);
    if (returnLastFrame) printInfo('  尾帧返回: 启用');
    if (webSearch) printInfo('  联网搜索: 启用');
  }
  if (!noWatermark && !is2x) {
    printInfo('  水印: 默认添加');
  }
  printInfo('');

  const response = await makeRequest(
    'POST',
    `${BASE_URL}/contents/generations/tasks`,
    {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${API_KEY}`
    },
    payload
  );

  if (response.status !== 200) {
    let errorMsg = `HTTP ${response.status}`;
    if (typeof response.data === 'object' && response.data.error) {
      const errorDetail = response.data.error;
      errorMsg = typeof errorDetail === 'object'
        ? errorDetail.message || errorMsg
        : String(errorDetail);
    }

    if (response.status === 401) {
      throw new Error('认证失败：API Key 无效或已过期\n请检查 Seedance Volc API Key 配置');
    } else if (response.status === 403) {
      throw new Error('权限不足：请确认 API Key 有视频生成权限');
    } else if (response.status === 429) {
      throw new Error('请求过于频繁：已超过限流配额\n请等待1分钟后重试');
    } else if (response.status === 400) {
      throw new Error(`参数错误：${errorMsg}\n请检查提示词和参数设置`);
    } else {
      throw new Error(`任务提交失败：${errorMsg}`);
    }
  }

  return response.data;
}

async function pollTaskStatus(taskId, options = {}) {
  const {
    pollInterval = DEFAULT_POLL_INTERVAL,
    timeout = DEFAULT_TIMEOUT
  } = options;

  const startTime = Date.now();
  let lastStatus = '';

  while (true) {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    
    if (elapsed > timeout) {
      throw new Error('任务超时，请稍后重试');
    }

    await new Promise(resolve => setTimeout(resolve, pollInterval * 1000));

    const response = await makeRequest(
      'GET',
      `${BASE_URL}/contents/generations/tasks/${taskId}`,
      {
        'Authorization': `Bearer ${API_KEY}`
      }
    );

    if (response.status !== 200) {
      throw new Error(`查询任务失败: HTTP ${response.status}`);
    }

    const result = response.data;
    const status = result.status;

    if (status !== lastStatus) {
      lastStatus = status;
      printInfo(`  [${elapsed}秒] 状态: ${getStatusText(status)}`);
    }

    if (status === 'succeeded') {
      return result;
    } else if (status === 'failed') {
      const errorMsg = result.error?.message || '未知错误';
      throw new Error(`任务失败: ${errorMsg}`);
    }
  }
}

function getStatusText(status) {
  const statusMap = {
    'queued': '排队中',
    'running': '生成中...',
    'succeeded': '完成',
    'failed': '失败'
  };
  return statusMap[status] || status;
}

// ==================== 主函数 ====================

async function main() {
  const args = process.argv.slice(2);
  const options = {
    prompt: null,
    image: null,
    model: DEFAULT_MODEL,
    duration: DEFAULT_DURATION,
    ratio: DEFAULT_RATIO,
    audio: false,
    'no-watermark': false,
    'poll-interval': DEFAULT_POLL_INTERVAL,
    timeout: DEFAULT_TIMEOUT,
    output: 'generated_video.mp4',
    seed: null,
    resolution: null,
    'return-last-frame': false,
    'web-search': false
  };

  // 解析命令行参数
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.substring(2);
      // 布尔标志参数（不需要值）
      if (key === 'audio' || key === 'no-watermark' || key === 'return-last-frame' || key === 'web-search') {
        options[key] = true;
      } else if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        const value = args[++i];
        if (key === 'image' || key === 'resolution') {
          options[key] = value;
        } else if (key === 'duration' || key === 'poll-interval' || key === 'timeout' || key === 'seed') {
          options[key] = parseInt(value, 10);
        } else {
          options[key] = value;
        }
      }
    }
  }

  // 验证必需参数
  if (!options.prompt) {
    printError('缺少必需参数: --prompt');
    process.exit(1);
  }

  // 验证配置
  if (!validateConfig()) {
    process.exit(1);
  }

  // 验证时长
  if (!validateDuration(options.duration, options.model)) {
    process.exit(1);
  }

  // 执行生成流程
  try {
    printInfo('='.repeat(50));
    printInfo('Seedance Volc 视频生成');
    printInfo('='.repeat(50));
    printInfo('');

    // 提交任务
    const submitResult = await submitVideoTask(
      options.prompt,
      options.image ? [options.image] : null,
      {
        model: options.model,
        duration: options.duration,
        ratio: options.ratio,
        audio: options.audio,
        noWatermark: options['no-watermark'],
        seed: options.seed,
        resolution: options.resolution,
        returnLastFrame: options['return-last-frame'],
        webSearch: options['web-search']
      }
    );

    const taskId = submitResult.id;
    if (!taskId) {
      throw new Error('任务提交失败：未返回任务ID');
    }

    printInfo(`任务已提交，任务ID: ${taskId}`);
    printInfo('');

    // 轮询任务状态
    printInfo('正在生成视频，请耐心等待...');
    printInfo('(视频生成通常需要 1-5 分钟，取决于时长和服务器负载)');
    printInfo('');

    const result = await pollTaskStatus(taskId, {
      pollInterval: options['poll-interval'],
      timeout: options.timeout
    });

    // 获取视频URL
    const videoUrl = result.content?.video_url;
    if (!videoUrl) {
      throw new Error('任务完成但未返回视频URL');
    }

    // 下载视频
    printInfo('');
    printInfo('正在下载视频...');
    await downloadFile(videoUrl, options.output);

    // 输出成功信息
    printInfo('');
    printInfo('='.repeat(50));
    printInfo('生成成功！');
    printInfo('='.repeat(50));

    console.log('视频生成成功！');
    console.log(`任务ID: ${taskId}`);
    console.log(`文件路径: ${path.resolve(options.output)}`);
    console.log(`分辨率: ${result.resolution || 'N/A'}`);
    console.log(`宽高比: ${result.ratio || 'N/A'}`);
    console.log(`时长: ${result.duration || 'N/A'}秒`);
    console.log(`帧率: ${result.framespersecond || 'N/A'} fps`);

    if (result.content?.has_audio) {
      console.log('音频: 已包含');
    }

  } catch (error) {
    printError(error.message);
    process.exit(1);
  }
}

main();