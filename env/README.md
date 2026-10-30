# 环境覆盖文件

## requirements.cu128.txt

UniMate 官方锁的是 torch 2.5.1+cu124，本机 RTX 5090 是 sm_120，cu124 没有对应 kernel，
会报 "no kernel image is available"。这份文件把 torch/torchvision 换成 cu128 构建，
并把 PyTorch 源换成阿里云镜像（本机 download.pytorch.org 不通）。

用法（在 UniMate 仓库根目录）：

    uv pip install --python <env>/bin/python \
        --find-links /home/.../wheels \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        --extra-index-url https://download.blender.org/pypi/ \
        --no-build-isolation -r <本文件>

注意：
- 必须 Python 3.10（pip 的 bpy 只有 cp310 轮子）。
- 装完把本文件从 UniMate 仓库删掉，保持上游仓库干净（已经这么做）。
