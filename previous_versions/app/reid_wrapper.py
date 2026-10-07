# reid_wrapper.py
# trimmed down version of torchreid_extractor.py
from __future__ import annotations
import importlib, importlib.util, io, contextlib
from   typing import Optional, Iterable, List, Callable
from   PIL import Image
import numpy as np
import torch
from   torchvision import transforms

# Return the torchreid.models module, supporting canonical and legacy layouts.
def _import_models(quiet: bool = True, log_fn: Optional[Callable[[str], None]] = None):
    def _cap(modname: str):
        if not quiet:
            return importlib.import_module(modname)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            mod = importlib.import_module(modname)
        msg = buf.getvalue().strip()
        if msg and log_fn:
            log_fn(f"[ReID] {msg.splitlines()[-1]}")
        return mod

    if importlib.util.find_spec("torchreid") is None:
        raise ImportError("TorchReID not found. Install torchreid (>=1.4.0) or the GitHub repo.")

    # Try canonical then legacy
    for name in ("torchreid.models", "torchreid.reid.models"):
        if importlib.util.find_spec(name) is not None:
            if name != "torchreid.models" and log_fn:
                log_fn(f"[ReID] Using fallback module path: {name}")
            return _cap(name)

    # Last resort: import base and walk attributes
    pkg = _cap("torchreid")
    for attr_path in ("models", "reid.models"):
        obj = pkg
        ok = True
        for part in attr_path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                ok = False
                break
        if ok:
            if attr_path != "models" and log_fn:
                log_fn(f"[ReID] Using models via torchreid.{attr_path}")
            return obj

    raise ImportError("Could not import TorchReID models (tried torchreid.models and torchreid.reid.models).")

# Quiet, minimal feature extractor around TorchReID backbones:
# __call__(PIL.Image)                           -> (D,) float32 L2-normalized
# extract_batch(List[PIL.Image], batch_size=32) -> (N, D) float32 L2-normalized
# extract_paths(Iterable[str], batch_size=32)   -> (N, D) float32 L2-normalized
class TorchreidBodyExtractor:
    def __init__(self, model_name: str = "osnet_ain_x1_0", device: Optional[str] = None, height: int = 256, width: int = 128, quiet: bool = True, log_fn: Optional[Callable[[str], None]] = None,):
        self.model_name = model_name
        self.height, self.width = int(height), int(width)
        self.quiet = bool(quiet)
        self._log = log_fn
        if device is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        # Import models lazily and build the backbone
        models = _import_models(self.quiet, self._log)
        # Build model class directly (no repo-specific builders)
        Model = getattr(models, model_name, None)
        if Model is None:
            # some installs keep classes in __dict__
            Model = models.__dict__.get(model_name)
        if Model is None:
            avail = sorted([k for k, v in models.__dict__.items() if not k.startswith("_")])
            raise ValueError(f"Unknown model '{model_name}'. Available: {avail[:20]}...")
        # Quiet stdout while constructing (pretrained download line, etc.)
        if self.quiet:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                self.model = Model(pretrained=True)   # downloads weights if needed
            msg = buf.getvalue().strip()
            if msg and self._log:
                self._log(f"[ReID] {msg.splitlines()[-1]}")
        else:
            self.model = Model(pretrained=True)
        self.model.eval().to(self.device)
        # Use plain torchvision transforms; keep consistent with TorchReID training stats
        self.transform = transforms.Compose([
            transforms.Resize((self.height, self.width), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    # ---- public API ----
    def __call__(self, image: Image.Image) -> np.ndarray:
        t = self.transform(image.convert("RGB")).unsqueeze(0).to(self.device, non_blocking=True)
        with torch.inference_mode():
            f = self.model(t)  # shape [1, D]
            f = torch.nn.functional.normalize(f, dim=1)
        return f.squeeze(0).detach().cpu().numpy().astype("float32")

    def extract_batch(self, images: List[Image.Image], batch_size: int = 32, num_workers: int = 0) -> np.ndarray:
        # turn PILs into tensors
        tensors = [self.transform(im.convert("RGB")) for im in images]
        if not tensors:
            return np.zeros((0, 0), dtype=np.float32)
        # simple mini-batching, no DataLoader workers to avoid PIL/thread issues on Windows
        feats = []
        with torch.inference_mode():
            for i in range(0, len(tensors), batch_size):
                batch = torch.stack(tensors[i:i+batch_size], dim=0).to(self.device, non_blocking=True)
                f = self.model(batch)
                f = torch.nn.functional.normalize(f, dim=1)
                feats.append(f.detach().cpu())
        return torch.cat(feats, dim=0).numpy().astype("float32", copy=False)

    def extract_paths(self, paths: Iterable[str], batch_size: int = 32, num_workers: int = 0) -> np.ndarray:
        imgs: List[Image.Image] = []
        for p in paths:
            try:
                with Image.open(p) as im:
                    imgs.append(im.convert("RGB").copy())  # detach from file handle
            except Exception:
                continue
        return self.extract_batch(imgs, batch_size=batch_size, num_workers=num_workers)

    @staticmethod
    def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))
    @staticmethod
    def euclid_dist(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.linalg.norm(a - b, ord=2))
