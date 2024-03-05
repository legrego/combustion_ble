#!/bin/bash

set -e

rm -rf ./build/

echo "Running ruff..."
ruff ./combustion_ble

echo "Running mypy..."
mypy ./combustion_ble

echo "Running isort..."
isort ./combustion_ble

echo "Running black..."
black ./combustion_ble