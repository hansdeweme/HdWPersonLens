# Torchreid body feature extractor with consistent L2-normalized outputs.
#
from __future__ import annotations
from typing import Iterable, List, Optional
import numpy as np
# only import torch and related modules at runtime when this file is used.
import torch
from torch.utils.data import DataLoader
from PIL import Image
from torchvision import transforms
# torchreid provides a wide range of pretrained ReID backbones
from torchreid import models


class TorchreidBodyExtractor:
    """
    Thin wrapper around a torchreid backbone to produce L2-normalized 1-D float32 embeddings.
    - __call__(PIL.Image) -> (D,) float32
    - extract_batch(Iterable[PIL.Image], batch_size=32) -> (N, D) float32
    - extract_paths(Iterable[str], batch_size=32) -> (N, D) float32
    """
    def __init__(
        self,
        model_name: str = "osnet_ain_x1_0",
        device: Optional[str] = None,
        height: int = 256,
        width: int = 128,
        use_inference_mode: bool = True,
    ) -> None:
        if device is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        # Build model
        if model_name not in models.__dict__:
            raise ValueError(f"Unknown model '{model_name}'. Available: {sorted(models.__dict__.keys())}")
        self.model = models.__dict__[model_name](pretrained=True)
        self.model.eval().to(self.device)

        # Preprocess consistent with torchreid
        self.transform = transforms.Compose([
            transforms.Resize((height, width), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        self.use_inference_mode = bool(use_inference_mode)

    # -----------------------------
    # Public API
    # -----------------------------

    # Extract a single body embedding. Returns shape (D,) float32, L2-normalized.
    def __call__(self, image: Image.Image) -> np.ndarray:
        t = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device, non_blocking=True)
        if self.use_inference_mode and hasattr(torch, "inference_mode"):
            ctx = torch.inference_mode()
        else:
            ctx = torch.no_grad()
        with ctx:
            feat = self.model(t)  # [1, D]
            feat = torch.nn.functional.normalize(feat, dim=1)
        return feat.squeeze(0).detach().cpu().numpy().astype("float32")

    # Vectorized extraction from a list/iterable of PIL images. Returns an array of shape (N, D) float32, L2-normalized.
    def extract_batch(self, images: Iterable[Image.Image], batch_size: int = 32, num_workers: int = 0) -> np.ndarray:
        tensors = []
        for im in images:
            if im is None:
                continue
            tensors.append(self.transform(im.convert("RGB")))
        if not tensors:
            return np.zeros((0, 0), dtype=np.float32)

        loader = DataLoader(
            tensors,
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            pin_memory=(self.device.type == "cuda"),
            collate_fn=lambda x: torch.stack(x, dim=0),
        )

        if self.use_inference_mode and hasattr(torch, "inference_mode"):
            ctx = torch.inference_mode()
        else:
            ctx = torch.no_grad()

        feats: List[torch.Tensor] = []
        with ctx:
            for batch in loader:
                batch = batch.to(self.device, non_blocking=True)
                f = self.model(batch)                              # [B, D]
                f = torch.nn.functional.normalize(f, dim=1)        # L2
                feats.append(f.detach().cpu())

        feats = torch.cat(feats, dim=0).numpy().astype("float32", copy=False)
        return feats

    #  Read images from paths and call extract_batch.
    def extract_paths(self, paths: Iterable[str], batch_size: int = 32, num_workers: int = 0) -> np.ndarray:
        imgs: List[Image.Image] = []
        for p in paths:
            try:
                imgs.append(Image.open(p).convert("RGB"))
            except Exception:
                continue
        return self.extract_batch(imgs, batch_size=batch_size, num_workers=num_workers)

    # Convenience for cosine similarity (on already L2-normalized features)
    @staticmethod
    def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    @staticmethod
    def euclid_dist(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.linalg.norm(a - b, ord=2))