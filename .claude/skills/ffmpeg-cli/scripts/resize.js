#!/usr/bin/env node
/**
 * OP6 - 分辨率修改
 * 
 * Usage:
 *   node resize.js --input input.mp4 --output output.mp4 [--width 1920] [--height 1080] [--scale 0.5] [--ratio 16:9]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { getFFmpegPath, getFFprobePath } = require('./merge_av');

function getVideoInfo(filepath) {
  const ffprobe = getFFprobePath();
  try {
    const result = execSync(`"${ffprobe}" -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "${filepath}"`, { encoding: 'utf-8' }).trim();
    const [w, h, fpsStr] = result.split(',');
    return { width: parseInt(w), height: parseInt(h), fps: fpsStr };
  } catch (e) {
    return null;
  }
}

async function resize(options) {
  const { input, output, width, height, scale, ratio } = options;
  const ffmpeg = getFFmpegPath();

  if (!fs.existsSync(input)) throw new Error(`Input file not found: ${input}`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  const info = getVideoInfo(input);
  if (!info) throw new Error('Cannot read video info');

  let vf = '';

  if (scale) {
    // Scale by ratio
    const s = parseFloat(scale);
    vf = `scale=${Math.round(info.width * s)}:${Math.round(info.height * s)}`;
  } else if (width && height) {
    // Exact resolution
    vf = `scale=${width}:${height}`;
  } else if (width && !height) {
    // Width only, keep aspect ratio
    vf = `scale=${width}:-2`;
  } else if (height && !width) {
    // Height only, keep aspect ratio
    vf = `scale=-2:${height}`;
  } else if (ratio) {
    // Target aspect ratio (pad with black bars)
    const [rw, rh] = ratio.split(':').map(Number);
    const targetRatio = rw / rh;
    const currentRatio = info.width / info.height;
    if (Math.abs(currentRatio - targetRatio) < 0.01) {
      vf = null; // Already correct ratio
    } else if (currentRatio > targetRatio) {
      // Video is wider, add top/bottom bars
      const newHeight = Math.round(info.width / targetRatio);
      vf = `scale=${info.width}:${newHeight},pad=${info.width}:${newHeight}:(ow-iw)/2:(oh-ih)/2`;
    } else {
      // Video is taller, add left/right bars
      const newWidth = Math.round(info.height * targetRatio);
      vf = `scale=${newWidth}:${info.height},pad=${newWidth}:${info.height}:(ow-iw)/2:(oh-ih)/2`;
    }
  } else {
    throw new Error('Must specify at least one of: --width, --height, --scale, --ratio');
  }

  let cmd;
  if (vf) {
    cmd = `"${ffmpeg}" -y -i "${input}" -vf "${vf}" -c:v libx264 -crf 23 -preset medium -c:a copy "${output}"`;
  } else {
    cmd = `"${ffmpeg}" -y -i "${input}" -c copy "${output}"`;
  }

  console.log(`Resizing: ${info.width}x${info.height} → target`);
  execSync(cmd, { stdio: 'inherit' });
  console.log(`✅ Resized: ${output}`);
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

  if (options.width) options.width = parseInt(options.width);
  if (options.height) options.height = parseInt(options.height);
  if (options.scale) options.scale = parseFloat(options.scale);

  if (!options.input || !options.output) {
    console.log('Usage: node resize.js --input <input> --output <output> [--width 1920] [--height 1080] [--scale 0.5] [--ratio 16:9]');
    process.exit(1);
  }

  resize(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { resize };
