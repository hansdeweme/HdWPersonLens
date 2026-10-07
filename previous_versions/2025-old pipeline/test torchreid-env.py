# test torchreid-env.py
import torch, sys
from importlib.metadata import version, PackageNotFoundError

print("torch:", torch.__version__)
import torchvision
print("torchvision:", torchvision.__version__)

# torch-directml version + basic device check
try:
    import torch_directml as dml
    try:
        print("torch-directml:", version("torch-directml"))
    except PackageNotFoundError:
        print("torch-directml: <unknown> (try 'pip show torch-directml')")
    dev = dml.device()
    print("DML device:", dev)                       # e.g. privateuseone:0
    print("Tensor on DML:", torch.zeros(1, device=dev).device)
except Exception as e:
    print("DirectML import/device failed:", e)

# Optional: Torchreid smoke test on DML (use a non-AIN backbone)
try:
    import torchreid
    m = torchreid.models.build_model('osnet_x1_0', num_classes=1, pretrained=False).to(dev).eval()
    x = torch.randn(2, 3, 256, 128, device=dev)
    with torch.no_grad():
        y = torch.nn.functional.normalize(m(x), dim=1)
    print("Torchreid OK, output shape:", tuple(y.shape))
except Exception as e:
    print("Torchreid test failed:", e)
