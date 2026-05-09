#!/usr/bin/env node
/**
 * OP8 - 音频处理
 * 
 * Usage:
 *   node audio_process.js --input input.mp4 --output audio.mp3 --action extract
 *   node audio_process.js --input input.mp3 --output normalized.mp3 --action normalize [--target-loudness -14]
 *   node audio_process.js --input input.mp4 --output extended.mp4 --action pad --duration 10
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { getFFmpegPath, getDuration } = require('./merge_av');

async function audioProcess(options) {
  const { input, output, action, targetLoudness = -14, duration } = options;
  const ffmpeg = getFFmpegPath();

  if (!fs.existsSync(input)) throw new Error(`Input file not found: ${input}`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let cmd;

  if (action === 'extract') {
    // Extract audio from video
    cmd = `"${ffmpeg}" -y -i "${input}" -vn -acodec libmp3lame -b:a 192k "${output}"`;
    console.log('Extracting audio...');
  } else if (action === 'normalize') {
    // Loudness normalization
    cmd = `"${ffmpeg}" -y -i "${input}" -af "loudnorm=I=${targetLoudness}:TP=-2:LRA=11" "${output}"`;
    console.log(`Normalizing to ${targetLoudness} LUFS...`);
  } else if (action === 'pad') {
    // Extend video with still frames
    const currentDur = getDuration(input);
    if (!currentDur) throw new Error('Cannot determine input duration');
    const targetDur = parseFloat(duration);
    if (targetDur <= currentDur) {
      console.log(`Current duration (${currentDur.toFixed(2)}s) >= target (${targetDur}s), no padding needed`);
      cmd = `"${ffmpeg}" -y -i "${input}" -c copy "${output}"`;
    } else {
      const padDur = (targetDur - currentDur).toFixed(2);
      cmd = `"${ffmpeg}" -y -i "${input}" -vf "tpad=stop_duration=${padDur}:stop_mode=clone" -c:v libx264 -c:a copy "${output}"`;
      console.log(`Padding video by ${padDur}s (still frames)...`);
    }
  } else {
    throw new Error(`Unknown action: ${action}. Use: extract|normalize|pad`);
  }

  execSync(cmd, { stdio: 'inherit' });
  console.log(`✅ Audio processed (${action}): ${output}`);
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

  if (options.targetLoudness) options.targetLoudness = parseFloat(options.targetLoudness);
  if (options.duration) options.duration = parseFloat(options.duration);

  if (!options.input || !options.output || !options.action) {
    console.log('Usage: node audio_process.js --input <input> --output <output> --action extract|normalize|pad [--target-loudness -14] [--duration 10]');
    process.exit(1);
  }

  audioProcess(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { audioProcess };
