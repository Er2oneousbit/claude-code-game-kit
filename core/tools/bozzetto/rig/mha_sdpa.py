# ---------------------------------------------------------------------------
# mha_sdpa.py
# Purpose : A stand-in for flash_attn.modules.mha.MHA in its cross-attention form, built on PyTorch's own
#           scaled_dot_product_attention, so UniRig's skin model runs without the flash_attn package (and without
#           Triton, which flash_attn pulls in through transformers). Same parameter names (Wq, Wkv, out_proj), so
#           UniRig's checkpoint loads into it unchanged.
# Usage   : in UniRig's src/model/unirig_skin.py replace
#               from flash_attn.modules.mha import MHA
#           with
#               try:
#                   from flash_attn.modules.mha import MHA
#               except ImportError:
#                   from mha_sdpa import MHA      # this file, copied next to unirig_skin.py or on PYTHONPATH
# Notes   : UniRig builds MHA(embed_dim, num_heads, cross_attn=True) with flash_attn's defaults, and those defaults
#           (use_flash_attn=False) run flash_attn's plain PyTorch CrossAttention, not its CUDA kernels: softmax(q k^T /
#           sqrt(d)) v. This file computes the same thing; only the cross-attention form is implemented.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import torch.nn as nn
import torch.nn.functional as F


class MHA(nn.Module):
    def __init__(self, embed_dim, num_heads, cross_attn=False, qkv_proj_bias=True, out_proj_bias=True,
                 softmax_scale=None, **unused):
        super().__init__()
        if not cross_attn:
            raise NotImplementedError("mha_sdpa.MHA only implements cross_attn=True (all UniRig uses)")
        if embed_dim % num_heads:
            raise ValueError("embed_dim must be divisible by num_heads")
        self.cross_attn = True
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.softmax_scale = softmax_scale
        self.Wq = nn.Linear(embed_dim, embed_dim, bias=qkv_proj_bias)
        self.Wkv = nn.Linear(embed_dim, 2 * embed_dim, bias=qkv_proj_bias)
        self.out_proj = nn.Linear(embed_dim, embed_dim, bias=out_proj_bias)

    def forward(self, x, x_kv=None, **unused):
        """x: (batch, q_len, embed); x_kv: (batch, kv_len, embed), defaults to x."""
        b, s, _ = x.shape
        h, d = self.num_heads, self.head_dim
        q = self.Wq(x).view(b, s, h, d).transpose(1, 2)
        kv = self.Wkv(x_kv if x_kv is not None else x)
        kv = kv.view(b, kv.shape[1], 2, h, d)               # flash_attn's "... (two hkv d)" layout
        k, v = kv[:, :, 0].transpose(1, 2), kv[:, :, 1].transpose(1, 2)
        out = F.scaled_dot_product_attention(q, k, v, scale=self.softmax_scale)
        return self.out_proj(out.transpose(1, 2).reshape(b, s, h * d))
