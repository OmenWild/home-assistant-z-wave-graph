#!/bin/bash
set -e

cp /z-wave-graph.html /config/www
cp /shell_commands_z-wave-graph.yaml /config/shell_commands/z-wave-graph.yaml

python3 z-wave-graph.py
