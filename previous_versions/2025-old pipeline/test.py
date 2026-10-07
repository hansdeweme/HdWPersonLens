import torch, torchreid, numpy as np
import torch_directml as dml

dev = dml.device()          # DirectML device
m = torchreid.models.build_model('osnet_ain_x1_0', num_classes=1, pretrained=False).to(dev).eval()
x = torch.randn(4,3,256,128, device=dev)

with torch.no_grad():       # use no_grad, not inference_mode
    y = torch.nn.functional.normalize(m(x), dim=1)

print("device:", dev)
print("ok shape:", tuple(y.shape), "dtype:", y.dtype)