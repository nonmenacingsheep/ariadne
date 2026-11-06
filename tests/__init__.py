# Nothing a test does may land in her real data: actions.log is her own record of what she did,
# and she reads it back as history (a test's clipboard "hello" once showed up there at 3 a.m.).
import os
import tempfile

_DATA = tempfile.TemporaryDirectory(prefix="ariadne2-tests-")
os.environ["XDG_DATA_HOME"] = _DATA.name
