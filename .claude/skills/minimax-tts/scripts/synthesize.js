#!/usr/bin/env node

/**
 * MiniMax TTS 语音合成脚本
 * 支持文本转语音，可配置音色、语速、情感等参数
 * 
 * 使用 MiniMax 语音合成 API，配置从 ~/.phoenixassistantai/media_config.json 读取
 * 
 * 用法：
 *   node synthesize.js --text "你好世界" --output hello.mp3
 *   node synthesize.js --text-file ./narration.txt -v "male-qn-qingse" -o audio.mp3
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { URL } = require('url');
const os = require('os');

// ==================== 配置 ====================

// 从配置文件或环境变量读取 API Key
function getApiKey() {
  // 1. 尝试从配置文件读取
  const configPath = path.join(os.homedir(), '.phoenixassistantai', 'media_config.json');
  if (fs.existsSync(configPath)) {
    try {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      // 优先使用 minimaxTTS 配置，兼容 minimax 配置
      if (config.minimaxTTS?.apiKey) {
        return config.minimaxTTS.apiKey;
      }
      if (config.minimax?.apiKey) {
        return config.minimax.apiKey;
      }
    } catch (e) {
      // 配置文件解析失败，继续尝试其他方式
    }
  }

  // 2. 从环境变量读取
  return process.env.MINIMAX_API_KEY;
}

const API_KEY = getApiKey();
const BASE_URL = 'https://api.minimaxi.com/v1/t2a_v2';

// 默认参数
const DEFAULT_MODEL = 'speech-2.8-hd';
const DEFAULT_VOICE = 'Chinese (Mandarin)_Warm_Bestie';
const DEFAULT_SPEED = 1.0;
const DEFAULT_VOLUME = 1.0;
const DEFAULT_PITCH = 0;
const DEFAULT_FORMAT = 'mp3';
const DEFAULT_SAMPLE_RATE = 32000;
const DEFAULT_BITRATE = 128000;
const DEFAULT_CHANNEL = 1;

// ==================== 工具函数 ====================

function printError(message) {
  console.error(`错误: ${message}`);
}

function printInfo(message) {
  console.error(message);
}

function validateConfig() {
  if (!API_KEY) {
    printError('未配置 MiniMax TTS API Key');
    printInfo('');
    printInfo('='.repeat(70));
    printInfo('MiniMax TTS 语音合成配置指南');
    printInfo('='.repeat(70));
    printInfo('');
    printInfo('【方式一：创建配置文件（推荐）】');
    printInfo('  创建文件：~/.phoenixassistantai/media_config.json');
    printInfo('  内容如下：');
    printInfo('  {');
    printInfo('    "minimaxTTS": {');
    printInfo('      "enabled": true,');
    printInfo('      "apiKey": "你的API密钥"');
    printInfo('    }');
    printInfo('  }');
    printInfo('');
    printInfo('【方式二：设置环境变量】');
    printInfo('  macOS/Linux:');
    printInfo('    export MINIMAX_API_KEY="你的API密钥"');
    printInfo('');
    printInfo('  Windows PowerShell:');
    printInfo('    $env:MINIMAX_API_KEY="你的API密钥"');
    printInfo('');
    printInfo('【获取 API Key】');
    printInfo('  https://platform.minimaxi.com/user-center/basic-information/interface-key');
    printInfo('='.repeat(70));
    return false;
  }
  return true;
}

// volume 范围转换：storyboard 使用 1-10，API 使用 0.1-2.0
function normalizeVolume(value) {
  const num = parseFloat(value);
  if (isNaN(num)) return DEFAULT_VOLUME;
  // 如果值 > 2，认为是 storyboard 的 1-10 范围，转换为 0.1-2.0
  if (num > 2) {
    return Math.min(2.0, Math.max(0.1, num / 5));
  }
  return Math.min(2.0, Math.max(0.1, num));
}

// ==================== API 调用函数 ====================

function makeRequest(urlStr, headers, body) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(urlStr);

    const options = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'MiniMaxTTS/1.0',
        ...headers
      },
      timeout: 120000
    };

    const req = https.request(options, (res) => {
      // 检查是否为流式响应
      const contentType = res.headers['content-type'] || '';
      const isStream = options.streamMode || false;

      if (isStream && contentType.includes('application/octet-stream')) {
        // 流式响应 - 收集二进制数据
        const chunks = [];
        res.on('data', (chunk) => {
          chunks.push(chunk);
        });
        res.on('end', () => {
          resolve({
            status: res.statusCode,
            data: Buffer.concat(chunks),
            headers: res.headers,
            isBinary: true
          });
        });
        return;
      }

      // 非流式响应 - JSON
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
            headers: res.headers,
            isBinary: false
          });
        } catch (e) {
          resolve({
            status: res.statusCode,
            data: data,
            headers: res.headers,
            isBinary: false
          });
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('请求超时'));
    });

    req.write(JSON.stringify(body));
    req.end();
  });
}

/**
 * 语音合成核心函数
 * @param {Object} params - 合成参数
 * @returns {Object} 合成结果
 */
async function synthesize(params) {
  const {
    text,
    model = DEFAULT_MODEL,
    voice = DEFAULT_VOICE,
    speed = DEFAULT_SPEED,
    volume = DEFAULT_VOLUME,
    pitch = DEFAULT_PITCH,
    emotion,
    format = DEFAULT_FORMAT,
    sampleRate = DEFAULT_SAMPLE_RATE,
    bitrate = DEFAULT_BITRATE,
    channel = DEFAULT_CHANNEL,
    output = 'output.mp3',
    outputFormat = 'hex',
    pronunciation = [],
    languageBoost,
    subtitle = false,
    aigcWatermark = false,
    stream = false
  } = params;

  if (!text || text.trim().length === 0) {
    throw new Error('合成文本不能为空');
  }

  if (text.length > 10000) {
    throw new Error(`文本长度 ${text.length} 超过限制（最大 10000 字符）`);
  }

  // 构建请求体
  const requestBody = {
    model,
    text,
    stream
  };

  // 语音设置
  const voiceSetting = {
    voice_id: voice,
    speed: parseFloat(speed),
    vol: normalizeVolume(volume),
    pitch: parseInt(pitch, 10)
  };
  if (emotion) {
    voiceSetting.emotion = emotion;
  }
  requestBody.voice_setting = voiceSetting;

  // 音频设置
  requestBody.audio_setting = {
    sample_rate: parseInt(sampleRate, 10),
    bitrate: parseInt(bitrate, 10),
    format: format,
    channel: parseInt(channel, 10)
  };

  // 发音词典
  if (pronunciation && pronunciation.length > 0) {
    requestBody.pronunciation_dict = {
      tone: pronunciation
    };
  }

  // 语言增强
  if (languageBoost) {
    requestBody.language_boost = languageBoost;
  }

  // 字幕服务
  if (subtitle) {
    requestBody.subtitle_enable = true;
  }

  // AIGC水印
  if (aigcWatermark) {
    requestBody.aigc_watermark = true;
  }

  // 输出格式（仅非流式生效）
  if (!stream && outputFormat) {
    requestBody.output_format = outputFormat;
  }

  printInfo('正在提交语音合成请求...');
  printInfo(`  模型: ${model}`);
  printInfo(`  音色: ${voice}`);
  printInfo(`  语速: ${speed}`);
  printInfo(`  音量: ${volume}`);
  printInfo(`  音调: ${pitch}`);
  if (emotion) printInfo(`  情感: ${emotion}`);
  printInfo(`  格式: ${format}`);
  printInfo(`  采样率: ${sampleRate}`);
  printInfo(`  文本长度: ${text.length} 字符`);
  printInfo('');

  const headers = {
    'Authorization': `Bearer ${API_KEY}`
  };

  const response = await makeRequest(BASE_URL, headers, requestBody);

  if (response.status !== 200) {
    let errorMsg = `HTTP ${response.status}`;
    if (typeof response.data === 'object') {
      if (response.data.base_resp?.status_msg) {
        errorMsg = response.data.base_resp.status_msg;
      } else if (response.data.error?.message) {
        errorMsg = response.data.error.message;
      }
    }

    if (response.status === 401) {
      throw new Error('认证失败：API Key 无效或已过期\n请检查 MiniMax TTS API Key 配置');
    } else if (response.status === 429) {
      throw new Error('请求过于频繁：已超过限流配额\n请等待后重试');
    } else if (response.status === 400) {
      throw new Error(`参数错误：${errorMsg}`);
    } else {
      throw new Error(`语音合成失败：${errorMsg}`);
    }
  }

  const result = response.data;

  // 检查业务状态码
  if (result.base_resp?.status_code !== 0) {
    throw new Error(`合成失败：${result.base_resp?.status_msg || '未知错误'}`);
  }

  // 确保输出目录存在
  const outputDir = path.dirname(output);
  if (outputDir && !fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  // 处理音频数据
  if (outputFormat === 'url') {
    // URL模式 - 下载音频文件
    const audioUrl = result.data?.audio;
    if (!audioUrl) {
      throw new Error('未获取到音频URL');
    }
    printInfo('正在下载音频文件...');
    await downloadFile(audioUrl, output);
    printInfo(`音频已下载至: ${output}`);
  } else {
    // hex模式 - 解码hex数据写入文件
    const audioHex = result.data?.audio;
    if (!audioHex) {
      throw new Error('未获取到音频数据');
    }
    const audioBuffer = Buffer.from(audioHex, 'hex');
    fs.writeFileSync(output, audioBuffer);
    printInfo(`音频已保存至: ${output}`);
  }

  // 构建返回结果
  const extraInfo = result.extra_info || {};
  const returnResult = {
    filePath: path.resolve(output),
    audioLength: extraInfo.audio_length ? extraInfo.audio_length / 1000 : null, // ms -> s
    sampleRate: extraInfo.audio_sample_rate,
    bitrate: extraInfo.bitrate,
    format: extraInfo.audio_format,
    channel: extraInfo.audio_channel,
    usageCharacters: extraInfo.usage_characters,
    wordCount: extraInfo.word_count,
    traceId: result.trace_id
  };

  return returnResult;
}

// 下载文件
function downloadFile(urlStr, outputPath) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(urlStr);

    const options = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: 'GET',
      headers: {
        'User-Agent': 'MiniMaxTTS/1.0'
      },
      timeout: 120000
    };

    const req = https.request(options, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        // 处理重定向
        downloadFile(res.headers.location, outputPath).then(resolve).catch(reject);
        return;
      }

      if (res.statusCode !== 200) {
        reject(new Error(`下载失败 (HTTP ${res.statusCode})`));
        return;
      }

      const dir = path.dirname(outputPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      const file = fs.createWriteStream(outputPath);
      res.pipe(file);

      file.on('finish', () => {
        file.close();
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

// ==================== 命令行参数解析 ====================

function parseArgs(args) {
  const options = {
    text: null,
    'text-file': null,
    model: DEFAULT_MODEL,
    voice: DEFAULT_VOICE,
    speed: DEFAULT_SPEED,
    volume: DEFAULT_VOLUME,
    pitch: DEFAULT_PITCH,
    emotion: null,
    format: DEFAULT_FORMAT,
    'sample-rate': DEFAULT_SAMPLE_RATE,
    bitrate: DEFAULT_BITRATE,
    channel: DEFAULT_CHANNEL,
    output: `output.${DEFAULT_FORMAT}`,
    'output-format': 'hex',
    pronunciation: [],
    'language-boost': null,
    subtitle: false,
    'aigc-watermark': false,
    stream: false
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.substring(2);
      
      if (key === 'subtitle' || key === 'aigc-watermark' || key === 'stream') {
        options[key] = true;
      } else if (key === 'pronunciation') {
        if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
          options.pronunciation.push(args[++i]);
        }
      } else if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        const value = args[++i];
        
        // 短参数别名
        if (key === 'v') {
          options.voice = value;
        } else if (key === 'o') {
          options.output = value;
        } else if (key === 'f') {
          options.format = value;
        } else {
          options[key] = value;
        }
      }
    }
  }

  return options;
}

// ==================== 主函数 ====================

async function main() {
  const args = process.argv.slice(2);
  const options = parseArgs(args);

  // 验证必需参数
  if (!options.text && !options['text-file']) {
    printError('缺少必需参数: --text 或 --text-file');
    printInfo('');
    printInfo('用法:');
    printInfo('  node synthesize.js --text "你好世界" --output hello.mp3');
    printInfo('  node synthesize.js --text-file ./narration.txt -v "male-qn-qingse" -o audio.mp3');
    process.exit(1);
  }

  // 验证配置
  if (!validateConfig()) {
    process.exit(1);
  }

  // 读取文本
  let text = options.text;
  if (!text && options['text-file']) {
    const textFilePath = path.resolve(options['text-file']);
    if (!fs.existsSync(textFilePath)) {
      printError(`文本文件不存在: ${textFilePath}`);
      process.exit(1);
    }
    text = fs.readFileSync(textFilePath, 'utf-8').trim();
    if (!text) {
      printError(`文本文件内容为空: ${textFilePath}`);
      process.exit(1);
    }
  }

  // 根据format调整默认output扩展名
  if (!args.includes('--output') && !args.includes('-o')) {
    options.output = `output.${options.format}`;
  }

  // 执行合成
  try {
    printInfo('='.repeat(50));
    printInfo('MiniMax TTS 语音合成');
    printInfo('='.repeat(50));
    printInfo('');

    const result = await synthesize({
      text,
      model: options.model,
      voice: options.voice,
      speed: options.speed,
      volume: options.volume,
      pitch: options.pitch,
      emotion: options.emotion,
      format: options.format,
      sampleRate: options['sample-rate'],
      bitrate: options.bitrate,
      channel: options.channel,
      output: options.output,
      outputFormat: options['output-format'],
      pronunciation: options.pronunciation,
      languageBoost: options['language-boost'],
      subtitle: options.subtitle,
      aigcWatermark: options['aigc-watermark'],
      stream: options.stream
    });

    printInfo('');
    printInfo('='.repeat(50));
    printInfo('✅ 语音合成成功！');
    printInfo('='.repeat(50));

    // 标准输出（供程序化调用解析）
    console.log(JSON.stringify({
      success: true,
      filePath: result.filePath,
      audioLength: result.audioLength,
      sampleRate: result.sampleRate,
      bitrate: result.bitrate,
      format: result.format,
      channel: result.channel,
      usageCharacters: result.usageCharacters,
      wordCount: result.wordCount,
      traceId: result.traceId
    }, null, 2));

  } catch (error) {
    printError(error.message);
    process.exit(1);
  }
}

// 导出 synthesize 函数供模块化调用
module.exports = { synthesize };

// 命令行直接运行时执行主函数
if (require.main === module) {
  main();
}
