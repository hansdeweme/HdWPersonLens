# Read multiple Python files and combine them into a single text file
with open("recognized_person-app-and-persondb-codebase.txt", "w", encoding="utf-8") as output_file:
    for filename in [                     
                     "config.py", 
                     "face_encoder.py", 
                     "kb.py", 
                     "main.py",
                     "person_db.py", 
                     "person_db_gui.py",
                     "recognize.py",
                     "reid_wrapper.py", 
                     "ui.py", 
                     "ui_dialogs.py", 
                     "ui_workers.py",                      
                     "person.schema.json", 
                     "settings.json"]:  
        with open(filename, "r", encoding="utf-8") as input_file:
            content = input_file.read()
            output_file.write(f"--- Start of {filename} ---\n")
            output_file.write(content)
            output_file.write(f"\n--- End of {filename} ---\n\n")   