# Keep a developer's real backend/.env out of the test suite (see config.load_env_file).
import os as _os

_os.environ["TRUSTBREAK_LOAD_DOTENV"] = "0"
