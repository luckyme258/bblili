from test_bili3 import BiliVideo

url_origin= "https://www.bilibili.com/video/BV1LtfCBFEPB?spm_id_from=333.788.player.switch&vd_source=b6857fe63bdf6f387a858666aa54e12d&p=67"

video = BiliVideo(url_origin)
print(video.bvid)