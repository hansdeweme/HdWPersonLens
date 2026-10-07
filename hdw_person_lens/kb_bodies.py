#kb_bodies.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# torchreid_extractor_pytorchDirectML.py
# Robust Torchreid extractor with DirectML support, AIN→GN swap, and CPU fallback.
from __future__ import annotations
from typing import Iterable, List, Optional
import numpy as np
import hashlib, json
import gc
from PIL import Image
import warnings
import torch
import torch.nn as nn
import torch.nn.functional as F
# torchvision is available in your env
# DirectML is for AMD machines only
# NVIDEA CUDA
from torchvision import transforms as T
# Try DirectML
try:
    import torch_directml as dml  # type: ignore
except Exception:
    dml = None

#-------------------------------
# Helpers
#--------------------------------
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

def _is_classifier_component(name: str) -> bool:
    """
    Torchreid's identity-classification head is not used when the
    model returns evaluation embeddings.

    Exclude only `classifier`; do not exclude `fc`, because OSNet's
    feature projection layer contributes to the embedding.
    """
    return (
        name == "classifier"
        or name.startswith("classifier.")
    )

def _embedding_state_sha256(
    model: nn.Module,
) -> str:
    """
    Hash only parameters and buffers that contribute to embeddings.
    The Torchreid classifier head is excluded because:
    - it is not used for evaluation embeddings;
    - it may be randomly initialized on each model construction.
    """
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items(), key=lambda item: item[0],):
        if _is_classifier_component(name):
            continue
        value = (tensor.detach().cpu().contiguous())
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":"),).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()

def _embedding_graph_sha256(model: nn.Module,) -> str:
    """
    Hash the module types that contribute to embeddings.
    This still detects meaningful architecture changes, including
    InstanceNorm2d being replaced with GroupNorm, while excluding
    the irrelevant classifier head.
    """
    digest = hashlib.sha256()
    for name, module in model.named_modules():
        if _is_classifier_component(name):
            continue
        module_type = (f"{module.__class__.__module__}." f"{module.__class__.__qualname__}")
        digest.update(f"{name}:{module_type}\n".encode("utf-8"))
    return digest.hexdigest()

#---------------------------------------------
#  Extractor Class
#=-------------------------------------------

class TorchreidBodyExtractor:
    """
    Minimal, dependable wrapper around Torchreid for body embeddings.
    - On DirectML: defaults to a DML-friendly backbone (osnet_x1_0).
      If the user forces AIN, we swap InstanceNorm2d→GroupNorm.
    - Preflights a dummy forward; if it fails, falls back to CPU automatically.
    - Uses torch.no_grad(), contiguous() and avoids non_blocking on DML.
    """

    def __init__(self, model_name: Optional[str] = "osnet_ain_x1_0", device: object | None = None, height: int = 256, width: int = 128,  norm_variant: str = "native_instance_norm", log_callback=None,) -> None:
        self.height = int(height)
        self.width = int(width)
        self.log_callback = log_callback
        # Note: prevent CUDA vs DirectML difference         
        norm_variant = str(norm_variant).strip().lower()
        allowed_variants = {"native_instance_norm", "groupnorm_compat",}
        if norm_variant not in allowed_variants:
            raise ValueError(
                f"Unsupported ReID normalization variant: "
                f"{norm_variant!r}. Expected one of "
                f"{sorted(allowed_variants)}."
            )
        self.norm_variant = norm_variant        

        # ---- Select device ----
        requested_device = (device.strip().lower() if isinstance(device, str) else device )
        if requested_device in {None, "", "auto"}:
            # Prefer native CUDA, then DirectML, then CPU.
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
            elif dml is not None:
                self.device = dml.device()
            else:
                self.device = torch.device("cpu")
        elif (isinstance(requested_device, str) and requested_device in {"dml", "directml"}):
            if dml is not None:
                # DirectML must use the device object returned by torch_directml.device().
                self.device = dml.device()
            elif torch.cuda.is_available():
                self._log("[ReID] DirectML requested but torch_directml is unavailable; using CUDA.")
                self.device = torch.device("cuda")
            else:
                self._log("[ReID] DirectML requested but torch_directml is unavailable; using CPU.")
                self.device = torch.device("cpu")
        elif isinstance(requested_device, torch.device):
            self.device = requested_device
        else:
            # Valid standard PyTorch strings: cpu, cuda, cuda:0, mps, etc.
            self.device = torch.device(requested_device)
        # IMPORTANT: define these before selecting the model.
        self.backend = getattr(self.device, "type", str(self.device),)
        self._is_dml = self.backend in {"privateuseone", "dml",}
        # Log immediately, because model creation or transfer could fail later.
        self._log(
            f"[ReID] Requested device={device!r}; "
            f"selected device={self.device}; "
            f"backend={self.backend}; "
            f"is_dml={self._is_dml}"
        )

        # ---- Choose model name ----
        if model_name is None:
            # AIN uses InstanceNorm2d, which may fail on DirectML.
            model_name = ("osnet_x1_0" if self._is_dml else "osnet_ain_x1_0")
        self.model_name = str(model_name)
        # ---- Build Torchreid model ----
        import torchreid
        self._log(f"[ReID] Building model " f"{self.model_name!r}...")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning, )
            self.model = torchreid.models.build_model(self.model_name, num_classes=1, pretrained=True,)
        # If AIN was explicitly selected on DirectML replace InstanceNorm with GroupNorm.
        if (self.norm_variant == "groupnorm_compat" and "ain" in self.model_name.lower()):
            self._log("[ReID] Applying canonical InstanceNorm2d→GroupNorm compatibility variant.")
            _swap_in_with_gn(self.model)                   
        self.weights_sha256 = (_embedding_state_sha256(self.model))
        self.module_graph_sha256 = (_embedding_graph_sha256(self.model))      
            
        # ---- Move model to selected device ----
        self._log(f"[ReID] Moving model to " f"{self.device}..." )
        self.model.to(self.device).eval()
        
        # ---- Image transform ----
        self.transform = T.Compose(
            [
                T.Resize((self.height, self.width), interpolation=(T.InterpolationMode.BILINEAR), antialias=True,),
                T.ToTensor(), T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225],),
            ]
        )

        # ---- Preflight forward ----
        self._log(f"[ReID] Running preflight on " f"{self.backend}..." )
        try:
            with torch.no_grad():
                dummy = torch.zeros(1, 3, self.height, self.width, device=self.device, ).contiguous()
                _ = self.model(dummy)
        except Exception as exc:
            self._log(f"[ReID] {self.backend} preflight failed: " f"{exc.__class__.__name__}: {exc}" )
            self._log("[ReID] Switching body extractor to CPU.")
            self.device = torch.device("cpu")
            self.backend = "cpu"
            self._is_dml = False
            self.model.to(self.device).eval()
            with torch.no_grad():
                dummy = torch.zeros(1, 3, self.height, self.width, device=self.device,)
                _ = self.model(dummy)
        self._log(
            f"[ReID] Torchreid ready: "
            f"backend={self.backend}, "
            f"device={self.device}, "
            f"model={self.model_name}"
        )

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
                self._log(f"[ReID] Runtime failed on {self.backend} ({e}); retrying on CPU.")
                self.device = torch.device("cpu")
                self.backend = "cpu"
                self._is_dml = False
                self.model.to(self.device).eval()
                try:
                    t = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device).contiguous()
                    out = self._forward_tensor(t)
                    return out.squeeze(0).numpy()
                except Exception as e2:
                    self._log(f"[ReID] CPU retry also failed: {e2}")
            return np.zeros((0,), dtype=np.float32)

    def compatibility_signature(self) -> dict:
        signature = {
            "schema_version": 2,
            "fingerprint_version": 2,
            "weights_scope": (
                "embedding_backbone_excluding_classifier"
            ),
            "model_name": self.model_name,
            "norm_variant": self.norm_variant,
            "module_graph_sha256": (
                self.module_graph_sha256
            ),
            "weights_sha256": self.weights_sha256,
            "input_height": self.height,
            "input_width": self.width,
            "interpolation": "bilinear",
            "antialias": True,
            "rgb": True,
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
            "output_l2_normalized": True,
        }
        serialized = json.dumps(signature, sort_keys=True, separators=(",", ":"),).encode("utf-8")
        signature["pipeline_id"] = hashlib.sha256(serialized).hexdigest()
        return signature

    def runtime_info(self) -> dict:
        # Diagnostic information. These fields do not define the embedding space and are not part of pipeline_id.
        return {
            "backend": self.backend,
            "device": str(self.device),
            "model_name": self.model_name,
            "norm_variant": self.norm_variant,
        }


    def extract_batch(self, images: Iterable[Image.Image], batch_size: int = 32, num_workers: int = 0,) -> np.ndarray:
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
                self._log(f"[ReID] Batch run failed on {self.backend} ({e}); retrying on CPU.")
                self.device = torch.device("cpu")
                self.backend = "cpu"
                self._is_dml = False
                self.model.to(self.device).eval()
                try:
                    return _run()
                except Exception as e2:
                    self._log(f"[ReID] CPU batch retry failed: {e2}")
            return np.zeros((0, 0), dtype=np.float32)

    def _log(self, message: str) -> None:
        if callable(self.log_callback):
            try:
                self.log_callback(str(message))
                return
            except Exception:
                pass
        print(str(message), flush=True)

    def close(self) -> None:
        model = getattr(self, "model", None)
        if model is not None:
            try:
                model.to("cpu")
            except Exception:
                pass

        self.model = None
        self.device = torch.device("cpu")
        self.backend = "cpu"
        self._is_dml = False

        try:
            gc.collect()
        except Exception:
            pass

        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# Compute cosine distance stats between two sets of embeddings
def _cosine_pair_stats(A: np.ndarray, B: np.ndarray) -> tuple[float | None, float | None]:
    """Return (avg_dist, min_dist) for cosine distance, or (None,None) if incompatible."""
    if A is None or B is None:
        return None, None
    if A.ndim != 2 or B.ndim != 2:
        return None, None
    if A.shape[1] != B.shape[1]:
        return None, None
    A_n = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-12)
    B_n = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-12)
    D = 1.0 - (A_n @ B_n.T)
    return float(D.mean()), float(D.min())
