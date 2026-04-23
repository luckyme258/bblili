import requests
import re
import sys
import httpx
import bilibili_api

class BiliVideo:
    """视频类：提供基础属性和方法"""
    def __init__(self,url:str):
        self.url = url
        """从任意链接提取bv号码"""
        match = re.search(r'BV([a-zA-Z0-9]+)', self.url)
        self.bvid= match.group(0) if match else None
        
    def fetch_video_pages(self.bvid):
        """使用 httpx 调用 B 站 API"""
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={self.bvid}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/',
        }
        
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(api_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                
                if data['code'] != 0:
                    print(f"API 返回错误: code={data['code']}, message={data['message']}")
                    return None
                return data['data']
        except Exception as e:
            print(f"请求失败: {e}")
            return None
        
    

            
            
            
                
            
    
            