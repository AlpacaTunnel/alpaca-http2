#!/bin/sh

set -e

ALPACA_LOG=/tmp/alpaca.log
ALPACA_BIN=/opt/alpaca-switch/main.py

[ -z $LOGLEVEL ] && LOGLEVEL=ERROR

echo > $ALPACA_LOG
nohup python3 -u $ALPACA_BIN --role remote --log-level $LOGLEVEL >> $ALPACA_LOG 2>&1 &

tail -f $ALPACA_LOG
