from pathlib import Path


def load_tests(loader, tests, pattern):
    return loader.discover(
        str(Path(__file__).parent), pattern="test_*.py", top_level_dir=str(Path(__file__).parents[2])
    )
