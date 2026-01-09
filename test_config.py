#!/usr/bin/env python3
"""
测试配置加载
"""
import sys
sys.path.insert(0, '/Volumes/samsungssd/code/temp/ccsdk')

from app.config import settings

print("=" * 60)
print("Settings 对象配置:")
print(f"  anthropic_auth_token: {settings.anthropic_auth_token[:20] if settings.anthropic_auth_token else 'None'}...")
print(f"  anthropic_base_url: {settings.anthropic_base_url}")
print(f"  anthropic_model: {settings.anthropic_model}")
print(f"  work_dir: {settings.work_dir}")
print("=" * 60)
