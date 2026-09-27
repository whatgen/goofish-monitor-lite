"""Run the settings page and the existing monitor in one container."""

import os
import sys
import threading

from admin_ui import serve
from goofish_monitor import main


if __name__ == "__main__":
    if not os.path.isfile(os.environ.get("GOOFISH_ADMIN_PASSWORD_FILE", "/app/private/admin_password.hash")):
        raise SystemExit("Admin password hash file is missing")
    threading.Thread(target=serve, name="settings-page", daemon=True).start()
    sys.argv = ["goofish_monitor.py", "monitor", "--config", os.environ.get("GOOFISH_CONFIG", "/app/private/config.local.json")]
    main()
