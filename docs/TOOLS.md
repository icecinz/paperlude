# 工具与复现范围

Paperlude 当前是一个可复现的研究原型。v0.1.0 只绑定已验证的两秒长颈鹿镜头：3840×2160、60000/1001 fps、123 帧、局部区域 `[1050,600,600,1200]`。目标提示、分段阈值和导出尺寸仍按这个案例固定；这不是任意视频通用入口。

## 获取运行环境和示例

需要 Git、FFmpeg、ffprobe 和 Python 3.10 以上版本。原实验使用 Python 3.12.13；固定依赖版本见根目录 `requirements.txt`。不同操作系统的包和硬件支持需要各自验证。

```sh
python3.12 tools/setup_runtime.py --dry-run
python3.12 tools/setup_runtime.py
python3 tools/fetch_demo.py
python3 tools/paperlude.py doctor
python3 tools/paperlude.py check
python3 tools/paperlude.py verify
```

`setup_runtime.py` 会在忽略版本控制的 `.runtime/` 中建立独立环境，从官方仓库获取固定 SAM2 提交，并下载、核对 SAM 2.1 small 模型 SHA-256。默认不编译 CUDA 扩展。模型、第三方源码和虚拟环境不在 Git 仓库中。安装脚本支持 `--python python3.12` 指定解释器；它拒绝修改符号链接到别处的共享 `.runtime`。

`fetch_demo.py` 从固定 GitHub Release 获取独立示例 ZIP，校验整包 SHA-256，再解压原片和基线素材。它拒绝覆盖已有输入，也拒绝越界路径或 ZIP 符号链接。已经手动下载时可用：

```sh
python3 tools/fetch_demo.py --archive giraffe-demo-v0.1.0.zip
```

示例输入在 `examples/giraffe/`，模型和运行环境在 `.runtime/`。主入口路径相对于仓库根目录解析，不依赖原作者电脑上的路径。示例 ZIP 内保留了原实验的中文文件名。

## 只读检查

- `doctor`：检查 FFmpeg、运行环境、SAM2 和图像计算依赖。
- `check`：核对原片指纹和属性、123 张裁剪与 123 张蒙版的内容、尺寸、编号及非空性；核对模型、初始蒙版、纸纹和核心代码指纹。
- `verify`：继续检查已有八段的连续性、代表帧范围和四个视频的属性与完整解码，读取既有覆盖及编码前局部范围外像素保留报告。

指纹绑定的是已审看的原实验缓存。检查没有重新逐帧证明 JPEG 分析缓存与 ProRes 解码像素相同。蒙版修补区域计数为零不等于分割准确、供体干净、背景自然或没有视觉残影。

## 生成新的结果

```sh
python3 tools/paperlude.py compose
python3 tools/paperlude.py track
```

`compose` 复用已验证蒙版，重跑当前核心与参数。`track` 使用 SAM2 重新传播目标蒙版。每次都在 `outputs/` 创建带时间和随机后缀的新目录；源视频和基线不会被覆盖。

重新追踪后，先检查其 `qa/tracking_contact.jpg`，尤其是细腿、耳朵、尾巴和腿间空隙，再使用该次结果合成：

```sh
python3 tools/paperlude.py compose --tracking-run outputs/本次track目录
python3 tools/paperlude.py verify --run outputs/本次compose目录
```

每次结果记录输入、裁剪、核心代码和蒙版指纹；后续修改核心或蒙版会使该结果的验证停止。失败时保留新目录及失败记录便于检查。输出是 H.264、8 位 4:2:0 预览，不是 10 位后期母版。

## 调整和新素材

此入口尚无风格或分段参数的公开调节界面；修改核心会触发基线指纹检查。要适配新素材，需要新案例和明确版本：重新抽帧、选目标、分割、设置镜头和遮挡规则，再建立独立指纹与验收记录。不要覆盖旧指纹来消除基线差异。

当前有完整的原实验追踪记录和重跑合成验证。发布包做了路径迁移检查、示例解包检查及本地既有环境的检查验证；没有把全新机器的联网安装标记为已经验证。

## 小型工具测试

```sh
python3 -m unittest discover -s tests -v
```

测试关注分段缺口、代表帧越界、核心指纹、ZIP 路径穿越、符号链接、错误 SHA-256 和输入覆盖保护；它们不能替代观看合成视频。
