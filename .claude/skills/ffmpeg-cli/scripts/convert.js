#!/usr/bin/env node
/**
 * OP5 - 格式转换
 * 
 * Usage:
 *   node convert.js --input input.avi --output output.mp4 [--video-codec libx264] [--audio-codec aac] [--crf 23] [--preset medium] [--fps 30] [--copy-all false]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { getFFmpegPath } = require('./merge_av');

async function convert(options) {
  const { input, output, videoCodec = 'libx264', audioCodec = 'aac', crf = 23, preset = 'medium', fps, copyAll = false } = options;
  const ffmpeg = getFFmpegPath();

  if (!fs.existsSync(input)) throw new Error(`Input file not found: ${input}`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let cmd;
  if (copyAll) {
    cmd = `"${ffmpeg}" -y -i "${input}" -c copy "${output}"`;
  } else {
    let parts = [`"${ffmpeg}" -y -i "${input}"`];
    parts.push(`-c:v ${videoCodec}`);
    if (videoCodec !== 'copy') {
      parts.push(`-crf ${crf}`);
      parts.push(`-preset ${preset}`);
    }
    parts.push(`-c:a ${audioCodec}`);
    if (audioCodec === 'aac') parts.push('-b:a 128k');
    if (fps) parts.push(`-r ${fps}`);
    parts.push('-movflags +faststart');
    parts.push(`"${output}"`);
    cmd = parts.join(' ');
  }

  console.log(`Converting: ${path.extname(input)} → ${path.extname(output)}`);
  execSync(cmd, { stdio: 'inherit' });
  console.log(`✅ Converted: ${output}`);
}

// CLI mode
if (require.main === module) {
  const args = process.argv.slice(2);
  const options = {};
  let currentKey = null;
  for (const arg of args) {
    if (arg.startsWith('--')) {
      currentKey = arg.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      options[currentKey] = true;
    } else if (currentKey) {
      if (options[currentKey] === true) options[currentKey] = arg;
      currentKey = null;
    }
  }

  if (options.crf) options.crf = parseInt(options.crf);
  if (options.fps) options.fps = parseInt(options.fps);
  if (options.copyAll === 'true') options.copyAll = true;
  if (options.copyAll === 'false') options.copyAll = false;

  if (!options.input || !options.output) {
    console.log('Usage: node convert.js --input <input> --output <output> [--video-codec libx264] [--audio-codec aac] [--crf 23] [--preset medium] [--fps 30] [--copy-all false]');
    process.exit(1);
  }

  convert(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { convert };
