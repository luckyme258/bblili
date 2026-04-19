test_next.py  这个是更新了按钮位置
test_progress.py 这个功能最全，新加了进度保存
small.py 这个是最基本
next_episode.py 这个实现了快速下一集（需要全屏放大，才可以看见）
test_api.py 这个是测试bili的api

这个是一个借助mpv以及bilibil api 制作的播放器
适用于将合集收藏到playlist.txt，
格式 名字*链接

note： 实测 如果是完整链接，任意的一集，清晰度是1080p

https://www.bilibili.com/video/BV1LtfCBFEPB?spm_id_from=333.788.player.switch&vd_source=b6857fe63bdf6f387a858666aa54e12d&p=67

加入是简短的，比如只是
https://www.bilibili.com/video/BV1LtfCBFEPB

那么清晰度会是360或720 具体没测试 所以推荐完整链接 任意一集的完整链接
都可以保持清晰度

这个代码采用的是避开av1编码，这个格式消耗处理器，是处理器性能不佳时候的选项
