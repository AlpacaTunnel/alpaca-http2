#!/usr/bin/env python3

# Author: twitter.com/alpacatunnel

import logging
import argparse
import asyncio
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from libs.local_server import start_local
from libs.remote_server import start_remote

LOGFORMAT = '[%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(funcName)s()] - %(message)s'
VERSION = '1.0'

def main():
    parser = argparse.ArgumentParser(description='')
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Log Level, default INFO')
    parser.add_argument(
        '--role',
        choices=['local', 'remote'],
        default='local',
        help='Client or Server mode, default local')
    args = parser.parse_args()

    logging.basicConfig(format=LOGFORMAT, level=args.log_level)

    if args.role == 'local':
        start_local()
    else:
        start_remote()


if __name__ == '__main__':
    main()
