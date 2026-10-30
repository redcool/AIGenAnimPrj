# 变更记录

版本号规则（见 Agent工作纪律.md 第 6 条）：
x 世代版本（人手）、y 大版本（人手）、z 大功能（agent 可动）、w 小改动（agent 可动）。

## 1.0.0.2

- 修：流水线的 rig / 采样目录改成绝对路径。原来打印相对路径，用户换个
  工作目录再跑下一步就会解析错（`abs_path` 是按当前目录解析的）。

## 1.0.0.1

- 文档迁移：`docs/快速上手.md` 里的脚本路径改到 `scripts/`，顶部加了迁移说明。
- 无代码改动。

## 1.0.0.0

首个版本。把此前散落在 UniMate 仓库里的工具拆成独立工程，UniMate 只作只读依赖。

### 功能

- `scripts/unimate-inspect.sh` 骨架体检：关节数、层级、蒙皮权重覆盖、动画数量。
- `scripts/unimate-simplify.sh` 骨架精简：按 Mixamo 22 根核心骨或自定义正则删骨，
  并把被删骨的蒙皮权重并入最近的保留祖先（实测 X Bot 65→22，0 个顶点失去权重）。
- `scripts/unimate-pipeline.sh` 一条龙：体检 → 超标才精简 → rig_preprocess → 采样 → 导出。
  目标关节数按权重自动定（人体专用权重固定 22，通用权重默认 71）。
- `scripts/unimate-loop.sh` 循环化，两条路线：
  - 后处理：起点与周期一起搜，剪切 + 接缝淡化（走/跑接缝 0.62~1.10）；
  - 模型闭环 `--close`：末 2 帧钉成首帧 + 速度外推，替换式采样重算中间（待机 1.36~2.21）。
- `tools/flatten_root.py` 拉平根位移，动作变原地。
- `tools/bundle_unity.py` 打包 Unity 目录：角色 FBX + `anim/<类别>_<序号>.fbx` + 带循环质量表的说明。

### 与上游的接口

- 只依赖 UniMate 的公开模块 + `sample.py` 的几个私有辅助函数，全部封装在
  `tools/unimate_api.py`；验证过的 commit 记在 `unimate_version.txt`，启动时不一致会警告。