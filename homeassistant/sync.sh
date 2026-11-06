#!/bin/bash
# Copies the checker package into the add-on build context (run before installing / committing).
set -euo pipefail
cd "$(dirname "$0")"
rm -rf ps_remote_helper/ps_remote_checker
rsync -a --exclude '__pycache__' ../ps_remote_checker ps_remote_helper/
echo "synced ps_remote_checker into ps_remote_helper/"
