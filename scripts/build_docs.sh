#!/bin/bash

set -e

rm -rf ./docs/build

pushd docs && make html
popd