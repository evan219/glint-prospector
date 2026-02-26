#!/bin/bash
set -e
sudo -E $(which python) -m playwright install-deps chromium
echo "Done."
