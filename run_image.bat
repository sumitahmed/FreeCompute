@echo off
chcp 65001 > nul
python -m harness.cli.main image %*
