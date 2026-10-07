# torchreid_extractor_pytorchDirectML.py
# Robust Torchreid extractor with DirectML support, AIN→GN swap, and CPU fallback.
from __future__ import annotations
from typing import Iterable, List, Optional
import numpy as np
from PIL import Image
import warnings
import torch
import torch.nn as nn
import torch.nn.functional as F
# torchvision is available in your env
from torchvision import transforms as T
# Try DirectML
try:
    import torch_directml as dml  # type: ignore
except Exception:
    dml = None


def _swap_in_with_gn(module: nn.Module) -> None:
    """
    Replace every InstanceNorm2d with GroupNorm(C groups) recursively.
    This makes AIN backbones run on DirectML.
    """
    for name, child in list(module.named_children()):
        if isinstance(child, nn.InstanceNorm2d):
            C = child.num_features
            gn = nn.GroupNorm(
                num_groups=C,
                num_channels=C,
                eps=child.eps,
                affine=child.affine,
            )
            if child.affine:
                with torch.no_grad():
                    gn.weight.copy_(child.weight)
                    gn.bias.copy_(child.bias)
            setattr(module, name, gn)
        else:
            _swap_in_with_gn(child)


class TorchreidBodyExtractor:
    """
    Minimal, dependable wrapper around Torchreid for body embeddings.

    - On DirectML: defaults to a DML-friendly backbone (osnet_x1_0).
      If the user forces AIN, we swap InstanceNorm2d→GroupNorm.
    - Preflights a dummy forward; if it fails, falls back to CPU automatically.
    - Uses torch.no_grad(), contiguous() and avoids non_blocking on DML.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[object] = None,
        height: int = 256,
        width: int = 128,
    ) -> None:
        self.height = int(height)
        self.width = int(width)

        # ---- Select device ----
        if device is not None:
            # Allow passing "cpu" | "cuda" | torch.device(...) | "dml"
            if isinstance(device, str) and device.lower() in {"dml", "directml"} and dml is not None:
                self.device = dml.device()  # DirectML device -> type "privateuseone"
            else:
                self.device = torch.device(device)
        else:
            # Default: prefer DirectML if available
            if dml is not None:
                self.device = dml.device()
            else:
                self.device = torch.device("cpu")

        self._is_dml = getattr(self.device, "type", "") in ("privateuseone", "dml")

        # ---- Choose model name (DML-friendly by default) ----
        if model_name is None:
            # AIN uses InstanceNorm2d which may fail on some DML stacks.
            model_name = "osnet_x1_0" if self._is_dml else "osnet_ain_x1_0"
        self.model_name = str(model_name)

        # ---- Build Torchreid model ----
        # Use build_model for best compatibility across versions.
        import torchreid  # imported late so we don't pull it unless needed

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            self.model = torchreid.models.build_model(
                self.model_name, num_classes=1, pretrained=True
            )

        # If user forced an AIN backbone on DML, swap IN→GN to make it work.
        if self._is_dml and "ain" in self.model_name.lower():
            _swap_in_with_gn(self.model)

        self.model.to(self.device).eval()

        # ---- Image transform (match ImageNet/Torchreid expectations) ----
        self.transform = T.Compose(
            [
                T.Resize((self.height, self.width), interpolation=T.InterpolationMode.BILINEAR, antialias=True),
                T.ToTensor(),  # HWC uint8 -> CHW float in [0,1]
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )

        # ---- Preflight forward to validate backend; fallback to CPU if needed ----
        self.backend = getattr(self.device, "type", "cpu")
        try:
            with torch.no_grad():
                dummy = torch.zeros(1, 3, self.height, self.width, device=self.device).contiguous()
                _ = self.model(dummy)  # run once
        except Exception as e:
            print(f"[ReID] DML preflight failed ({e}); switching to CPU.")
            self.device = torch.device("cpu")
            self._is_dml = False
            self.backend = "cpu"
            self.model.to(self.device).eval()
            with torch.no_grad():
                _ = self.model(torch.zeros(1, 3, self.height, self.width, device=self.device))

        # ---- One clear line so you can see what was chosen ----
        print(f"[ReID] Torchreid backend: {self.backend} (model={self.model_name})")

    # ---------- Core inference ----------
    def _forward_tensor(self, t: torch.Tensor) -> torch.Tensor:
        """Run model, return L2-normalized embeddings (N,D) on CPU (float32)."""
        with torch.no_grad():
            f = self.model(t)
            if isinstance(f, (list, tuple)):
                f = f[0]
            f = F.normalize(f, dim=1)
        return f.detach().cpu().to(dtype=torch.float32)

    def _ensure_device_tensor(self, image: Image.Image) -> torch.Tensor:
        """Image -> (1,C,H,W) float tensor on self.device."""
        t = self.transform(image.convert("RGB")).unsqueeze(0)
        # non_blocking only helps on CUDA; DML/CPU prefer False
        non_blocking = getattr(self.device, "type", "") == "cuda"
        return t.to(self.device, non_blocking=non_blocking).contiguous()

    def __call__(self, image: Image.Image) -> np.ndarray:
        """Extract a single (D,) float32 feature. Returns None-like empty if failure."""
        try:
            t = self._ensure_device_tensor(image)
            out = self._forward_tensor(t)
            return out.squeeze(0).numpy()
        except Exception as e:
            # If this was DML, try one-time fallback to CPU
            if self.backend != "cpu":
                print(f"[ReID] Runtime failed on {self.backend} ({e}); retrying on CPU.")
                self.device = torch.device("cpu")
                self.backend = "cpu"
                self._is_dml = False
                self.model.to(self.device).eval()
                try:
                    t = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device).contiguous()
                    out = self._forward_tensor(t)
                    return out.squeeze(0).numpy()
                except Exception as e2:
                    print(f"[ReID] CPU retry also failed: {e2}")
            return np.zeros((0,), dtype=np.float32)

    def extract_batch(
        self,
        images: Iterable[Image.Image],
        batch_size: int = 32,
        num_workers: int = 0,
    ) -> np.ndarray:
        """
        Vectorized extraction from an iterable of PIL images.
        Returns (N, D) float32, L2-normalized. Uses one retry on CPU if a DML error occurs.
        """
        # Ensure we can reuse on fallback
        if not isinstance(images, list):
            images = list(images)

        tensors: List[torch.Tensor] = []
        for im in images:
            if im is None:
                continue
            tensors.append(self.transform(im.convert("RGB")))

        if not tensors:
            return np.zeros((0, 0), dtype=np.float32)

        from torch.utils.data import DataLoader

        def _run() -> np.ndarray:
            loader = DataLoader(
                tensors,
                batch_size=batch_size,
                shuffle=False,
                num_workers=num_workers,
                # pin_memory only on CUDA; DML returns pinned-like tensors but PyTorch API
                # here is safer with False.
                pin_memory=(getattr(self.device, "type", "") == "cuda"),
                collate_fn=lambda x: torch.stack(x, dim=0),
            )
            feats_cpu: List[torch.Tensor] = []
            with torch.no_grad():
                for batch in loader:
                    batch = batch.to(self.device, non_blocking=False).contiguous()
                    f = self.model(batch)
                    if isinstance(f, (tuple, list)):
                        f = f[0]
                    f = F.normalize(f, dim=1)
                    feats_cpu.append(f.detach().cpu().to(dtype=torch.float32))
            return torch.cat(feats_cpu, dim=0).numpy()

        # First attempt on current backend
        try:
            return _run()
        except Exception as e:
            # If that was DML, retry once on CPU
            if self.backend != "cpu":
                print(f"[ReID] Batch run failed on {self.backend} ({e}); retrying on CPU.")
                self.device = torch.device("cpu")
                self.backend = "cpu"
                self._is_dml = False
                self.model.to(self.device).eval()
                try:
                    return _run()
                except Exception as e2:
                    print(f"[ReID] CPU batch retry failed: {e2}")
            return np.zeros((0, 0), dtype=np.float32)
