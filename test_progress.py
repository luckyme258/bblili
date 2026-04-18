#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import yt_dlp
import requests
import re
import shutil
import os
import signal
import time
import json
from typing import List, Dict, Optional, Tuple

# ========== 调试输出 ==========
def debug_print(*args):
    print("[DEBUG]", *args, flush=True)

# ========== 依赖检查 ==========
def check_dependencies() -> Tuple[bool, str]:
    mpv_path = shutil.which("mpv")
    if not mpv_path:
        return False, "未找到 mpv 命令，请安装: sudo apt install mpv"
    debug_print(f"mpv 路径: {mpv_path}")
    try:
        import yt_dlp
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
    """读取进度文件，返回 {bv: page} 字典"""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        debug_print(f"读取进度文件失败: {e}")
        return {}

def save_progress(bvid: str, page: int):
    """保存进度：更新指定 BV 的页码"""
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
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
    "cache_mb": 100,
    "cookies": None,
}

def get_best_format_id(url: str, strategy: Dict, status_callback=None) -> Optional[str]:
    if status_callback:
        status_callback("正在获取视频格式列表...")
    ydl_opts = {'quiet': True, 'extract_flat': False, 'no_warnings': True}
    cookies = strategy.get('cookies')
    if cookies:
        if isinstance(cookies, tuple):
            ydl_opts['cookiesfrombrowser'] = (cookies[0],)
        elif isinstance(cookies, str) and os.path.isfile(cookies):
            ydl_opts['cookiefile'] = cookies
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        debug_print(f"extract_info 失败: {e}")
        return None
    formats = info.get('formats', [])
    video_formats = [f for f in formats if f.get('vcodec') != 'none']
    if not video_formats:
        return None
    # 按优先级选择
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
            debug_print(f"选中格式: {best['format_id']} ({best['vcodec']}, {best.get('height')}p)")
            return best['format_id']
    if strategy.get('fallback_to_any') and video_formats:
        best = max(video_formats, key=lambda f: (f.get('height', 0), f.get('tbr', 0)))
        return best['format_id']
    return None

def build_mpv_command(url: str, format_id: str, strategy: Dict) -> List[str]:
    cmd = ['mpv']
    cmd.extend([
        f'--hwdec={strategy.get("hardware_decoding", "auto-safe")}',
        '--cache=yes',
        f'--demuxer-max-bytes={strategy.get("cache_mb", 100)}M',
        '--cache-secs=60',
        '--cache-pause=no',
        '--stream-buffer-size=64M',
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
    debug_print(f"mpv 命令: {' '.join(cmd)}")
    return cmd

def play_with_mpv(url: str, strategy: Dict, status_callback=None) -> Optional[subprocess.Popen]:
    """
    启动 mpv 播放，返回 Popen 对象（用于后续杀死）
    如果失败返回 None
    """
    if status_callback:
        status_callback("正在选择最佳格式...")
    format_id = get_best_format_id(url, strategy, status_callback)
    if not format_id:
        if status_callback:
            status_callback("无法获取可用的视频格式")
        return None
    cmd = build_mpv_command(url, format_id, strategy)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if status_callback:
            status_callback("mpv 播放器已启动")
        return proc
    except Exception as e:
        if status_callback:
            status_callback(f"启动 mpv 失败: {e}")
        return None

# ========== GUI 程序 ==========
class BiliPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("B站播放器 - 支持上/下一集")
        self.root.geometry("750x680")

        ok, err = check_dependencies()
        if not ok:
            messagebox.showerror("依赖缺失", err)
            self.root.destroy()
            return

        self.avoid_av1 = tk.BooleanVar(value=True)
        self.max_res = tk.StringVar(value="1080p")
        self.hwdec = tk.BooleanVar(value=True)
        self.cookie_source = tk.StringVar(value="none")
        self.cookie_file_path = ""
        self.entries = []          # (title, play_url)
        self.current_strategy = DEFAULT_STRATEGY.copy()

        # 资源库数据
        self.playlist_entries = []  # [(name, url)]
        self.selected_playlist_var = tk.StringVar()

        # 播放状态跟踪
        self.current_playing_idx = -1   # 当前正在播放的分集索引（-1表示无）
        self.current_mpv_process = None # 当前 mpv 进程对象

        # 当前加载的 BV 号（用于进度保存/高亮）
        self.current_bvid = None

        self.create_widgets()
        self.refresh_playlist()

    def create_widgets(self):
        # 资源库区域
        frame_library = tk.LabelFrame(self.root, text="我的资源库 (playlist.txt)", padx=10, pady=5)
        frame_library.pack(pady=10, padx=10, fill=tk.X)

        tk.Label(frame_library, text="选择资源:").pack(side=tk.LEFT)
        self.playlist_combo = ttk.Combobox(frame_library, textvariable=self.selected_playlist_var, width=50, state="readonly")
        self.playlist_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.playlist_combo.bind("<<ComboboxSelected>>", self.on_playlist_select)

        tk.Button(frame_library, text="刷新资源库", command=self.refresh_playlist).pack(side=tk.LEFT, padx=5)

        # URL 输入区
        frame_url = tk.Frame(self.root)
        frame_url.pack(pady=5, padx=10, fill=tk.X)
        tk.Label(frame_url, text="B站视频/合集URL:").pack(side=tk.LEFT)
        self.url_entry = tk.Entry(frame_url, width=60)
        self.url_entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.load_btn = tk.Button(frame_url, text="加载分集", command=self.load_video)
        self.load_btn.pack(side=tk.LEFT)

        # Cookie 设置
        frame_cookie = tk.Frame(self.root)
        frame_cookie.pack(pady=5, padx=10, fill=tk.X)
        tk.Label(frame_cookie, text="Cookie来源:").pack(side=tk.LEFT)
        for text, val in [("无", "none"), ("Firefox", "browser:firefox"), ("Chrome", "browser:chrome"), ("cookies.txt", "file")]:
            rb = tk.Radiobutton(frame_cookie, text=text, variable=self.cookie_source, value=val, command=self.toggle_cookie_file)
            rb.pack(side=tk.LEFT, padx=5)
        self.cookie_file_btn = tk.Button(frame_cookie, text="选择文件", command=self.select_cookie_file, state=tk.DISABLED)
        self.cookie_file_btn.pack(side=tk.LEFT, padx=5)
        self.cookie_label = tk.Label(frame_cookie, text="", fg="gray")
        self.cookie_label.pack(side=tk.LEFT)

        # 播放策略
        frame_strategy = tk.LabelFrame(self.root, text="播放策略", padx=10, pady=5)
        frame_strategy.pack(pady=5, padx=10, fill=tk.X)
        tk.Checkbutton(frame_strategy, text="避开 AV1 编码", variable=self.avoid_av1).pack(anchor=tk.W)
        tk.Checkbutton(frame_strategy, text="启用硬件解码", variable=self.hwdec).pack(anchor=tk.W)
        tk.Label(frame_strategy, text="分辨率上限:").pack(anchor=tk.W)
        ttk.Combobox(frame_strategy, textvariable=self.max_res, values=["1080p", "720p", "480p"], state="readonly").pack(anchor=tk.W)

        # 分集列表
        frame_list = tk.LabelFrame(self.root, text="分集列表 (双击播放)", padx=10, pady=5)
        frame_list.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(frame_list, height=12, font=("TkFixedFont", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)
        self.listbox.bind("<Double-Button-1>", lambda e: self.play_selected())

        # 控制按钮区（新增上/下一集）
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        self.prev_btn = tk.Button(btn_frame, text="◀ 上一集", command=self.play_prev, width=10)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        self.play_btn = tk.Button(btn_frame, text="播放选中集", command=self.play_selected, bg="#4CAF50", fg="white", width=12)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        self.next_btn = tk.Button(btn_frame, text="下一集 ▶", command=self.play_next, width=10)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="清空列表", command=self.clear_list, width=10).pack(side=tk.LEFT, padx=5)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

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
        else:
            self.selected_playlist_var.set("")

    def on_playlist_select(self, event=None):
        selected_name = self.selected_playlist_var.get()
        for name, url in self.playlist_entries:
            if name == selected_name:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, url)
                self.status_var.set(f"已选择：{name}")
                break

    def toggle_cookie_file(self):
        if self.cookie_source.get() == "file":
            self.cookie_file_btn.config(state=tk.NORMAL)
        else:
            self.cookie_file_btn.config(state=tk.DISABLED)
            self.cookie_label.config(text="")

    def select_cookie_file(self):
        f = filedialog.askopenfilename(title="选择 cookies.txt", filetypes=[("Text files", "*.txt")])
        if f:
            self.cookie_file_path = f
            self.cookie_label.config(text=os.path.basename(f))

    def clear_list(self):
        self.listbox.delete(0, tk.END)
        self.entries.clear()
        self.current_playing_idx = -1
        self.current_bvid = None
        self.status_var.set("列表已清空")

    def update_strategy(self):
        strategy = DEFAULT_STRATEGY.copy()
        src = self.cookie_source.get()
        if src == "none":
            strategy["cookies"] = None
        elif src == "file" and self.cookie_file_path:
            strategy["cookies"] = self.cookie_file_path
        elif src.startswith("browser:"):
            browser = src.split(":")[1]
            strategy["cookies"] = (browser,)
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
        if pages:
            self.entries = [(title, play_url) for title, _, play_url in pages]
            def update_listbox():
                self.listbox.delete(0, tk.END)
                for idx, (title, _) in enumerate(self.entries, 1):
                    display = f"{idx:02d}. {title[:80]}"
                    self.listbox.insert(tk.END, display)
                self.status_var.set(f"加载完成，共 {len(self.entries)} 集")
                self.load_btn.config(state=tk.NORMAL)
                self.update_nav_buttons_state()
                # 高亮上次播放的集（如果有）
                progress = load_progress()
                if bvid in progress:
                    saved_page = progress[bvid]
                    target_idx = saved_page - 1
                    if 0 <= target_idx < len(self.entries):
                        self.listbox.selection_clear(0, tk.END)
                        self.listbox.selection_set(target_idx)
                        self.listbox.see(target_idx)
                        self.status_var.set(f"上次播放: {self.entries[target_idx][0]}")
            self.root.after(0, update_listbox)
            return

        # 回退 yt-dlp
        update_status("API 失败，尝试 yt-dlp...")
        ydl_opts = {'quiet': True, 'extract_flat': False, 'no_warnings': True}
        src = self.cookie_source.get()
        if src == "file" and self.cookie_file_path:
            ydl_opts['cookiefile'] = self.cookie_file_path
        elif src.startswith("browser:"):
            ydl_opts['cookiesfrombrowser'] = (src.split(":")[1],)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            debug_print(f"yt-dlp 失败: {e}")
            self.root.after(0, lambda: messagebox.showerror("加载失败", str(e)))
            self.root.after(0, lambda: self.load_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.status_var.set("加载失败"))
            return

        entries = []
        if 'entries' in info and info['entries']:
            for entry in info['entries']:
                if entry is None:
                    continue
                title = entry.get('title', '未知标题')
                play_url = entry.get('webpage_url') or entry.get('url')
                if play_url:
                    entries.append((title, play_url))
        else:
            title = info.get('title', '视频')
            play_url = info.get('webpage_url') or url
            entries.append((title, play_url))

        if not entries:
            self.root.after(0, lambda: messagebox.showinfo("提示", "未找到任何分集"))
            self.root.after(0, lambda: self.load_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.status_var.set("未找到分集"))
            return

        self.entries = entries
        def update_listbox():
            self.listbox.delete(0, tk.END)
            for idx, (title, _) in enumerate(entries, 1):
                display = f"{idx:02d}. {title[:80]}"
                self.listbox.insert(tk.END, display)
            self.status_var.set(f"加载完成，共 {len(entries)} 集")
            self.load_btn.config(state=tk.NORMAL)
            self.update_nav_buttons_state()
            # 对于 yt-dlp 回退，同样尝试高亮（但可能无法精确页码，这里简单处理）
            progress = load_progress()
            if bvid in progress:
                saved_page = progress[bvid]
                target_idx = saved_page - 1
                if 0 <= target_idx < len(self.entries):
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(target_idx)
                    self.listbox.see(target_idx)
                    self.status_var.set(f"上次播放: {self.entries[target_idx][0]}")
        self.root.after(0, update_listbox)

    def update_nav_buttons_state(self):
        """根据当前分集数量和当前播放索引，启用/禁用上/下一集按钮"""
        if not self.entries:
            self.prev_btn.config(state=tk.DISABLED)
            self.next_btn.config(state=tk.DISABLED)
            return
        self.prev_btn.config(state=tk.NORMAL if self.current_playing_idx > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if self.current_playing_idx >= 0 and self.current_playing_idx < len(self.entries)-1 else tk.DISABLED)

    def kill_current_mpv(self):
        """终止当前正在运行的 mpv 进程"""
        if self.current_mpv_process is not None:
            try:
                self.current_mpv_process.terminate()
                try:
                    self.current_mpv_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.current_mpv_process.kill()
                debug_print("已终止旧的 mpv 进程")
            except Exception as e:
                debug_print(f"终止 mpv 进程时出错: {e}")
            finally:
                self.current_mpv_process = None

    def play_by_index(self, idx: int):
        """播放指定索引的分集，并保存进度"""
        if not self.entries:
            messagebox.showwarning("提示", "没有分集列表，请先加载视频")
            return
        if idx < 0 or idx >= len(self.entries):
            debug_print(f"索引越界: {idx}")
            return
        title, url = self.entries[idx]
        self.status_var.set(f"正在播放: {title}")
        self.update_strategy()

        # 先停止当前播放
        self.kill_current_mpv()

        # 记录新索引
        self.current_playing_idx = idx
        self.update_nav_buttons_state()

        # 保存进度：提取当前 BV 和页码
        if self.current_bvid:
            # 从 URL 中提取 p 参数
            p_match = re.search(r'[?&]p=(\d+)', url)
            if p_match:
                page = int(p_match.group(1))
                save_progress(self.current_bvid, page)

        # 启动播放（在新线程中）
        def play_thread():
            def status_cb(msg):
                self.root.after(0, lambda: self.status_var.set(msg))
            proc = play_with_mpv(url, self.current_strategy, status_cb)
            if proc is None:
                self.root.after(0, lambda: messagebox.showerror("播放错误", "无法启动 mpv"))
                self.root.after(0, lambda: self.status_var.set("播放失败"))
                self.root.after(0, lambda: setattr(self, 'current_playing_idx', -1))
                self.root.after(0, self.update_nav_buttons_state)
            else:
                self.current_mpv_process = proc
                proc.wait()
                if self.current_playing_idx == idx:
                    self.root.after(0, lambda: setattr(self, 'current_mpv_process', None))
                    self.root.after(0, lambda: setattr(self, 'current_playing_idx', -1))
                    self.root.after(0, self.update_nav_buttons_state)
                    self.root.after(0, lambda: self.status_var.set("播放结束"))

        threading.Thread(target=play_thread, daemon=True).start()

    def play_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先在列表中选择一集")
            return
        idx = selection[0]
        self.play_by_index(idx)

    def play_prev(self):
        if self.current_playing_idx > 0:
            self.play_by_index(self.current_playing_idx - 1)
        else:
            messagebox.showinfo("提示", "已经是第一集")

    def play_next(self):
        if self.current_playing_idx >= 0 and self.current_playing_idx < len(self.entries) - 1:
            self.play_by_index(self.current_playing_idx + 1)
        else:
            messagebox.showinfo("提示", "已经是最后一集")

if __name__ == "__main__":
    root = tk.Tk()
    app = BiliPlayer(root)
    root.mainloop()