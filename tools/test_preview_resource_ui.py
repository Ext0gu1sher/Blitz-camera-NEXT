"""Isolated resource lifecycle acceptance; never reads or controls a game process."""
from .test_preview_controls import main

if __name__ == '__main__':
    main('test_preview_resource_ui.cjs', launches=0)
