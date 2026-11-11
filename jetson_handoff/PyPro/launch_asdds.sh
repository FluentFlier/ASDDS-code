#!/bin/bash
# Terminal wrapper used by the ASDDS desktop icon.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/program_launcher.sh"
launcher_exit=$?

echo ""
if [ "$launcher_exit" -eq 0 ]; then
    echo "ASDDS launcher finished successfully."
else
    echo "ASDDS launcher finished with error code $launcher_exit."
fi
echo ""
read -rp "Press Enter to close this window..." _unused
exit "$launcher_exit"
