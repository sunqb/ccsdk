#!/usr/bin/env node

/**
 * Seedream 5.0 图片生成脚本
 * 支持文本生成图片（T2I）、图片编辑（I2I）、多图融合、组图生成、联网搜索增强
 * 
 * 基于火山引擎 Seedream 5.0 lite 模型
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
    } catch (e) {
      // 配置文件解析失败，继续尝试其他方式
    }
  }
  
  // 2. 从环境变量读取
  return process.env.ARK_API_KEY || process.env.SEEDREAM5_API_KEY;
}

const API_KEY = getApiKey();
const BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3';

// 默认参数 - Seedream 5.0 lite
const DEFAULT_MODEL = 'doubao-seedream-5-0-260128';
const DEFAULT_SIZE = '2K';

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
        'User-Agent': 'Seedream5ImageGenerator/1.0',
        ...headers
      },
      timeout: 180000 // 3分钟超时，因为5.0可能需要更长时间
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
        'User-Agent': 'Seedream5ImageGenerator/1.0'
      },
      timeout: 120000
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

async function generateImage(prompt, imagePaths = null, options = {}) {
  const {
    model = DEFAULT_MODEL,
    size = DEFAULT_SIZE,
    watermark = true,
    sequential = false,
    maxImages = 15,
    enableSearch = false,
    outputFormat = 'jpeg',
    negativePrompt = null
  } = options;

  // 构建请求payload
  const payload = {
    model,
    prompt,
    size,
    response_format: 'url',
    watermark,
    output_format: outputFormat
  };

  // 添加负向提示词
  if (negativePrompt) {
    payload.negative_prompt = negativePrompt;
  }

  // 添加图片
  if (imagePaths && imagePaths.length > 0) {
    if (imagePaths.length === 1) {
      try {
        const processedUrl = await processImagePath(imagePaths[0]);
        payload.image = processedUrl;
      } catch (e) {
        throw new Error(`图片处理失败: ${e.message}`);
      }
    } else {
      try {
        const processedUrls = [];
        for (const img of imagePaths) {
          processedUrls.push(await processImagePath(img));
        }
        payload.image = processedUrls;
        // 多图输入时默认关闭组图功能
        if (!sequential) {
          payload.sequential_image_generation = 'disabled';
        }
      } catch (e) {
        throw new Error(`图片处理失败: ${e.message}`);
      }
    }
  }

  // 组图生成
  if (sequential) {
    payload.sequential_image_generation = 'auto';
    payload.sequential_image_generation_options = { max_images: maxImages };
  }

  // 联网搜索 - Seedream 5.0 lite 特有功能
  if (enableSearch) {
    payload.tools = [{ type: 'web_search' }];
  }

  printInfo('正在生成图片...');
  printInfo(`  模型: ${payload.model}`);
  printInfo(`  尺寸: ${size}`);
  printInfo(`  输出格式: ${outputFormat.toUpperCase()}`);
  if (payload.negative_prompt) {
    printInfo(`  负向提示词: ${payload.negative_prompt.substring(0, 100)}${payload.negative_prompt.length > 100 ? '...' : ''}`);
  }
  if (imagePaths && imagePaths.length > 0) {
    printInfo(`  参考图片: ${imagePaths.length}张`);
    imagePaths.forEach((img, i) => {
      if (img.startsWith('file://')) {
        printInfo(`    [${i + 1}] 本地文件: ${img.substring(7)}`);
      } else if (!img.startsWith(('http://', 'https://', 'data:'))) {
        printInfo(`    [${i + 1}] 本地文件: ${img}`);
      } else {
        const displayUrl = img.length > 80 ? img.substring(0, 80) + '...' : img;
        printInfo(`    [${i + 1}] ${displayUrl}`);
      }
    });
  }
  if (sequential) {
    printInfo(`  组图数量: 最多${maxImages}张`);
  }
  if (enableSearch) {
    printInfo('  联网搜索: 启用');
  }
  printInfo('  (Seedream 5.0 通常需要 30-90 秒，请稍候...)');
  printInfo('');

  try {
    const response = await makeRequest(
      'POST',
      `${BASE_URL}/images/generations`,
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
        throw new Error('认证失败：API Key 无效或已过期\n请检查 Seedream 5.0 API Key 配置');
      } else if (response.status === 403) {
        throw new Error('权限不足：请确认 API Key 有图片生成权限');
      } else if (response.status === 429) {
        throw new Error('请求过于频繁：已超过限流配额\n请等待1分钟后重试');
      } else if (response.status === 400) {
        throw new Error(`参数错误：${errorMsg}\n请检查提示词和参数设置`);
      } else {
        throw new Error(`生成失败：${errorMsg}`);
      }
    }

    return response.data;
  } catch (e) {
    if (e.message.includes('生成失败') || e.message.includes('认证失败')) {
      throw e;
    }
    throw new Error(`生成失败：${e.message}`);
  }
}

// ==================== 主函数 ====================

async function main() {
  const args = process.argv.slice(2);
  const options = {
    prompt: null,
    'negative-prompt': null,
    image: [],
    model: DEFAULT_MODEL,
    size: DEFAULT_SIZE,
    'no-watermark': false,
    sequential: false,
    'max-images': 15,
    search: false,
    format: 'jpeg',
    output: 'generated_image.jpg'
  };

  // 解析命令行参数
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.substring(2);
      if (key === 'no-watermark' || key === 'sequential' || key === 'search') {
        options[key] = true;
      } else if (key === 'negative-prompt') {
        options[key] = args[++i];
      } else if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        const value = args[++i];
        if (key === 'image') {
          options.image.push(value);
        } else if (key === 'max-images') {
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

  // 验证参数
  if (options.sequential && options['max-images'] < 1) {
    printError('max-images 必须大于 0');
    process.exit(1);
  }

  // 验证 format 参数
  if (!['jpeg', 'png'].includes(options.format)) {
    printError('format 必须是 jpeg 或 png');
    process.exit(1);
  }

  // 根据格式调整输出文件扩展名
  if (options.format === 'png' && options.output.endsWith('.jpg')) {
    options.output = options.output.replace(/\.jpg$/, '.png');
  } else if (options.format === 'jpeg' && options.output.endsWith('.png')) {
    options.output = options.output.replace(/\.png$/, '.jpg');
  }

  // 执行生成流程
  try {
    printInfo('='.repeat(50));
    printInfo('Seedream 5.0 图片生成');
    printInfo('='.repeat(50));
    printInfo('');

    // 生成图片
    const result = await generateImage(
      options.prompt,
      options.image.length > 0 ? options.image : null,
      {
        model: options.model,
        size: options.size,
        watermark: !options['no-watermark'],
        sequential: options.sequential,
        maxImages: options['max-images'],
        enableSearch: options.search,
        outputFormat: options.format,
        negativePrompt: options['negative-prompt']
      }
    );

    // 下载图片
    const data = result.data || [];

    if (!data || data.length === 0) {
      throw new Error('API 返回格式错误：缺少 data');
    }

    printInfo('');

    // 处理单图或组图
    if (data.length === 1) {
      // 单张图片
      const imageUrl = data[0].url;
      if (!imageUrl) {
        throw new Error('API 返回格式错误：缺少 url');
      }

      printInfo('正在下载图片...');
      await downloadFile(imageUrl, options.output);

      // 输出成功信息到 stdout（供 Claude 读取）
      printInfo('');
      printInfo('='.repeat(50));
      printInfo('✓ 生成成功！');
      printInfo('='.repeat(50));

      console.log('图片生成成功！');
      console.log(`文件路径: ${path.resolve(options.output)}`);
      console.log(`尺寸: ${data[0].size || 'N/A'}`);
      if (result.usage) {
        console.log(`生成图片数: ${result.usage.generated_images || 1}`);
        if (result.usage.tool_usage?.web_search) {
          console.log(`联网搜索: 已使用`);
        }
      }
    } else {
      // 多张图片（组图）
      const outputBase = path.parse(options.output);
      const stem = outputBase.name;
      const suffix = outputBase.ext;
      const parent = path.dirname(options.output);

      for (let i = 0; i < data.length; i++) {
        const imageUrl = data[i].url;
        if (!imageUrl) {
          printError(`图片 ${i + 1} 缺少 URL，跳过`);
          continue;
        }

        // 生成文件名：image_1.jpg, image_2.jpg, ...
        const outputPath = path.join(parent, `${stem}_${i + 1}${suffix}`);
        printInfo(`正在下载图片 ${i + 1}/${data.length}...`);
        await downloadFile(imageUrl, outputPath);
        printInfo(`  已保存: ${outputPath}`);
      }

      printInfo('');
      printInfo('='.repeat(50));
      printInfo(`✓ 组图生成成功！共 ${data.length} 张图片`);
      printInfo('='.repeat(50));

      console.log(`组图生成成功！共 ${data.length} 张图片`);
      console.log(`保存目录: ${path.resolve(parent)}`);
      if (result.usage) {
        console.log(`生成图片数: ${result.usage.generated_images || data.length}`);
      }
    }
  } catch (error) {
    printError(error.message);
    process.exit(1);
  }
}

main();