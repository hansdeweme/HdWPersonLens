# where_torch.py
import os

torch_home = os.path.expanduser(
    os.getenv(
        "TORCH_HOME",
        os.path.join(
            os.getenv(
                "XDG_CACHE_HOME",
                "~/.cache",
            ),
            "torch",
        ),
    )
)

checkpoint = os.path.join(
    torch_home,
    "checkpoints",
    "osnet_ain_x1_0_imagenet.pth",
)

print("Torch home:", torch_home)
print("Expected checkpoint:", checkpoint)
print("Exists:", os.path.isfile(checkpoint))