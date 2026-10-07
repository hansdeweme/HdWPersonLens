### Enhanced Batch Processing Script (batch_process.py)
import os
import face_recognition
import pickle
import torch
import cv2
import shutil
import numpy as np
import time
from fastreid.config import get_cfg
from fastreid.modeling import build_model
from fastreid.utils.checkpoint import Checkpointer

# Paths
input_folder    = "E:\\persons_unknown"
output_folder   = "E:\\persons_processed"
encoded_persons = "E:\\persons_dataset\\encodings.pkl"
model_path      = "G:\\recognize\\market_bot_R50.pth"  # Standard model path
config_path     = "G:\\recognize\\configs\\Market1501\\bagtricks_R50.yml"
# supported image-formats
VALID_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')

# Load the trained encodings
with open(encoded_persons, "rb") as f:
    persons = pickle.load(f)

# Set up FastReID model
cfg = get_cfg()
cfg.merge_from_file(config_path)
cfg.MODEL.DEVICE = "cpu"

reid_model = build_model(cfg)
Checkpointer(reid_model).load(model_path)
reid_model.eval()

# Function to extract body embedding
def extract_body_embedding(image_path):
    try:
        image = cv2.imread(image_path)
        if image is None:
            return None
        image = cv2.resize(image, (128, 256))
        image = torch.as_tensor(image.transpose(2, 0, 1)).unsqueeze(0).float()

        with torch.no_grad():
            embeddings = reid_model(image)
        return embeddings.cpu().numpy()[0]
    except Exception as e:
        print(f"Failed to extract body encoding from {image_path}: {e}")
        return None 

# Function to process an image file
def process_file(file_path):
    recognized_models = []
    # Process face recognition
    try:
        image = face_recognition.load_image_file(file_path)
        face_encodings = face_recognition.face_encodings(image)
        for face_encoding in face_encodings:
            matches = face_recognition.compare_faces(persons["face_encodings"], face_encoding)
            name = "Unknown"
            if True in matches:
                matched_idx = [i for (i, b) in enumerate(matches) if b]
                name_counts = {persons["face_names"][idx]: matches.count(True) for idx in matched_idx}
                name = max(name_counts, key=name_counts.get)
            recognized_models.append(name)
    except Exception as e:
        print(f"Face recognition error for {file_path}: {e}")

    # Process body recognition
    if reid_model is not None:
        body_embedding = extract_body_embedding(file_path)
        if body_embedding is not None:
            distances = [np.linalg.norm(known_emb - body_embedding) for known_emb in persons["body_encodings"]]
            if distances:
                min_dist = min(distances)
                if min_dist < 0.6:  # Threshold for ReID
                    name = persons["body_names"][distances.index(min_dist)]
                    recognized_models.append(name)
                else:
                    recognized_models.append("Unknown")
    # Log recognized models
    return file_path, recognized_models

# Function to process all files 
def process_folder():
    start_time = time.time()
    files_to_process = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS ):
                files_to_process.append(os.path.join(root, file))
    
    total_files = len(files_to_process)
    processed_files = 0
    for file_path in files_to_process:
        file_path, recognized_models = process_file(file_path)
        processed_files += 1  # Increment the processed files count
        # Show progress
        progress = (processed_files / total_files) * 100
        print(f"Progress: {progress:.2f}% ({processed_files}/{total_files})")
        # Save processed files
        if recognized_models:
            for name in recognized_models:
                dest_dir = os.path.join(output_folder, name)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy(file_path, os.path.join(dest_dir, os.path.basename(file_path)))
        else:
            dest_dir = os.path.join(output_folder, "Unknown")
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy(file_path, os.path.join(dest_dir, os.path.basename(file_path)))
    end_time = time.time()
    print(f"Batch processing completed in {end_time - start_time:.2f} seconds")

# Run the process
process_folder()