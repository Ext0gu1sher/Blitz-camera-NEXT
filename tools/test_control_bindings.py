"""Isolated acceptance of editable shortcuts, persistence and actual flight input."""
from .test_preview_controls import main

if __name__ == '__main__':
    main('test_control_bindings.cjs', launches=0, unchanged=False)
