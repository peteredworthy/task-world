#!/bin/bash
# Wrapper to bypass xcode-select issues
export DEVELOPER_DIR=""
exec /usr/bin/git "$@"
