import torch, torch_directml
dml = torch_directml.device()       # device object (not the string "dml")
a = torch.tensor([1]).to(dml); b = torch.tensor([2]).to(dml)
print((a+b).item())                 # -> 3 if DML is working
