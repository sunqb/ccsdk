#!/usr/bin/env node
/**
 * OP2 - 视频拼接
 * 
 * Usage:
 *   node concat_videos.js --inputs v1.mp4 v2.mp4 v3.mp4 --output merged.mp4 [--reencode false]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { getFFmpegPath } = require('./merge_av');

async function concatVideos(options) {
  const { inputs, output, reencode = false } = options;
  const ffmpeg = getFFmpegPath();

  if (!inputs || inputs.length < 2) throw new Error('At least 2 input files required');

  for (const f of inputs) {
    if (!fs.existsSync(f)) throw new Error(`File not found: ${f}`);
  }

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  // Create concat list file
  const listFile = path.join(os.tmpdir(), `concat_${Date.now()}.txt`);
  const listContent = inputs.map(f => `file '${path.resolve(f)}'`).join('\n');
  fs.writeFileSync(listFile, listContent);

  try {
    let cmd;
    if (reencode) {
      cmd = `"${ffmpeg}" -y -f concat -safe 0 -i "${listFile}" -c:v libx264 -c:a aac -movflags +faststart "${output}"`;
    } else {
      cmd = `"${ffmpeg}" -y -f concat -safe 0 -i "${listFile}" -c copy "${output}"`;
    }
    execSync(cmd, { stdio: 'inherit' });
    console.log(`✅ Concatenated ${inputs.length} videos: ${output}`);
  } finally {
    fs.unlinkSync(listFile);
  }
}

// CLI mode
if (require.main === module) {
  const args = process.argv.slice(2);
  const options = { inputs: [] };
  let currentKey = null;
  for (const arg of args) {
    if (arg.startsWith('--')) {
      currentKey = arg.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      if (currentKey === 'inputs') {
        options.inputs = options.inputs || [];
      } else {
        options[currentKey] = true;
      }
    } else if (currentKey === 'inputs') {
      options.inputs.push(arg);
    } else if (currentKey) {
      options[currentKey] = arg;
      currentKey = null;
    }
  }

  if (options.reencode === 'true') options.reencode = true;
  if (options.reencode === 'false') options.reencode = false;

  if (options.inputs.length < 2 || !options.output) {
    console.log('Usage: node concat_videos.js --inputs v1.mp4 v2.mp4 ... --output merged.mp4 [--reencode false]');
    process.exit(1);
  }

  concatVideos(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { concatVideos };
