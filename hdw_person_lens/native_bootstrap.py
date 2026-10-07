# native_bootstrap.py
#
def preload_native_backends() -> None:
    # Windows/Python 3.13 native DLL guard:
    # PyTorch must be imported before PyQt6, otherwise torch\lib\c10.dll can fail with WinError 1114.
    import torch
    _ = torch.__version__
