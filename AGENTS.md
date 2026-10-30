# AGENTS.md —— 给在这个工程里干活的 agent 看

本工程把 [UniMate](https://github.com/Friedrich-M/UniMate) 包成一条动画产线。
读这个文件的人（或 agent）默认要动代码或跑流程，所以先讲清楚边界和数据在哪。

## 0. 三条边界

1. **不改 UniMate**。它是只读依赖，用 commit 锁定（见 `unimate_version.txt`）。
   真需要改模型或采样逻辑，去 fork，另开补丁，不要动这里的依赖。
2. **权重、产物、数据集都不入库**。`models/`、`outputs/`、`dataset/` 都在 `.gitignore` 里。
   它们体积大，下载方式见本文第 2、3 节。
3. **临时文件进 `tmp/`，删文件进 `.trash/`，同名不覆盖（加 `_v2`）**；版本号遵循
   `Agent工作纪律.md` 第 6 条：x.y 由人定，z（大功能）和 w（小改动）由 agent 维护，
   唯一来源是 `VERSION`。

## 1. 目录

```
AIGenAnimPrj/
├── scripts/   入口（bash）。_env.sh 读配置并导出绝对路径
├── tools/     Python 实现
└── models/    ★ 权重，不入库          （本文第 2 节）
    outputs/   ★ rig 产物 + 采样结果，不入库（本文第 4 节）
    dataset/   ★ UniML3D 数据集，不入库，可选（本文第 3 节）
    tmp/ .trash/  不入库
```

## 2. 下载权重（必做）

两个权重都发布在 HuggingFace 的 `Linzhan/UniMate`（model repo）：

| 目录 | 用途 | 关节 | 大小 | 需要的文件 |
|---|---|---|---|---|
| `models/unimate_mixamo_f60_v2` | 人体专用，**推荐** | 固定 22 | 约 730 MB | config.json、dataset_stats.npy、checkpoints/checkpoint_step_120000.pt |
| `models/unimate_uniml3d_f60_v3` | 通用，任意骨架 | 5~70 | 约 1.2 GB | config.json、dataset_stats.npy、checkpoints/checkpoint_step_150000.pt |

### 用 Python（推荐，可控）

```bash
export HF_HUB_DISABLE_XET=1     # 必须：xet 后端在不少网络下会挂住，表现为"缓存 0 字节"

python - <<'EOF'
from huggingface_hub import snapshot_download

# 人体专用
snapshot_download("Linzhan/UniMate", repo_type="model", local_dir="models",
    allow_patterns=["unimate_mixamo_f60_v2/config.json",
                    "unimate_mixamo_f60_v2/dataset_stats.npy",
                    "unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt"])

# 通用
snapshot_download("Linzhan/UniMate", repo_type="model", local_dir="models",
    allow_patterns=["unimate_uniml3d_f60_v3/config.json",
                    "unimate_uniml3d_f60_v3/dataset_stats.npy",
                    "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"])
EOF
```

### 用 hf 命令行

```bash
hf download Linzhan/UniMate --repo-type model --local-dir models \
    --include "unimate_mixamo_f60_v2/*.json" --include "unimate_mixamo_f60_v2/*.npy" \
    --include "unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt"
```

### 三个坑

- **别下整个模型目录**。`unimate_mixamo_f60_v2/checkpoints/` 里有 13 个历史 checkpoint，
  每个约 765 MB，全下要 10 GB。只要最新的那一个。
- **必须带 `config.json` 和 `dataset_stats.npy`**。前者定义模型结构，后者是归一化统计，
  缺任何一个 sampler 都起不来。
- **网络慢**（实测国内约 1 MB/s）：可设 `HF_ENDPOINT=https://hf-mirror.com` 换镜像；
  下完核对：`du -sh models/*` 应接近上表体积。

### 校验下载结果

```bash
ls models/unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt   # 必须存在
bash setup.sh                                                          # 6 项依赖 + 版本检查
```

## 3. 下载 UniML3D 数据集（可选）

只有两种情况需要：① 想用训练集的 caption 当 prompt 参考；② 想训练或做数据侧对比。
**日常生成动作不需要它。**

```bash
# 只要 caption（很小，写 prompt 时查用例）
hf download Linzhan/UniML3D --repo-type dataset --local-dir dataset \
    --include "features/*/captions*.json"

# 训练用的特征（几十 GB；README 给的完整下载见上游仓库）
hf download Linzhan/UniML3D --repo-type dataset --local-dir dataset \
    --include "features/*" --exclude "features/*/videos/*" --exclude "features/*/tpose/*"
```

全量约 88 GB。下载后目录是 `dataset/features/<dataset>/`，
其中 `captions*.json` 就是官方 prompt 的写法来源（`"An object ..."` 句式）。

## 4. 采样产物：自己生成，不用下载

`outputs/` 里的东西都是本地跑出来的，换机器要重跑，不要指望下载：

```
outputs/
├── rig/<资产名>/          rig_preprocess 产物：cond.npy、<资产名>.glb、preview.png、summary.json
│   └── motions/           （用 --save_clips 才有）资产自带的片段，供插帧/编辑用
└── samples/<批次>/
    ├── motions/*.npy      模型生成的 12 维动作特征（每帧 J×12）
    ├── animations/*.mp4   骨骼预览视频（--only_save_motion 可跳过）
    ├── animated/*.glb     ★ 带动画的网格，Unity 用这个（另有 .fbx）
    ├── manifest.json      这批用了哪个权重、哪个资产、什么 prompt
    └── captions.json      文件名 → prompt 的对照
```

想复刻别人的结果，靠的是 `manifest.json` 里的 `exp_dir / cond_path / prompt / cfg_scale`，
不是下载产物。注意 manifest 里存的是**绝对路径**，换机器后这些路径会失效，
需要重新采样（或者在 manifest 里改路径再跑 `unimate-animate.sh`）。

## 5. 资产从哪来：绑定这一步不在本工程里

**UniMate 不做自动绑定。** 它的输入必须已经是一个 armature + 蒙皮网格，输出只有动作。
手上只有没绑定的网格时，先在外部工具里把绑定做掉，再回到本工程。

### 5.1 rig_preprocess 不是「自动绑骨」

名字容易误会。它做四件事，没有一件是生成骨架：

| 步骤 | 做 | 不做 |
|---|---|---|
| 1 Export | 读入你的骨架，剪掉不带动画的辅助骨 | 不生成骨 |
| 2 Annotate | 把**已有**骨头映射到标签词表、选朝向对 | 不改骨名与层级 |
| 3 Features | 算 T-pose / 层级 / 拓扑，写 `cond.npy` | 不算蒙皮权重 |
| 4 Bake | 把网格与骨架烘到 canonical 帧（站地、朝 +Z） | 不改绑定拓扑 |

第 2 步默认停下来等 review（`REVIEW.md`、`annotation_preview.png`）。
标签或朝向错了整段动作就废——所以它不是全自动的。

### 5.2 四条硬条件

| 条件 | 怎么查 | 不过怎么办 |
|---|---|---|
| 关节数 5~70（模型吃 ≤71；truebones 权重到 85） | `unimate-inspect.sh` 的「关节数」 | `unimate-simplify.sh` |
| 单 armature（一个文件一套骨架） | inspect 输出的 armature 列表 | 先合并或删掉多余骨架 |
| 关节能映射到标签词表 | `REVIEW.md` 里 flagged 的骨头 | 手改 `annotation.json` 的 `label` |
| 朝向对可判定（两关节水平分开） | `annotation_preview.png` 的绿箭头 | `--face_r` / `--face_l` 手动指定 |

### 5.3 哪些形体支持

训练数据覆盖 bipedal（两足）、quadrupedal（四足）、avian（鸟）、marine（水生）、
insectoid（虫）、serpentine（蛇）、articulated rigid objects（带关节的刚体物件）。

| 权重 | 关节 | 说明 |
|---|---|---|
| `unimate_uniml3d_f60_v3` | 5–70 | 通用，推荐 |
| `unimate_mixamo_f60_v2` | 22 固定 | 只吃 Mixamo 22 关节人体 |
| `unimate_truebones_f60_v2` | 5–85 | 动物专用，能吃到 85 关节（唯一不支持 Dragon） |

实测过的四个：X Bot 65→22（两足）、Eagle 51（鸟）、shark 16（鱼）、unitree_go2 18（四足机器人）。

容易翻车的情况：比例极端、密集骨架（全套手指 + 表情）、部件语义模糊（抽象雕塑）、
rest pose 躺倒或倒置（加 `--rest_rotation x180` 摆正）、训练里稀有的体形。

### 5.4 外部绑定工具

| 工具 | 适合 | 出来之后怎么接 |
|---|---|---|
| Mixamo 自动绑定（免费） | 人形首选 | 65 关节 → `--mode mixamo` 削到 22 |
| Blender Rigify | 人形，可定制 | 骨名不固定 → `--mode keep/drop` 指定正则 |
| AccuRig / Meshy / Tripo | 人形、四足 | 视工具输出，先跑 `unimate-inspect.sh` 看关节数 |
| 手工绑定 | 蛇、虫、花等特殊体形 | 目前没有可靠的全自动方案 |

**四足特别提醒**：前腿按手臂标签（`Shoulder` / `Upper Arm` / `Forearm` / `Hand`），
后腿按腿标签（`Thigh` / `Shin` / `Foot` / `Toe`），朝向对仍取左右大腿。
完整规范在 UniMate 的 `data_process/rig_preprocess/AGENTS.md`，改标签前先读它。

## 6. 从零到出片

前提：**资产已经绑定好**（没绑定先看第 5 节）。

```bash
cp config.example.env config.env      # 填 UNIMATE_HOME / UNIMATE_PYTHON
bash setup.sh                          # 依赖自检
bash scripts/install_blender_shim.sh   # 一次性：让 UniMate 的 blender 调用走 bpy

# 0. （可选）先单独体检，避免跑完管线才发现关节不对
bash scripts/unimate-inspect.sh --input /path/to/model.fbx --no-bones
#    超了先精简：Mixamo 绑定用 --mode mixamo，其它骨架用 --drop 正则
bash scripts/unimate-simplify.sh --input /path/to/model.fbx --mode mixamo

# 1. 一条龙：体检 -> 精简（超标才跑）-> 打标签 -> 采样 -> 导出
bash scripts/unimate-pipeline.sh --input /path/to/model.fbx --reps 3

# 2. 循环化 + 打包 Unity
bash scripts/unimate-loop.sh --samples outputs/samples/<资产名> --name <资产名> \
    --rig outputs/rig/<资产名>/<资产名>.glb
```


## 7. 硬约束（踩过坑的）

| 约束 | 原因 / 后果 |
|---|---|
| Python 必须是 **3.10** | pip 的 `bpy` 只有 cp310 轮子，装不上就没有 GLB/FBX 导出 |
| torch 必须匹配 GPU | RTX 5090 是 sm_120，默认 cu124 会报 no kernel image，用 `env/requirements.cu128.txt` |
| 关节 ≤ 71（人体专用固定 22） | 超了 sampler 直接不吃；先跑 `unimate-simplify.sh` |
| 必须有 `blender` 命令 | UniMate 的导出脚本写死调用它；没有装 Blender 就用 shim |
| 模型吃的是**标签**不是骨名 | 标签错 = 动作错；每个资产都要看 `preview.png` 和 `REVIEW.md` |
| 动作是原地（in-place） | 位移交给引擎；不要期待根位移 |
| **资产必须已经绑定** | 本工程不建骨、不算权重；只有网格没有骨架的资产无处可动（第 5 节） |

## 8. 排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `Fetching N files` 卡住、缓存 0 字节 | xet 后端 | `export HF_HUB_DISABLE_XET=1` |
| `No config.json in ...` | 权重只下了 .pt | 补 `config.json` 和 `dataset_stats.npy` |
| `blender: command not found` | 没装 shim | `bash scripts/install_blender_shim.sh` |
| `fits=false` | 关节超 71 | 先精简 |
| 生成的动作"抖"或"不像" | prompt 风格不对 / cfg 太低 | 照 `An object ...` 句式；`--cfg_scale 5~7` |
| 循环处一跳 | 没做循环化 | 走 `unimate-loop.sh`（有周期就剪，没周期用 `--close`） |

## 9. 改动本工程时

- 改完跑一遍 `bash -n`（脚本）和 `python -m py_compile`（工具）。
- 对上游的调用只允许出现在 `tools/unimate_api.py`；其它文件不许 `import unimate`。
- 端到端回归：拿 `Arts/X Bot.fbx` 跑一次 `unimate-loop.sh`，接缝倍数应与上次一致
  （走/跑 0.6~1.3，待机走 `--close` 后 1.4~2.2）。
- 版本号：字段改动 → w+1；新增能力 → z+1 并在 `CHANGELOG.md` 写清楚。