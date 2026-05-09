#!/usr/bin/env python3
"""
使用 moviepy 将 SRT 字幕烧录到视频中
支持中文，自动检测系统字体

用法:
    python3 burn_subtitles.py <video_path> <srt_path> <output_path> [--font <font_path>]
    python3 burn_subtitles.py --batch <directory>  # 批量处理目录下的所有匹配视频/字幕

示例:
    python3 burn_subtitles.py video.mp4 subtitles.srt output.mp4
    python3 burn_subtitles.py video.mp4 subtitles.srt output.mp4 --font /path/to/font.ttf
    python3 burn_subtitles.py --batch ./videos
"""

import os
import re
import sys
import argparse
import platform
from moviepy import VideoFileClip, TextClip, CompositeVideoClip


def parse_srt(srt_file):
    """解析 SRT 字幕文件"""
    subtitles = []
    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\n+', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_line = lines[1]
            match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_line)
            if match:
                start_str, end_str = match.groups()
                start = time_to_seconds(start_str)
                end = time_to_seconds(end_str)
                text = '\n'.join(lines[2:])
                subtitles.append(((start, end), text))

    return subtitles


def time_to_seconds(time_str):
    """将时间字符串转换为秒"""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600 + m * 60 + s + ms / 1000
    return 0


def get_system_chinese_font():
    """检测系统中可用的中文字体"""
    system = platform.system()

    if system == 'Darwin':  # macOS
        candidates = [
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/System/Library/Fonts/STHeiti Medium.ttc',
            '/Library/Fonts/Arial Unicode.ttf',
            '/System/Library/Fonts/AppleSDGothicNeo.ttc',
        ]
    elif system == 'Windows':
        candidates = [
            'C:/Windows/Fonts/simhei.ttf',
            'C:/Windows/Fonts/simsun.ttc',
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/msyhbd.ttc',
        ]
    else:  # Linux
        candidates = [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]

    for font in candidates:
        if os.path.exists(font):
            return font

    return None


def burn_subtitles(video_path, srt_path, output_path, font_path=None, font_size=36,
                   position_y=0.75, stroke_width=2, text_color='white', stroke_color='black'):
    """
    将字幕烧录到视频中

    Args:
        video_path: 输入视频路径
        srt_path: SRT 字幕文件路径
        output_path: 输出视频路径
        font_path: 字体路径（可选，自动检测）
        font_size: 字体大小
        position_y: 字幕垂直位置（0-1，0.75 表示底部偏上）
        stroke_width: 描边宽度
        text_color: 文字颜色
        stroke_color: 描边颜色
    """
    print(f"处理: {os.path.basename(video_path)}")

    # 加载视频
    video = VideoFileClip(video_path)

    # 解析字幕
    subtitles = parse_srt(srt_path)
    print(f"加载 {len(subtitles)} 条字幕")

    # 自动检测字体
    font = font_path or get_system_chinese_font()
    if not font:
        print("⚠️ 未找到中文字体，使用默认字体")
        font = 'Arial'
    else:
        print(f"使用字体: {os.path.basename(font)}")

    # 创建字幕剪辑列表
    subtitle_clips = []
    for (start, end), text in subtitles:
        txt_clip = (TextClip(
            text=text,
            font_size=font_size,
            color=text_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            font=font,
            method='caption',
            text_align='center',
            size=(int(video.w * 0.9), None)
        )
        .with_start(start)
        .with_duration(end - start)
        .with_position(('center', int(video.h * position_y))))

        subtitle_clips.append(txt_clip)

    # 合成视频和字幕
    final_video = CompositeVideoClip([video] + subtitle_clips)

    # 保存结果
    final_video.write_videofile(
        output_path,
        codec='libx264',
        audio_codec='aac',
        temp_audiofile='/tmp/tmp_audio.m4a',
        remove_temp=True,
        fps=video.fps,
        preset='medium',
        logger=None  # 减少输出信息
    )

    # 清理
    video.close()
    final_video.close()

    print(f"✅ 完成: {output_path}")
    return output_path


def batch_process(directory, font_path=None):
    """批量处理目录下的所有视频/字幕对"""
    import glob

    video_files = sorted(glob.glob(os.path.join(directory, '*.mp4')))
    processed = 0

    for video_path in video_files:
        # 跳过已处理过的文件
        if '_subtitled' in video_path:
            continue

        base = os.path.splitext(video_path)[0]
        srt_path = base + '.srt'

        if os.path.exists(srt_path):
            output_path = base + '_subtitled.mp4'
            try:
                burn_subtitles(video_path, srt_path, output_path, font_path)
                processed += 1
            except Exception as e:
                print(f"❌ 处理失败 {video_path}: {e}")
        else:
            print(f"⏭️  跳过: {os.path.basename(video_path)} (无对应字幕文件)")

    print(f"\n🎉 批量处理完成！共处理 {processed} 个视频")


def main():
    parser = argparse.ArgumentParser(
        description='使用 moviepy 将 SRT 字幕烧录到视频中',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s video.mp4 subtitles.srt output.mp4
  %(prog)s video.mp4 subtitles.srt output.mp4 --font /path/to/font.ttf
  %(prog)s --batch ./videos
        """
    )

    parser.add_argument('--batch', '-b', action='store_true',
                        help='批量处理模式，处理目录下所有匹配的视频/字幕对')
    parser.add_argument('--font', '-f', default=None,
                        help='指定字体文件路径')
    parser.add_argument('--font-size', type=int, default=36,
                        help='字体大小（默认: 36）')
    parser.add_argument('--position', type=float, default=0.75,
                        help='字幕垂直位置 0-1（默认: 0.75）')

    parser.add_argument('args', nargs='*',
                        help='[video_path srt_path output_path] 或 [directory]')

    args = parser.parse_args()

    if args.batch:
        if len(args.args) != 1:
            parser.error("批量模式需要一个目录参数")
        batch_process(args.args[0], args.font)
    else:
        if len(args.args) != 3:
            parser.error("需要 3 个参数: video_path srt_path output_path")
        burn_subtitles(
            args.args[0],
            args.args[1],
            args.args[2],
            font_path=args.font,
            font_size=args.font_size,
            position_y=args.position
        )


if __name__ == '__main__':
    main()
