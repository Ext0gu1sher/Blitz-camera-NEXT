"""Keep application-level tests away from the real Windows user profile."""
import atexit
import os
import tempfile

_account = tempfile.TemporaryDirectory(prefix='blitzcam-tests-profile-',ignore_cleanup_errors=True)
os.environ['BLITZCAM_PROFILE_ROOT'] = _account.name
atexit.register(_account.cleanup)
