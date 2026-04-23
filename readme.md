# 有效文件
- test_next_01.py  主程序
- test_api.py 这个是测试bili的api，用来测试api的有效性（假如未来bili改了api）
- cookies.txt 是通过浏览器插件得到的
- playlist.txt 这个是自定义的播放列表
# 回收站 忽略就好
- test_progress.py 新加了进度保存（已经更新到主程序）
- small.py 这个是最基本（备份，大概无用）
- test_next.py 曾经用了五天，很好用，但是似乎被检测到了

# 使用说明
- 这个是一个借助mpv以及bilibil的api 制作的播放器
- 适用于将合集收藏到playlist.txt，
- 格式： 名字*链接

- 如果是**完整链接**，任意的一集，清晰度是1080p

https://www.bilibili.com/video/BV1LtfCBFEPB?spm_id_from=333.788.player.switch&vd_source=b6857fe63bdf6f387a858666aa54e12d&p=67

- 假如链接是**简短**的，比如只是
https://www.bilibili.com/video/BV1LtfCBFEPB

- 那么清晰度会是360或720，具体没测试，所以推荐完整链接，任意一集的**完整链接**
都可以保持**最高清晰度**

- 这个代码采用的是*避开av1编码**，这个格式消耗处理器，是处理器**性能不佳**时候的选项
