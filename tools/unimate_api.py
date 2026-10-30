"""唯一 import UniMate 内部模块的地方。

上游是研究代码，sample.py 里的 _prepare_cases、_wrap_for_cfg 这类私有函数
随时可能改名或改签名。所有对它们的依赖都收在这里，上游一动只改这一个文件。

对外只暴露 Session：
    s = Session(exp_dir=..., asset_dir=...)
    cond = s.cond_for("An object walks forward.")
    closed = s.close_loop(motion, prompt, pin_tail=2)   # 输入输出都是反归一化的 (F, J, D)
"""

from __future__ import annotations

import os
import sys

import numpy as np
import torch


def _bootstrap(home) -> None:
    """把 UniMate 仓库放进 import 路径，并切进去（仓库内部大量相对路径）。"""
    home = str(home)
    if home not in sys.path:
        sys.path.insert(0, home)
    os.chdir(home)


class Session:
    """一次加载，多次使用：模型 + 骨架条件 + 文本编码器。"""

    def __init__(self, exp_dir, asset_dir, home=None, cfg_scale=None, device=None):
        _bootstrap(home)

        from unimate.configs.schema import MainConfig
        from unimate.inference.sample import (
            InferenceArgs, _prepare_cases, _resolve_exp_paths, _build_diffusion,
            _load_checkpoint, _make_text_encoder, _encode_prompt, _wrap_for_cfg,
            _resolve_stats_path,
        )
        from unimate.models.factory import create_model
        from unimate.inference.motion_inbetweening import inbetween_sample_ode
        from unimate.dataset.conditioning import create_sample_condition

        self._encode_prompt = _encode_prompt
        self._create_sample_condition = create_sample_condition
        self._inbetween = inbetween_sample_ode

        self.exp_dir = os.path.abspath(str(exp_dir))
        self.asset_dir = os.path.abspath(str(asset_dir))

        self.config = MainConfig.from_json(os.path.join(self.exp_dir, "config.json"))
        _, model_path = _resolve_exp_paths(self.exp_dir, self.config.sampling.model_path)
        self.model_path = model_path
        self.cfg_scale = cfg_scale if cfg_scale is not None else self.config.sampling.cfg_scale
        self.device = torch.device(device or self.config.sampling.device)

        probe = InferenceArgs(exp_dir=self.exp_dir, asset=(self.asset_dir,),
                              prompt=("An object stands still.",), output_dir=self.exp_dir)
        self.dataset, cases, _assets = _prepare_cases(
            probe, self.config, self.cfg_scale, _resolve_stats_path(self.exp_dir), self.device)
        self.object_type = cases[0][1]

        self.model = create_model(dataset_config=self.config.dataset,
                                  model_config=self.config.model)
        transport, sampler = _build_diffusion(self.config)
        self.transport = transport
        self.sampler = sampler
        _load_checkpoint(self.model, model_path, self.config)
        self.model.to(self.device).eval()
        self.sample_model = _wrap_for_cfg(self.model, self.cfg_scale)
        self.encoder = _make_text_encoder(self.config, self.device)

        self.max_T = self.config.dataset.max_motion_length
        self.max_J = self.config.dataset.max_joints
        self.feature_len = self.config.dataset.feature_len

    def cond_for(self, prompt):
        emb = self._encode_prompt(self.encoder, prompt)
        _gt, cond = self._create_sample_condition(
            config=self.config, data=self.dataset,
            test_case_captions=[(self.object_type, prompt, emb)],
        )
        return {k: v.to(self.device) if torch.is_tensor(v) else v for k, v in cond.items()}

    def close_loop(self, motion, prompt, pin_tail=2, num_steps=50,
                   keep_first=True, drop_last=True):
        """把一段动作的末尾钉回收首帧，让模型重算中间。输入/输出都是 (F, J, D)。"""
        cond = self.cond_for(prompt)
        n_joints = int(cond["n_joints"][0].item())
        mean = cond["mean"][0][:n_joints].cpu().numpy()
        std = cond["std"][0][:n_joints].cpu().numpy()

        norm = (motion - mean[None]) / std[None]
        x1 = np.zeros((self.max_J, self.feature_len, self.max_T), dtype=np.float32)
        T = min(motion.shape[0], self.max_T)
        x1[:n_joints, :, :T] = norm[:T].transpose(1, 2, 0)
        x1_known = torch.from_numpy(x1)[None].to(self.device)

        keep = torch.zeros((1, 1, 1, self.max_T), dtype=torch.bool, device=self.device)
        if keep_first:
            keep[0, 0, 0, 0] = True
        step0 = x1_known[:, :, :, 1] - x1_known[:, :, :, 0]
        K = max(1, min(pin_tail, T - 2))
        for i in range(1, K + 1):
            keep[0, 0, 0, T - i] = True
            x1_known[:, :, :, T - i] = x1_known[:, :, :, 0] - float(i) * step0

        with torch.no_grad():
            out = self._inbetween(
                sample_model=self.sample_model, transport=self.sampler.transport,
                cond=cond, x1_known=x1_known, keep_mask=keep,
                motion_shape=(1, self.max_J, self.feature_len, self.max_T),
                num_steps=num_steps, device=self.device,
            )

        m = out[0][:n_joints].permute(2, 0, 1).cpu().numpy() * std[None] + mean[None]
        m = m[:T].astype(np.float32)
        if drop_last:
            m = m[:-1]
        return m, {"pin_frames": K, "frames_in": int(T), "frames_out": int(m.shape[0])}

    def close(self):
        import gc
        try:
            del self.encoder
        except AttributeError:
            pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
