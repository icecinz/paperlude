# 纸片照片进入实拍空间的参考作品

用户明确选定《Stopgap in Stop Motion》作为主要方向：真实人物的照片成为有纸边的平面替身，并待在有纵深的真实环境中。后续制作在这个视觉基础上，让背景连续流动，人物较慢换姿态。

以下“看什么”是本项目的美术取舍。实体剪纸作品可以提供纸边、光影和空间参考，不能据此认为它们使用了本项目的数字目标替换或相同持帧算法。

## 首要参考 Stopgap in Stop Motion

- [观看片段](https://vimeo.com/175577783)
- [导演访谈及影片说明](https://portlanddancefilmfest.com/stopgap-stop-motion/)

影片把舞者照片做成剪片，让人物在桌面上活动。导演说明多数时候每位舞者每秒用约十二张剪片，因此其动画比我们当前追求的低频换姿态密得多。看纸片保留真实人物、窄纸边、薄片与实物的前后关系，以及纸片在场景里的大小与站位。不要把作品中的实物背景等同于持续正常帧率拍下的背景。

以用户确认的[影片片段](https://vimeo.com/175577783)作为视觉方向。

## 空间关系参考 REBEL

- [观看短片](https://vimeo.com/130105496)
- [动画师 Pete List 的作品说明](https://www.petelist.com/rebel)
- [Nix Gerber 的布景说明](https://www.nixgerberstudio.com/archive/rebel)

创作者将模特照片打印裁成小纸片，在实体微缩布景中拍摄。适合看平面人物、机位、透视与有层次的环境如何共存。它的理发店、巷道和地铁等空间是制作的微缩布景，不能直接当成普通街景的视频替换案例。

## 摄影机与平面人物参考 Leaving LA

- [观看 MV](https://www.youtube.com/watch?v=kX-ly8VxhLY)
- [Tee Ken Ng 的制作说明与幕后](https://www.teekenng.com/leaving-la-animated-film)

创作者把真人拍摄画面逐张打印、裁剪，按动作顺序放到旋转装置上，用手机拍出动画。它适合参考摄影机移动时，平面人物与周围物体如何呈现空间；技术采用旋转装置、纸模型和实拍，与当前数字替换流程不同。

## 纸边与印刷加工参考 I Go Crazy

- [观看 MV](https://www.youtube.com/watch?v=evUe46ua8Ao)
- [导演 Guy Larsen 的制作说明](https://www.guylarsen.com/digital/i-go-crazy-orla-gartland)

导演说明使用了打印、手撕嘴型以及定格动画。适合参考手工撕边和照片加工，人物局部替换也可提供启发。用户此前已指出，整个人成为纸片并融入空间才是主要目标，因此它只作材质和局部处理参考。

## 之前检索中保留的补充观看入口

下列链接来自“寻找纸片定格动画参考”对话，作为补充观看入口保存；本次未重新检查全部影片和制作细节。

| 作品 | 观看入口 | 可进一步观察的方向 |
|---|---|---|
| 1990s《59》 | [Vimeo](https://vimeo.com/3383555) | 真人照片剪片与立体场景 |
| The Shins《Half a Million》 | [官方 MV](https://www.youtube.com/watch?v=mWIqmXn3Yyk) | 小照片人物与现实物件互动 |
| Osbert Parker《Film Noir》 | [片段](https://vimeo.com/53209171) | 电影照片剪片、实体空间与光影 |

当需要选风格时，先看 Stopgap，再看 REBEL；要研究镜头运动时看 Leaving LA。现有参考中尚无已核实完整满足“等身照片替身、连续实拍背景、很低频率换姿态、真实纸边”的同一制作范例。

## 工具资料

- [SAM 2 官方仓库](https://github.com/facebookresearch/sam2)：本例已使用 SAM 2.1 small；环境记录和权重指纹保存在历史 v2 与本工作流的资料中。
- [FFmpeg 文档](https://ffmpeg.org/ffmpeg.html)：抽帧、合成输出与解码检查。
- [DaVinci Resolve Studio](https://www.blackmagicdesign.com/products/davinciresolve/studio)：可作为后续人工抠像与合成候选，本案例没有验证其自动化入口。
- [ProPainter 官方仓库](https://github.com/sczhou/ProPainter)：保留为视频修复备选，本例没有使用；采用前再核对运行环境和许可。

首要参考及四个创作者/影片说明页于 2026-10-29 复核。在线链接用于观看和查制作过程，本项目没有下载或复制他人成片。
