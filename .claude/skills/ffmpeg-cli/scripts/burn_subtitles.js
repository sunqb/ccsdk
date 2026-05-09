#!/usr/bin/env node
/**
 * OP4 - 字幕烧录
 * 
 * Usage:
 *   node burn_subtitles.js --video input.mp4 --subtitle subs.srt --output output.mp4 [--font "PingFang SC"] [--font-size 22] [--method auto|ffmpeg|moviepy]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { getFFmpegPath } = require('./merge_av');

function hasSubtitlesFilter() {
  const ffmpeg = getFFmpegPath();
  try {
    const result = execSync(`"${ffmpeg}" -filters 2>&1`, { encoding: 'utf-8' });
    return result.includes('subtitles') && result.includes('libass');
  } catch (e) {
    return false;
  }
}

function burnWithFFmpeg(options) {
  const { video, subtitle, output, font = 'PingFang SC', fontSize = 22, position = 'bottom', primaryColor = '&HFFFFFF&', outlineColor = '&H000000&', outlineWidth = 2 } = options;
  const ffmpeg = getFFmpegPath();

  const alignmentMap = { bottom: 2, center: 8, top: 10 };
  const alignment = alignmentMap[position] || 2;

  const forceStyle = `FontName=${font},FontSize=${fontSize},PrimaryColour=${primaryColor},OutlineColour=${outlineColor},Outline=${outlineWidth},Alignment=${alignment}`;
  
  // Escape colons in subtitle path for FFmpeg filter
  const escapedSubtitle = subtitle.replace(/\\/g, '/').replace(/:/g, '\\:');

  const cmd = `"${ffmpeg}" -y -i "${video}" -vf "subtitles='${escapedSubtitle}':force_style='${forceStyle}'" -c:a copy "${output}"`;
  execSync(cmd, { stdio: 'inherit' });
}

function burnWithMoviePy(options) {
  const { video, subtitle, output, font, fontSize = 22, position = 'bottom', primaryColor = '&HFFFFFF&', outlineColor = '&H000000&', outlineWidth = 2 } = options;

  // Find Chinese font
  let fontPath = font;
  if (font && !fs.existsSync(font)) {
    const candidates = {
      darwin: ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc', '/Library/Fonts/Arial Unicode.ttf'],
      win32: ['C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc'],
      linux: ['/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    };
    const platform = process.platform === 'darwin' ? 'darwin' : process.platform === 'win32' ? 'win32' : 'linux';
    for (const c of (candidates[platform] || [])) {
      if (fs.existsSync(c)) { fontPath = c; break; }
    }
  }

  const posMap = { bottom: 0.78, center: 0.5, top: 0.15 };
  const posY = posMap[position] || 0.78;

  // Generate Python script
  const pyScript = path.join(require('os').tmpdir(), `burn_subs_${Date.now()}.py`);
  const scriptContent = `
import sys
sys.path.insert(0, '/Users/yeq/CodeBuddy/python_libs')

from moviepy import VideoFileClip, TextClip, CompositeVideoClip
import re

def parse_srt(srt_file):
    subtitles = []
    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = re.split(r'\\n\\n+', content.strip())
    for block in blocks:
        lines = block.strip().split('\\n')
        if len(lines) >= 3:
            time_line = lines[1]
            match = re.match(r'(\\d{2}):(\\d{2}):(\\d{2}),(\\d{3}) --> (\\d{2}):(\\d{2}):(\\d{2}),(\\d{3})', time_line)
            if match:
                h1,m1,s1,ms1,h2,m2,s2,ms2 = map(int, match.groups())
                start = h1*3600 + m1*60 + s1 + ms1/1000
                end = h2*3600 + m2*60 + s2 + ms2/1000
                text = '\\n'.join(lines[2:])
                subtitles.append(((start, end), text))
    return subtitles

def to_seconds(t):
    return t

video = VideoFileClip("${video.replace(/\\/g, '/')}")
subs = parse_srt("${subtitle.replace(/\\/g, '/')}")
font = ${fontPath && fs.existsSync(fontPath) ? `"${fontPath}"` : 'None'}

subtitle_clips = []
for (start, end), text in subs:
    txt = TextClip(
        text=text,
        font_size=${fontSize},
        color='white',
        stroke_color='black',
        stroke_width=${outlineWidth},
        font=font,
        method='caption',
        text_align='center',
        size=(int(video.w * 0.9), None)
    ).with_start(start).with_duration(end - start).with_position(('center', video.h * ${posY}))
    subtitle_clips.append(txt)

final = CompositeVideoClip([video] + subtitle_clips)
final.write_videofile("${output.replace(/\\/g, '/')}", codec='libx264', audio_codec='aac', fps=video.fps, preset='medium', threads=4)
video.close()
final.close()
`;

  fs.writeFileSync(pyScript, scriptContent);
  try {
    execSync(`python3 "${pyScript}"`, { stdio: 'inherit' });
  } finally {
    fs.unlinkSync(pyScript);
  }
}

async function burnSubtitles(options) {
  const { video, subtitle, output, method = 'auto' } = options;

  if (!fs.existsSync(video)) throw new Error(`Video file not found: ${video}`);
  if (!fs.existsSync(subtitle)) throw new Error(`Subtitle file not found: ${subtitle}`);

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let useMethod = method;
  if (useMethod === 'auto') {
    useMethod = hasSubtitlesFilter() ? 'ffmpeg' : 'moviepy';
    console.log(`Auto-detected method: ${useMethod}`);
  }

  if (useMethod === 'ffmpeg') {
    burnWithFFmpeg(options);
  } else {
    burnWithMoviePy(options);
  }

  console.log(`✅ Subtitles burned: ${output}`);
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

  if (!options.video || !options.subtitle || !options.output) {
    console.log('Usage: node burn_subtitles.js --video <video> --subtitle <srt|ass> --output <output> [--font "PingFang SC"] [--font-size 22] [--method auto|ffmpeg|moviepy] [--position bottom|center|top]');
    process.exit(1);
  }

  if (options.fontSize) options.fontSize = parseInt(options.fontSize);

  burnSubtitles(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { burnSubtitles, hasSubtitlesFilter };
