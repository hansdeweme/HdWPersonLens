import numpy as np, face_recognition, dlib, cv2, sys
print("versions:", sys.version.split()[0], "numpy", np.__version__, "dlib", dlib.__version__, "cv2", cv2.__version__)
img_rgb  = np.zeros((100,100,3), np.uint8)
img_gray = np.zeros((100,100),   np.uint8)
face_recognition.face_locations(img_rgb,  model="hog")
face_recognition.face_locations(img_gray, model="hog")
print("RGB OK, GRAY OK")
