"""Isolated UI acceptance for preview transport, telemetry and held rear follow."""
from .test_preview_controls import main

if __name__ == '__main__':
    main('test_preview_details_ui.cjs', launches=0)
