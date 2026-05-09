#!/usr/bin/env node
/**
 * OP3 - 音频拼接
 * 
 * Usage:
 *   node concat_audios.js --inputs a1.mp3 a2.mp3 --output merged.mp3 [--normalize false] [--crossfade 0]
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { getFFmpegPath } = require('./merge_av');

async function concatAudios(options) {
  const { inputs, output, normalize = false, crossfade = 0 } = options;
  const ffmpeg = getFFmpegPath();

  if (!inputs || inputs.length < 2) throw new Error('At least 2 input files required');

  for (const f of inputs) {
    if (!fs.existsSync(f)) throw new Error(`File not found: ${f}`);
  }

  const outputDir = path.dirname(output);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  let processFiles = [...inputs];

  // Normalize if requested
  if (normalize) {
    console.log('Normalizing audio levels...');
    const normalizedFiles = [];
    for (let i = 0; i < processFiles.length; i++) {
      const normPath = path.join(os.tmpdir(), `norm_${i}_${Date.now()}${path.extname(processFiles[i])}`);
      execSync(`"${ffmpeg}" -y -i "${processFiles[i]}" -af "loudnorm=I=-14:TP=-2:LRA=11" "${normPath}"`, { stdio: 'inherit' });
      normalizedFiles.push(normPath);
    }
    processFiles = normalizedFiles;
  }

  // Simple concat (no crossfade)
  if (crossfade <= 0) {
    const listFile = path.join(os.tmpdir(), `concat_audio_${Date.now()}.txt`);
    const listContent = processFiles.map(f => `file '${path.resolve(f)}'`).join('\n');
    fs.writeFileSync(listFile, listContent);

    try {
      execSync(`"${ffmpeg}" -y -f concat -safe 0 -i "${listFile}" -c copy "${output}"`, { stdio: 'inherit' });
    } finally {
      fs.unlinkSync(listFile);
      if (normalize) processFiles.forEach(f => fs.unlinkSync(f));
    }
  } else {
    // Crossfade concat using filter_complex
    const cfSec = parseFloat(crossfade);
    let filterParts = [];
    let inputArgs = '';
    
    for (let i = 0; i < processFiles.length; i++) {
      inputArgs += ` -i "${processFiles[i]}"`;
    }

    if (processFiles.length === 2) {
      filterParts = `[0:a][1:a]acrossfade=d=${cfSec}:c1=tri:c2=tri[aout]`;
      execSync(`"${ffmpeg}" -y${inputArgs} -filter_complex "${filterParts}" -map "[aout]" "${output}"`, { stdio: 'inherit' });
    } else {
      // For >2 files, concat without crossfade (complex crossfade chains are error-prone)
      console.log('Warning: Crossfade only supports 2 files. Using simple concat for >2 files.');
      const listFile = path.join(os.tmpdir(), `concat_audio_${Date.now()}.txt`);
      const listContent = processFiles.map(f => `file '${path.resolve(f)}'`).join('\n');
      fs.writeFileSync(listFile, listContent);
      try {
        execSync(`"${ffmpeg}" -y -f concat -safe 0 -i "${listFile}" -c copy "${output}"`, { stdio: 'inherit' });
      } finally {
        fs.unlinkSync(listFile);
        if (normalize) processFiles.forEach(f => fs.unlinkSync(f));
      }
    }
  }

  console.log(`✅ Concatenated ${inputs.length} audios: ${output}`);
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

  if (options.normalize === 'true') options.normalize = true;
  if (options.normalize === 'false') options.normalize = false;
  if (options.crossfade) options.crossfade = parseFloat(options.crossfade);

  if (options.inputs.length < 2 || !options.output) {
    console.log('Usage: node concat_audios.js --inputs a1.mp3 a2.mp3 ... --output merged.mp3 [--normalize false] [--crossfade 0]');
    process.exit(1);
  }

  concatAudios(options).catch(e => { console.error(e.message); process.exit(1); });
}

module.exports = { concatAudios };
