#!/usr/bin/env node
/**
 * OP1 - 音视频合并（时长匹配）
 * 核心原则：音频时长为基准（Ground Truth）
 * 
 * Usage:
 *   node merge_av.js --video input.mp4 --audio input.mp3 --output output.mp4 [--strategy auto|truncate|extend|shortest] [--padding 0.3]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// FFmpeg 路径解析
function getFFmpegPath() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH;
  // 尝试 moviepy 自带的 FFmpeg
  try {
    const result = execSync('python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"', { encoding: 'utf-8' }).trim();
    if (fs.existsSync(result)) return result;
  } catch (e) { /* ignore */ }
  return 'ffmpeg';
}

function getFFprobePath() {
  if (process.env.FFPROBE_PATH) return process.env.FFPROBE_PATH;
  // 优先使用系统 ffprobe（conda 版本），因为 imageio_ffmpeg 不附带 ffprobe
  try {
    const result = execSync('which ffprobe', { encoding: 'utf-8' }).trim();
    if (result && fs.existsSync(result)) return result;
  } catch (e) { /* ignore */ }
  // 回退：尝试与 ffmpeg 同目录
  const ffmpegPath = getFFmpegPath();
  if (ffmpegPath === 'ffmpeg') return 'ffprobe';
  // imageio_ffmpeg 目录下通常没有 ffprobe，尝试 conda 目录
  const condaFfprobe = ffmpegPath.replace(/imageio_ffmpeg\/binaries\/.*/, 'bin/ffprobe');
  if (fs.existsSync(condaFfprobe)) return condaFfprobe;
  return 'ffprobe';
}

function getDuration(filepath) {
  const ffprobe = getFFprobePath();
  try {
    const result = execSync(`"${ffprobe}" -v error -show_entries format=duration -of csv=p=0 "${filepath}"`, { encoding: 'utf-8' }).trim();
    return parseFloat(result);
  } catch (e) {
    console.error(`Failed to get duration of ${filepath}: ${e.message}`);
    return null;
  }
}

async function mergeAV(options) {
  const { video, audio, output, strategy = 'auto', padding = 0 } = options;
  const ffmpeg = getFFmpegPath();

  if (!fs.existsSync(video)) throw new Error(`Video file not found: ${video}`);
  if (!fs.existsSync(audio)) throw new Error(`Audio file not found: ${audio}`);

  const videoDur = getDuration(video);
  const audioDur = getDuration(audio);
  if (!videoDur || !audioDur) throw new Error('Cannot determine media duration');

  const diff = Math.abs(videoDur - audioDur);
  console.log(`Video: ${videoDur.toFixed(2)}s, Audio: ${audioDur.toFixed(2)}s, Diff: ${diff.toFixed(2)}s`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let cmd;

  if (strategy === 'shortest') {
    cmd = `"${ffmpeg}" -y -i "${video}" -i "${audio}" -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest "${output}"`;
  } else if (strategy === 'truncate') {
    const minDur = Math.min(videoDur, audioDur);
    cmd = `"${ffmpeg}" -y -i "${video}" -i "${audio}" -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -t ${minDur} "${output}"`;
  } else if (strategy === 'extend' || (strategy === 'auto' && audioDur > videoDur + 0.5)) {
    // Video shorter than audio: extend video with still frame
    const padDur = (audioDur - videoDur + padding).toFixed(2);
    const tmpVideo = output.replace(/\.mp4$/, '_padded.mp4');
    execSync(`"${ffmpeg}" -y -i "${video}" -vf "tpad=stop_duration=${padDur}:stop_mode=clone" -an "${tmpVideo}"`, { stdio: 'inherit' });
    cmd = `"${ffmpeg}" -y -i "${tmpVideo}" -i "${audio}" -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 "${output}"`;
    execSync(cmd, { stdio: 'inherit' });
    fs.unlinkSync(tmpVideo);
    console.log(`✅ Merged (video extended by ${padDur}s): ${output}`);
    return;
  } else if (strategy === 'auto' && videoDur > audioDur + 0.5) {
    // Video longer: truncate to audio duration
    cmd = `"${ffmpeg}" -y -i "${video}" -i "${audio}" -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -t ${audioDur} "${output}"`;
  } else {
    // Close enough: direct merge
    cmd = `"${ffmpeg}" -y -i "${video}" -i "${audio}" -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest "${output}"`;
  }

  execSync(cmd, { stdio: 'inherit' });
  console.log(`✅ Merged: ${output}`);
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
      if (options[currentKey] === true) {
        options[currentKey] = arg;
      }
      currentKey = null;
    }
  }

  // Parse numeric values
  if (options.padding) options.padding = parseFloat(options.padding);

  if (!options.video || !options.audio || !options.output) {
    console.log('Usage: node merge_av.js --video <video> --audio <audio> --output <output> [--strategy auto|truncate|extend|shortest] [--padding 0.3]');
    process.exit(1);
  }

  mergeAV(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { mergeAV, getFFmpegPath, getFFprobePath, getDuration };
