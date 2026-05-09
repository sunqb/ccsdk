#!/usr/bin/env node
/**
 * OP7 - 调速
 * 
 * Usage:
 *   node change_speed.js --input input.mp4 --output output.mp4 --speed 1.5 [--target video|audio|both] [--target-duration 30]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { getFFmpegPath, getDuration } = require('./merge_av');

function buildAtempoFilter(speed) {
  // atempo range: 0.5 - 2.0, chain for values outside
  const filters = [];
  let remaining = speed;
  while (remaining > 2.0) {
    filters.push('atempo=2.0');
    remaining /= 2.0;
  }
  while (remaining < 0.5) {
    filters.push('atempo=0.5');
    remaining /= 0.5;
  }
  filters.push(`atempo=${remaining.toFixed(4)}`);
  return filters.join(',');
}

async function changeSpeed(options) {
  const { input, output, speed: speedArg, target = 'both', targetDuration } = options;
  const ffmpeg = getFFmpegPath();

  if (!fs.existsSync(input)) throw new Error(`Input file not found: ${input}`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let speed = speedArg ? parseFloat(speedArg) : null;
  if (!speed && targetDuration) {
    const currentDur = getDuration(input);
    if (!currentDur) throw new Error('Cannot determine input duration');
    speed = currentDur / parseFloat(targetDuration);
  }
  if (!speed || speed <= 0) throw new Error('Must specify --speed or --target-duration');

  console.log(`Speed: ${speed.toFixed(3)}x`);

  let cmd;
  if (target === 'video') {
    // Video only, remove audio
    cmd = `"${ffmpeg}" -y -i "${input}" -filter:v "setpts=PTS/${speed.toFixed(4)}" -an "${output}"`;
  } else if (target === 'audio') {
    // Audio only
    const atempo = buildAtempoFilter(speed);
    cmd = `"${ffmpeg}" -y -i "${input}" -filter:a "${atempo}" -vn "${output}"`;
  } else {
    // Both video and audio
    const atempo = buildAtempoFilter(speed);
    cmd = `"${ffmpeg}" -y -i "${input}" -filter:v "setpts=PTS/${speed.toFixed(4)}" -filter:a "${atempo}" "${output}"`;
  }

  execSync(cmd, { stdio: 'inherit' });
  console.log(`✅ Speed changed to ${speed.toFixed(2)}x: ${output}`);
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

  if (!options.input || !options.output) {
    console.log('Usage: node change_speed.js --input <input> --output <output> --speed 1.5 [--target video|audio|both] [--target-duration 30]');
    process.exit(1);
  }

  changeSpeed(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { changeSpeed };
