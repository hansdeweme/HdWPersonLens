New persons database modules
person.schema.json  An example JSON Schema file describing a minimal person object that the form builder uses to create a data entry module. Adapt this based on the relevant domain of your photo collection.
persons.json	    An example flat file database of person properties defined in the JSON Schema. Replace the content with data on the people in the knowledge base of your photo collection. 
validate_persons.py	The validation script that uses person.schema.json to validate the data file persons.json
person_db_gui.py	The standalone module that contains the form builder that uses per-son.schema.json to generate the data entry form.  

The existing person recognition application
main.py	            The entry point of the application. It handles imports, applies warning filters, and boots the app
config.py	        Manages settings.json and shared constants used throughout the application.
ui.py	            Contains the main PyQt6 GUI, including the main window, menu actions, and the logging bridge.
ui_workers.py	    NEW Contains the main worker methods.
ui_dialogs.py	    NEW Contains the settings- & about-dialogs, but also the lookalikes-, identify-, KB-status- and media folders-report-dialogs. 

The encoder & recognition toolkit
reid_wrapper.py	    A trimmed-down full body person encoder.
face_encoder.py	    The face recognition-encoder.

The application functions building on the toolkit
kb.py	            Defines the knowledge base data model and worker methods for batch encoding.
recognize.py	    Holds the worker methods for batch recognition.

The API between application and the new persons database
person_db.py	    NEW Contains the interface class PersonDB

Settings shared by Recognition application and database modules 
settings.json	    Contains the location of the needed folders and the constants used for person recognition. 
