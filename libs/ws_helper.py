import logging
import asyncio
import aiohttp
from aiohttp import WSMsgType
import traceback

logger = logging.getLogger(__name__)


async def ws_connect(url, username=None, password=None, verify_ssl=True, headers=None):
    """
    Connect to the url, return the ws session.
    """

    retry_timeout = 2
    for _x in range(10):
        retry_timeout += 2

        try:
            if username and password:
                auth = aiohttp.BasicAuth(username, password)
            else:
                auth = None

            connector = aiohttp.TCPConnector(verify_ssl=verify_ssl, force_close=True)
            session = aiohttp.ClientSession(connector=connector)
            future = session.ws_connect(url, auth=auth, heartbeat=30, headers=headers)
            ws = await asyncio.wait_for(future, timeout=retry_timeout)
            logger.info('connected to %s' % url)
            # must return the session, otherwise the session will be deleted/closed.
            return ws, session

        except asyncio.TimeoutError:
            logger.info('connect to {} timeout, retry after {} second...'.format(url, retry_timeout))
            try:
                await session.close()
            except:
                pass
            continue

        except Exception:
            logger.info('connect to {} exception: {}'.format(url, traceback.format_exc()))
            logger.info('retry after {} second...'.format(retry_timeout))
            try:
                await session.close()
            except:
                pass
            await asyncio.sleep(retry_timeout)
            continue

    return None, None


async def ws_recv(ws):
    """
    Read from the ws session and return a BINARY/TEXT msg.
    Return None if ws is closed.
    """

    while True:
        if ws.closed:
            return None

        msg = await ws.receive()

        if msg.type in (WSMsgType.BINARY, WSMsgType.TEXT):
            return msg

        elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
            logger.info('error: {}'.format(msg))
            continue

        else:
            logger.info('unexpected message type: {}'.format(msg.type))
            continue


async def ws_send(ws, data, msg_type=WSMsgType.BINARY):
    """
    Send data to the ws session.
    """

    # If not return here, the send_bytes() will block all coroutines.
    if ws.closed:
        return None

    if msg_type == WSMsgType.BINARY:
        return await ws.send_bytes(data)

    elif msg_type == WSMsgType.TEXT:
        return await ws.send_str(data)
