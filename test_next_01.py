#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import yt_dlp
import re
import shutil
import os
import json
import signal
import time
from typing import List, Dict, Optional, Tuple

# ========== 调试输出 ==========
def debug_print(*args):
    print("[DEBUG]", *args, flush=True)

# ========== 播放策略配置 ==========
DEFAULT_STRATEGY = {
    "priorities": [
        {"codec": "avc1", "max_height": 1080, "weight": 100},
        {"codec": "hev1", "max_height": 1080, "weight": 80},
        {"codec": "avc1", "max_height": 720, "weight": 70},
        {"codec": "hev1", "max_height": 720, "weight": 60},
        {"codec": "avc1", "max_height": 480, "weight": 50},
        {"codec": "hev1", "max_height": 480, "weight": 40},
    ],
    "fallback_to_any": True,
    "hardware_decoding": "auto-safe",
    "cache_mb": 32,
    "cookies": None,
}

# ========== 全局单例 yt-dlp ==========
GLOBAL_YDL = None

def get_reusable_ydl():
    global GLOBAL_YDL
    if GLOBAL_YDL is None:
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
            'skip_download': True,
            'geo_bypass': True,
            'ignore_no_formats_error': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.bilibili.com/',
                'Origin': 'https://www.bilibili.com'
            }
        }
        GLOBAL_YDL = yt_dlp.YoutubeDL(base_opts)
    return GLOBAL_YDL

# ========== 依赖检查 ==========
def check_dependencies() -> Tuple[bool, str]:
    mpv_path = shutil.which("mpv")
    if not mpv_path:
        return False, "未找到 mpv 命令，请安装: sudo apt install mpv"
    debug_print(f"mpv 路径: {mpv_path}")
    try:
        debug_print(f"yt-dlp 版本: {yt_dlp.version.__version__}")
        return True, None
    except ImportError:
        return False, "未安装 yt-dlp，请运行: pip install yt-dlp"

# ========== 读取资源库文件 ==========
def load_playlist(file_path: str = "playlist.txt") -> List[Tuple[str, str]]:
    if not os.path.exists(file_path):
        return []
    entries = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '*' in line:
                name, url = line.split('*', 1)
                entries.append((name.strip(), url.strip()))
    return entries

# ========== 进度保存 ==========
PROGRESS_FILE = "progress.json"

def load_progress() -> Dict[str, int]:
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        debug_print(f"读取进度文件失败: {e}")
        return {}

def save_progress(bvid: str, page: int):
    progress = load_progress()
    progress[bvid] = page
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
    except Exception as e:
        debug_print(f"保存进度失败: {e}")

# ========== B站 API 获取分P列表 ==========
def get_video_pages_from_api(bvid: str) -> Optional[List[Tuple[str, int, str]]]:
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome 120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
    }
    try:
        import httpx
        resp = httpx.get(api_url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data['code'] != 0:
            debug_print(f"API 返回错误: code={data['code']}, msg={data.get('message')}")
            return None
        pages = data['data'].get('pages', [])
        if not pages:
            debug_print("API 返回的 pages 为空")
            return None
        result = []
        for page in pages:
            page_num = page.get('page', 0)
            title = page.get('part', f'第{page_num}集')
            play_url = f"https://www.bilibili.com/video/{bvid}?p={page_num}"
            result.append((title, page_num, play_url))
        debug_print(f"API 获取成功，共 {len(result)} 集")
        return result
    except Exception as e:
        debug_print(f"API 请求异常: {e}")
        return None

# ========== 使用 yt-dlp 管道获取直链 ==========
def get_video_stream_urls(url: str, cookies_file: str = None) -> Tuple[Optional[str], Optional[str]]:
    """使用 yt-dlp 获取视频和音频的直链，返回 (video_url, audio_url)"""
    cmd = ['yt-dlp', '-f', 'bestvideo+bestaudio', '-g']
    
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(['--cookies', cookies_file])
    
    cmd.append(url)
    debug_print(f"获取直链命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            debug_print(f"yt-dlp 获取直链失败: {result.stderr}")
            return None, None
        
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            video_url, audio_url = lines[0], lines[1]
            debug_print(f"成功获取直链")
            return video_url, audio_url
        elif len(lines) == 1:
            debug_print(f"获取到合并流")
            return lines[0], None
        else:
            debug_print("yt-dlp 未返回有效链接")
            return None, None
    except subprocess.TimeoutExpired:
        debug_print("获取直链超时")
        return None, None
    except Exception as e:
        debug_print(f"获取直链异常: {e}")
        return None, None

def start_mpv_process_pipe(url: str, strategy: Dict, status_callback=None) -> Tuple[Optional[str], Optional[subprocess.Popen], Optional[str]]:
    """管道模式：先获取直链，再用 mpv 播放（shell方式）"""
    if status_callback:
        status_callback("正在获取视频流地址...")
    
    cookies_file = None
    cookies = strategy.get('cookies')
    if cookies and isinstance(cookies, str) and os.path.isfile(cookies):
        cookies_file = cookies
    
    video_url, audio_url = get_video_stream_urls(url, cookies_file)
    
    if not video_url:
        return "无法获取视频流地址，请检查网络或Cookie", None, None
    
    # 构建 shell 命令字符串
    hwdec = strategy.get("hardware_decoding", "auto-safe")
    if audio_url:
        mpv_cmd = f'mpv --cache=yes --cache-secs=25 --keep-open=yes --hwdec={hwdec} "{video_url}" --audio-file="{audio_url}" --http-header-fields="Referer: https://www.bilibili.com"'
    else:
        mpv_cmd = f'mpv --cache=yes --cache-secs=25 --keep-open=yes --hwdec={hwdec} "{video_url}" --http-header-fields="Referer: https://www.bilibili.com"'
    
    debug_print(f"启动 mpv...")
    
    if status_callback:
        status_callback("正在启动 mpv 播放器...")
    
    try:
        proc = subprocess.Popen(
            mpv_cmd,
            shell=True,
            stdout=None,
            stderr=None,
            start_new_session=True,
            executable='/bin/bash'
        )
        debug_print(f"mpv 进程已启动，PID: {proc.pid}")
        return None, proc, "pipe (best)"
    except Exception as e:
        return f"启动 mpv 失败: {e}", None, None

# ========== 传统模式（备用） ==========
def get_best_format_id(url: str, strategy: Dict, status_callback=None) -> Tuple[Optional[str], Optional[str]]:
    """使用 yt-dlp 获取最佳格式ID"""
    if status_callback:
        status_callback("正在获取视频格式列表...")
    
    ydl = get_reusable_ydl()
    ydl.params.pop('cookiesfrombrowser', None)
    ydl.params.pop('cookiefile', None)
    
    cookies = strategy.get('cookies')
    if cookies:
        if isinstance(cookies, tuple):
            ydl.params['cookiesfrombrowser'] = (cookies[0],)
        elif isinstance(cookies, str) and os.path.isfile(cookies):
            ydl.params['cookiefile'] = cookies
    
    try:
        info = ydl.extract_info(url, download=False)
    except Exception as e:
        debug_print(f"extract_info 失败: {e}")
        return None, None
    
    formats = info.get('formats', [])
    video_formats = [f for f in formats if f.get('vcodec') != 'none']
    if not video_formats:
        return None, None
    
    for rule in sorted(strategy['priorities'], key=lambda x: x['weight'], reverse=True):
        codec_pattern = rule['codec']
        max_h = rule['max_height']
        candidates = []
        for f in video_formats:
            vcodec = f.get('vcodec', '')
            height = f.get('height', 0)
            if codec_pattern and codec_pattern not in vcodec:
                continue
            if height <= max_h:
                candidates.append(f)
        if candidates:
            best = max(candidates, key=lambda f: (f.get('height', 0), f.get('tbr', 0)))
            vcodec = best.get('vcodec', '')
            if 'avc1' in vcodec:
                codec_short = 'avc1 (H.264)'
            elif 'hev1' in vcodec or 'hvc1' in vcodec:
                codec_short = 'hev1 (H.265)'
            elif 'av01' in vcodec:
                codec_short = 'av01 (AV1)'
            else:
                codec_short = vcodec.split('.')[0]
            debug_print(f"选中格式: {best['format_id']} ({vcodec}, {best.get('height')}p)")
            return best['format_id'], codec_short
    
    if strategy.get('fallback_to_any') and video_formats:
        best = max(video_formats, key=lambda f: (f.get('height', 0), f.get('tbr', 0)))
        vcodec = best.get('vcodec', '')
        if 'avc1' in vcodec:
            codec_short = 'avc1 (H.264)'
        elif 'hev1' in vcodec or 'hvc1' in vcodec:
            codec_short = 'hev1 (H.265)'
        elif 'av01' in vcodec:
            codec_short = 'av01 (AV1)'
        else:
            codec_short = vcodec.split('.')[0]
        return best['format_id'], codec_short
    return None, None

def build_mpv_command(url: str, format_id: str, strategy: Dict) -> List[str]:
    """构建 mpv 传统命令"""
    cmd = ['mpv']
    cmd.extend([
        f'--hwdec={strategy.get("hardware_decoding", "auto-safe")}',
        '--cache=yes',
        f'--demuxer-max-bytes={strategy.get("cache_mb")}M',
        '--cache-secs=25',
        '--cache-pause=no',
        '--stream-buffer-size=16M',
        '--network-timeout=30',
        '--http-header-fields=Referer: https://www.bilibili.com',
        '--keep-open=yes',
    ])
    cookies = strategy.get('cookies')
    if cookies:
        if isinstance(cookies, tuple):
            cmd.append(f'--cookies-from-browser={cookies[0]}')
        elif isinstance(cookies, str) and os.path.isfile(cookies):
            cmd.append(f'--cookies-file={cookies}')
    cmd.append(f'--ytdl-format={format_id}+bestaudio/best')
    cmd.append(url)
    return cmd

def start_mpv_process_legacy(url: str, strategy: Dict, status_callback=None) -> Tuple[Optional[str], Optional[subprocess.Popen], Optional[str]]:
    """传统模式：让 mpv 自己调用 yt-dlp"""
    if status_callback:
        status_callback("正在选择最佳格式...")
    format_id, codec_name = get_best_format_id(url, strategy, status_callback)
    if not format_id:
        return "无法获取可用的视频格式", None, None
    cmd = build_mpv_command(url, format_id, strategy)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=None,
            stderr=None,
            start_new_session=True
        )
        if status_callback:
            status_callback("mpv 播放器已启动")
        return None, proc, codec_name
    except Exception as e:
        return f"启动 mpv 失败: {e}", None, None

# ========== GUI 程序 ==========
class BiliPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("B站播放器 - 管道模式版")
        self.root.geometry("850x700")

        ok, err = check_dependencies()
        if not ok:
            messagebox.showerror("依赖缺失", err)
            self.root.destroy()
            return

        self.avoid_av1 = tk.BooleanVar(value=True)
        self.max_res = tk.StringVar(value="1080p")
        self.hwdec = tk.BooleanVar(value=True)
        self.use_pipe_mode = tk.BooleanVar(value=True)
        self.cookie_source = tk.StringVar(value="file")
        self.cookie_file_path = ""
        self.entries = []
        self.current_strategy = DEFAULT_STRATEGY.copy()

        self.playlist_entries = []
        self.selected_playlist_var = tk.StringVar()

        self.current_mpv_proc = None
        self.current_playing_index = -1
        self.selected_index = -1
        self.current_bvid = None

        self.button_pool = []
        self.cols = 3

        self.create_widgets()
        self.refresh_playlist()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        frame_library = tk.LabelFrame(self.root, text="我的资源库 (playlist.txt)", padx=10, pady=5)
        frame_library.pack(pady=10, padx=10, fill=tk.X)

        tk.Label(frame_library, text="选择资源:").pack(side=tk.LEFT)
        self.playlist_combo = ttk.Combobox(frame_library, textvariable=self.selected_playlist_var, width=50, state="readonly")
        self.playlist_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.playlist_combo.bind("<<ComboboxSelected>>", self.on_playlist_select)

        tk.Button(frame_library, text="刷新资源库", command=self.refresh_playlist).pack(side=tk.LEFT, padx=5)

        frame_url = tk.Frame(self.root)
        frame_url.pack(pady=5, padx=10, fill=tk.X)
        tk.Label(frame_url, text="B站视频/合集URL:").pack(side=tk.LEFT)
        self.url_entry = tk.Entry(frame_url, width=60)
        self.url_entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.load_btn = tk.Button(frame_url, text="加载分集", command=self.load_video)
        self.load_btn.pack(side=tk.LEFT)

        frame_cookie = tk.Frame(self.root)
        frame_cookie.pack(pady=5, padx=10, fill=tk.X)
        tk.Label(frame_cookie, text="Cookie来源:").pack(side=tk.LEFT)
        for text, val in [("cookies.txt", "file")]:
            rb = tk.Radiobutton(frame_cookie, text=text, variable=self.cookie_source, value=val, command=self.toggle_cookie_file)
            rb.pack(side=tk.LEFT, padx=5)
        self.cookie_file_btn = tk.Button(frame_cookie, text="选择文件", command=self.select_cookie_file)
        self.cookie_file_btn.pack(side=tk.LEFT, padx=5)
        self.cookie_label = tk.Label(frame_cookie, text="", fg="gray")
        self.cookie_label.pack(side=tk.LEFT)
        
        default_cookie = os.path.join(os.path.dirname(__file__), "cookies.txt")
        if os.path.exists(default_cookie):
            self.cookie_file_path = default_cookie
            self.cookie_label.config(text=os.path.basename(default_cookie))
            debug_print(f"已加载默认 cookie: {default_cookie}")

        frame_strategy = tk.LabelFrame(self.root, text="播放策略", padx=10, pady=5)
        frame_strategy.pack(pady=5, padx=10, fill=tk.X)
        tk.Checkbutton(frame_strategy, text="避开 AV1 编码", variable=self.avoid_av1).pack(anchor=tk.W)
        tk.Checkbutton(frame_strategy, text="启用硬件解码", variable=self.hwdec).pack(anchor=tk.W)
        tk.Checkbutton(frame_strategy, text="使用管道模式（推荐）", variable=self.use_pipe_mode).pack(anchor=tk.W)
        tk.Label(frame_strategy, text="分辨率上限:").pack(anchor=tk.W)
        ttk.Combobox(frame_strategy, textvariable=self.max_res, values=["1080p", "720p", "480p"], state="readonly").pack(anchor=tk.W)

        nav_frame = tk.Frame(self.root)
        nav_frame.pack(pady=5, padx=10, fill=tk.X)
        self.prev_btn = tk.Button(nav_frame, text="◀ 上一集", command=self.prev_episode, width=10)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        self.next_btn = tk.Button(nav_frame, text="下一集 ▶", command=self.next_episode, width=10)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        self.play_btn = tk.Button(nav_frame, text="播放", bg="#4CAF50", fg="white", width=8, command=self.play_selected)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        self.codec_label = tk.Label(nav_frame, text="编码: --", fg="blue", width=20, anchor="w")
        self.codec_label.pack(side=tk.LEFT, padx=10)

        frame_list = tk.LabelFrame(self.root, text="分集列表 (单击选中，点击播放按钮播放)", padx=10, pady=5)
        frame_list.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(frame_list, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.episodes_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.episodes_frame, anchor="nw")

        def configure_canvas(event):
            self.canvas.itemconfig(1, width=event.width)
        self.canvas.bind('<Configure>', configure_canvas)

        def on_frame_configure(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.episodes_frame.bind('<Configure>', on_frame_configure)

        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind_all("<MouseWheel>", on_mousewheel)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="清空列表", command=self.clear_list, width=10).pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="就绪")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def toggle_cookie_file(self):
        pass

    def select_cookie_file(self):
        f = filedialog.askopenfilename(title="选择 cookies.txt", filetypes=[("Text files", "*.txt")])
        if f:
            self.cookie_file_path = f
            self.cookie_label.config(text=os.path.basename(f))

    def refresh_playlist(self):
        self.playlist_entries = load_playlist()
        if not self.playlist_entries:
            self.playlist_combo['values'] = []
            self.selected_playlist_var.set("")
            self.status_var.set("资源库为空，请在同级目录创建 playlist.txt，格式：名称*链接")
            return
        names = [name for name, _ in self.playlist_entries]
        self.playlist_combo['values'] = names
        if names:
            self.selected_playlist_var.set(names[0])
            first_url = self.playlist_entries[0][1]
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, first_url)
            self.status_var.set(f"已加载资源库，共 {len(names)} 个资源")

    def on_playlist_select(self, event=None):
        selected_name = self.selected_playlist_var.get()
        for name, url in self.playlist_entries:
            if name == selected_name:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, url)
                self.status_var.set(f"已选择：{name}")
                break

    def clear_list(self):
        for row_btns in self.button_pool:
            for btn in row_btns:
                btn.grid_remove()

        self.entries.clear()
        self.selected_index = -1
        self.current_playing_index = -1
        self.current_bvid = None
        self.status_var.set("列表已清空")
        self.stop_current_mpv()
        self.update_nav_buttons_state()
        self.codec_label.config(text="编码: --")

    def stop_current_mpv(self):
        if self.current_mpv_proc and self.current_mpv_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.current_mpv_proc.pid), signal.SIGTERM)
                self.current_mpv_proc.wait(timeout=2)
            except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                try:
                    self.current_mpv_proc.terminate()
                except:
                    pass
            finally:
                self.current_mpv_proc = None
                debug_print("已终止当前 mpv 进程")

    def on_closing(self):
        self.stop_current_mpv()
        self.root.destroy()

    def update_strategy(self):
        strategy = DEFAULT_STRATEGY.copy()
        
        if self.cookie_file_path and os.path.exists(self.cookie_file_path):
            strategy["cookies"] = self.cookie_file_path
        else:
            default_cookie = os.path.join(os.path.dirname(__file__), "cookies.txt")
            if os.path.exists(default_cookie):
                strategy["cookies"] = default_cookie
            else:
                strategy["cookies"] = None

        res_map = {"1080p": 1080, "720p": 720, "480p": 480}
        max_h = res_map.get(self.max_res.get(), 1080)

        if self.avoid_av1.get():
            strategy["priorities"] = [
                {"codec": "avc1", "max_height": max_h, "weight": 100},
                {"codec": "hev1", "max_height": max_h, "weight": 80},
                {"codec": "avc1", "max_height": 720, "weight": 70},
                {"codec": "hev1", "max_height": 720, "weight": 60},
                {"codec": "avc1", "max_height": 480, "weight": 50},
                {"codec": "hev1", "max_height": 480, "weight": 40},
            ]
        else:
            strategy["priorities"] = [{"codec": "", "max_height": max_h, "weight": 100}]
        strategy["hardware_decoding"] = "auto-safe" if self.hwdec.get() else "no"
        self.current_strategy = strategy

    def load_video(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入 URL")
            return
        self.clear_list()
        self.load_btn.config(state=tk.DISABLED)
        self.status_var.set("正在加载分集...")
        threading.Thread(target=self._load_entries, args=(url,), daemon=True).start()

    def _load_entries(self, url):
        def update_status(msg):
            self.root.after(0, lambda: self.status_var.set(msg))

        bv_match = re.search(r'BV([a-zA-Z0-9]+)', url)
        if not bv_match:
            update_status("无法提取 BV 号")
            self.root.after(0, self.load_btn.config(state=tk.NORMAL))
            return
        bvid = bv_match.group(0)
        self.current_bvid = bvid
        update_status(f"正在请求 API: {bvid}")

        pages = get_video_pages_from_api(bvid)
        if pages is None:
            update_status("API 请求失败")
            self.root.after(0, lambda: messagebox.showerror("加载失败", "无法从 B站 API 获取分集列表。\n请检查网络或 BV 号是否正确。"))
            self.root.after(0, lambda: self.load_btn.config(state=tk.NORMAL))
            return

        if not pages:
            update_status("未找到分集")
            self.root.after(0, lambda: messagebox.showinfo("提示", "未找到任何分集"))
            self.root.after(0, lambda: self.load_btn.config(state=tk.NORMAL))
            return

        self.entries = [(title, play_url) for title, _, play_url in pages]

        def build_grid():
            total = len(self.entries)
            rows = (total + self.cols - 1) // self.cols

            while len(self.button_pool) < rows:
                self.button_pool.append([])
            for r in range(rows):
                while len(self.button_pool[r]) < self.cols:
                    btn = tk.Button(self.episodes_frame, width=30, anchor="w")
                    self.button_pool[r].append(btn)

            for idx, (title, _) in enumerate(self.entries):
                row = idx // self.cols
                col = idx % self.cols
                btn = self.button_pool[row][col]
                display_text = f"{idx+1:02d}. {title[:27]}{'...' if len(title)>27 else ''}"
                btn.config(text=display_text, command=lambda i=idx: self.select_episode(i))
                btn.grid(row=row, column=col, padx=4, pady=2, sticky="ew")

            for c in range(self.cols):
                self.episodes_frame.columnconfigure(c, weight=1)

            progress = load_progress()
            if bvid in progress:
                saved_page = progress[bvid]
                target_idx = saved_page - 1
                if 0 <= target_idx < len(self.entries):
                    self.select_episode(target_idx, scroll_to_view=True)
                    self.status_var.set(f"上次播放: {self.entries[target_idx][0]}")
            else:
                if self.entries:
                    self.select_episode(0, scroll_to_view=True)

            self.update_nav_buttons_state()
            self.load_btn.config(state=tk.NORMAL)

        self.root.after(0, build_grid)

    def select_episode(self, idx: int, scroll_to_view=False):
        if idx < 0 or idx >= len(self.entries):
            return
        for row_btns in self.button_pool:
            for btn in row_btns:
                btn.config(bg=tk.Button().cget("bg"))
        row = idx // self.cols
        col = idx % self.cols
        if row < len(self.button_pool) and col < len(self.button_pool[row]):
            self.button_pool[row][col].config(bg="#b0e0e6")
        self.selected_index = idx
        if scroll_to_view:
            self.root.update_idletasks()
            canvas_height = self.canvas.winfo_height()
            if canvas_height > 0 and self.canvas.bbox("all"):
                bbox = self.canvas.bbox("all")
                item_height = bbox[3] / len(self.entries) if len(self.entries) > 0 else 35
                y_position = row * item_height
                self.canvas.yview_moveto(y_position / bbox[3] if bbox[3] > 0 else 0)
        self.status_var.set(f"已选中: {self.entries[idx][0]}")

    def update_nav_buttons_state(self):
        if not self.entries:
            self.prev_btn.config(state=tk.DISABLED)
            self.next_btn.config(state=tk.DISABLED)
            return
        self.prev_btn.config(state=tk.NORMAL if self.current_playing_index > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if 0 <= self.current_playing_index < len(self.entries)-1 else tk.DISABLED)

    def play_episode_by_index(self, idx: int):
        if idx < 0 or idx >= len(self.entries):
            return
        title, url = self.entries[idx]
        self.status_var.set(f"正在启动播放: {title}")
        self.update_strategy()
        self.stop_current_mpv()
        self.current_playing_index = idx
        self.update_nav_buttons_state()
        self.select_episode(idx)

        if self.current_bvid:
            p_match = re.search(r'[?&]p=(\d+)', url)
            if p_match:
                page = int(p_match.group(1))
                save_progress(self.current_bvid, page)

        def play_thread():
            def status_cb(msg):
                self.root.after(0, lambda: self.status_var.set(msg))
            
            if self.use_pipe_mode.get():
                debug_print("使用管道模式播放")
                err, proc, codec_name = start_mpv_process_pipe(url, self.current_strategy, status_cb)
            else:
                debug_print("使用传统模式播放")
                err, proc, codec_name = start_mpv_process_legacy(url, self.current_strategy, status_cb)
            
            if err:
                self.root.after(0, lambda: messagebox.showerror("播放错误", err))
                self.root.after(0, lambda: self.status_var.set("播放失败"))
                self.root.after(0, lambda: setattr(self, 'current_playing_index', -1))
                self.root.after(0, self.update_nav_buttons_state)
            else:
                self.current_mpv_proc = proc
                self.root.after(0, lambda: self.codec_label.config(text=f"编码: {codec_name}"))
                
                def monitor():
                    if proc:
                        proc.wait()
                    self.root.after(0, lambda: setattr(self, 'current_mpv_proc', None))
                    if self.current_playing_index == idx:
                        self.root.after(0, lambda: setattr(self, 'current_playing_index', -1))
                        self.root.after(0, self.update_nav_buttons_state)
                        self.root.after(0, lambda: self.status_var.set("播放结束"))
                
                threading.Thread(target=monitor, daemon=True).start()
        
        threading.Thread(target=play_thread, daemon=True).start()

    def play_selected(self):
        if self.selected_index >= 0 and self.selected_index < len(self.entries):
            self.play_episode_by_index(self.selected_index)
        else:
            messagebox.showinfo("提示", "请先在列表中单击选中一集")

    def prev_episode(self):
        if not self.entries:
            messagebox.showinfo("提示", "没有加载分集列表")
            return
        if self.current_playing_index <= 0:
            self.status_var.set("已经是第一集")
            return
        self.play_episode_by_index(self.current_playing_index - 1)

    def next_episode(self):
        if not self.entries:
            messagebox.showinfo("提示", "没有加载分集列表")
            return
        if self.current_playing_index >= len(self.entries) - 1:
            self.status_var.set("已经是最后一集")
            return
        self.play_episode_by_index(self.current_playing_index + 1)

if __name__ == "__main__":
    root = tk.Tk()
    app = BiliPlayer(root)
    root.mainloop()