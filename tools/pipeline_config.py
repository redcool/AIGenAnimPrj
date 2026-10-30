"""配置：所有工具和脚本都从这里取路径，不写死机器路径。

优先级：环境变量 > config.env > 默认值。
config.env 不入库（见 .gitignore），模板是 config.example.env。
"""

from __future__ import annotations

import os
import pathlib

# 本仓库根目录（tools/ 的上一级）
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_env_file():
    path = REPO_ROOT / "config.env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # 已存在的环境变量优先，不被文件覆盖
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def version() -> str:
    """本工程版本号，唯一来源是仓库根的 VERSION 文件。"""
    path = REPO_ROOT / "VERSION"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "0.0.0.0"


def cfg(key: str, default=None, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise SystemExit(
            "%s 没有设置。复制 config.example.env 为 config.env 并填写。" % key)
    return value


def unimate_home() -> pathlib.Path:
    """UniMate 仓库的位置（只读依赖，不往里写代码）。"""
    home = pathlib.Path(cfg("UNIMATE_HOME", required=True)).expanduser().resolve()
    if not (home / "unimate").is_dir():
        raise SystemExit("%s 看起来不是 UniMate 仓库（缺 unimate/ 目录）" % home)
    return home


def python_exe() -> str:
    """跑 UniMate 的 Python（要装好 torch / bpy 的那个环境）。"""
    return cfg("UNIMATE_PYTHON", default="python3")


def under_project(value: str) -> pathlib.Path:
    """相对路径按本工程根目录解析；绝对路径原样返回。

    权重和产物都放在本工程里（models/ 和 outputs/），不放进 UniMate 仓库 ——
    上游随时可能被重新克隆或清理。
    """
    p = pathlib.Path(value).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p)


def under_unimate(value: str) -> pathlib.Path:
    """相对路径按 UNIMATE_HOME 解析（给需要指向上游仓库的场景用）。"""
    p = pathlib.Path(value).expanduser()
    return p if p.is_absolute() else (unimate_home() / p)


def exp_dir() -> pathlib.Path:
    """权重目录（含 config.json 和 checkpoints/），默认 models/unimate_mixamo_f60_v2。"""
    return under_project(cfg("UNIMATE_EXP", default="models/unimate_mixamo_f60_v2"))


def samples_home() -> pathlib.Path:
    """采样结果的根目录，默认 outputs/samples。"""
    return under_project(cfg("UNIMATE_SAMPLES", default="outputs/samples"))


def rigs_home() -> pathlib.Path:
    """rig_preprocess 产物的根目录，默认 outputs/rig。"""
    return under_project(cfg("UNIMATE_RIGS", default="outputs/rig"))


def check_pinned_version(home: pathlib.Path) -> str:
    """对照 unimate_version.txt 检查依赖 commit，不一致只警告不阻断。"""
    import subprocess
    pin_file = REPO_ROOT / "unimate_version.txt"
    try:
        head = subprocess.run(["git", "-C", str(home), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""
    if not pin_file.is_file():
        return head
    pinned = ""
    for line in pin_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pinned = line.split()[0]
            break
    if pinned and not head.startswith(pinned[:7]) and not pinned.startswith(head):
        print("[警告] UniMate commit 与本仓库验证过的版本不一致："
              "验证过 %s，当前 %s。行为可能变化。" % (pinned, head))
    return head