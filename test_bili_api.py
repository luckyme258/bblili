#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import re
import sys


def get_bvid_from_url(url_origin):
    """从 B 站 URL 中提取 BV 号"""
    match = re.search(r'BV([a-zA-Z0-9]+)', url_origin)
    if match:
        return match.group(0)
    return None

def get_video_data(url_origin):
    bvid= get_bvid_from_url(url_origin)
    viedo_data=fetch_video_pages(bvid)
    return bvid,viedo_data
    

def fetch_video_pages(bvid):
    """调用 B 站 API 获取视频分 P 信息"""
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data['code'] != 0:
            print(f"API 返回错误: code={data['code']}, message={data['message']}")
            # 常见错误码：-403 需要签名，-404 视频不存在
            if data['code'] == -403:
                print("提示：B站 API 要求 wbi 签名，当前请求未携带签名，可能被拒绝。")
                print("可以尝试使用带签名的请求（见下文）。")
            return None
        return data['data']
    except Exception as e:
        print(f"请求失败: {e}")
        return None

def get_url(bvid):
          
    
    if not bvid or not bvid.startswith('BV'):
        print("无法提取有效的 BV 号，请检查输入。")
        return
    
    print(f"正在请求 API: bvid={bvid}")
    video_data = fetch_video_pages(bvid)
    if not video_data:
        print("获取视频信息失败。")
        return
    
    # 基本信息
    title = video_data.get('title', '无标题')
    print(f"\n视频标题: {title}")
    print(f"BV号: {bvid}")
    print(f"视频简介: {video_data.get('desc', '')[:100]}...")
    
    pages = video_data.get('pages', [])
    if not pages:
        print("该视频没有分 P 信息（可能是单 P）。")
        return
    
    print(f"\n分 P 总数: {len(pages)}")
    print("-" * 60)
    for idx, page in enumerate(pages, 1):
        page_num = page.get('page')
        part_title = page.get('part', f'第{page_num}集')
        cid = page.get('cid')
        print(f"{idx:2d}. 第{page_num}集: {part_title} (cid={cid})")
        # 构造可直接播放的链接
        play_url = f"https://www.bilibili.com/video/{bvid}?p={page_num}"
        return play_url
       

if __name__ == "__main__":
    main()