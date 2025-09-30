# FILE: file_utils.py

from pathlib import Path
import importlib_resources

def check_default_path(default_filename):
    """Checks default-defined path to a file."""
    filepath = importlib_resources.files("ichigo.calc.cacofoni.python_data") / default_filename
    if not filepath.is_file():
        raise FileNotFoundError(f"Default file not found in package: {filepath}")
    return filepath

def check_user_path(user_filepath):
    """Checks user-defined path to a file."""
    filepath = Path(user_filepath).expanduser().resolve()
    if not filepath.is_file():
        raise FileNotFoundError(f"User-supplied file not found: {filepath}")
    return filepath

def resolve_filepath(user_filepath, default_filename, silent):
    if user_filepath is None:
        filepath = check_default_path(default_filename)
        if not silent:
            print(f"Using default file: {filepath}\n")
    else:
        filepath = check_user_path(user_filepath)
        if not silent:
            print(f"Using user-provided file: {filepath}\n")
            
    return filepath