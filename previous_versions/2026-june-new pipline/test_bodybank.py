# test_bodybank.py
import json
import pickle

from kb_bodies import TorchreidBodyExtractor

with open(r".\persons_dataset\encodings.pkl", "rb") as file:
    bank = pickle.load(file)

stored = bank.get("metadata", {}).get("body_pipeline", {})

extractor = TorchreidBodyExtractor(
    model_name="osnet_ain_x1_0",
    norm_variant="native_instance_norm",
    device="auto",
)

runtime = extractor.compatibility_signature()

print("\nSTORED:")
print(json.dumps(stored, indent=2, sort_keys=True))

print("\nRUNTIME:")
print(json.dumps(runtime, indent=2, sort_keys=True))

print("\nDIFFERENCES:")
for key in sorted(set(stored) | set(runtime)):
    if stored.get(key) != runtime.get(key):
        print(f"{key}:")
        print(f"  bank:    {stored.get(key)!r}")
        print(f"  runtime: {runtime.get(key)!r}")