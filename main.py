# main.py
#
# wrapper for the packaged main, allows to start the app with "py -3.13 main.py"
# instead of the installed package with "personlens" or "py -3.13 -m hdw_person_lens.main"

from hdw_person_lens.main import main

if __name__ == "__main__":
    raise SystemExit(main())