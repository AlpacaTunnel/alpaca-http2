import asyncio
import os
import random
import time
import logging
from aiohttp import web
from copy import deepcopy

from .multiplexing import Multiplexing, BINARY_PADDING
from .ctrl_msg import CtrlMsg


HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-store',
}

logger = logging.getLogger(__name__)


class ResponseSession:
    def __init__(self,
            stream_id : int=None,
            mp_wrapper : Multiplexing=None,
            s5_writer=None,
            s5_reader=None,
            response=None,
            need_flush=False,
            last_flush=None,
            tasks=None):
        self.stream_id = stream_id
        self.mp_wrapper = mp_wrapper
        self.s5_writer = s5_writer
        self.s5_reader = s5_reader
        self.response = response
        self.need_flush = need_flush
        self.last_flush = last_flush
        self.tasks = tasks  # a list of coroutines, should clear when session ends

    def clean(self):
        if not self.tasks:
            return

        logger.debug(f'{self.stream_id}: clean tasks...')
        for task in self.tasks:
            try:
                task.cancel()
            except Exception:
                pass


def _get_s5_response(request_ctrl, stream_id, result=False, reason=None):
    if reason:
        logger.info(reason)

    ctrl = CtrlMsg(
        msg_type=CtrlMsg.TYPE_RESPONSE,
        address_type=request_ctrl.address_type,
        dst_addr=request_ctrl.dst_addr,
        dst_port=request_ctrl.dst_port,
        stream_id=stream_id,
        result=result,
        reason=reason)

    ctrl_str = ctrl.to_str()
    logger.info(ctrl_str)
    return ctrl_str.encode('utf-8')


async def _s5_connect(dst_addr, dst_port):
    try:
        future = asyncio.open_connection(dst_addr, dst_port)
        s5_reader, s5_writer = await asyncio.wait_for(future, timeout=10)
        logger.info('success connect to %s %s', dst_addr, dst_port)
        return s5_reader, s5_writer, None

    # except (asyncio.TimeoutError, ConnectionRefusedError) as e:
    except Exception as e:
        reason = f'error connect to {dst_addr}:{dst_port} {e.__class__.__name__}:{e}'
        return None, None, reason


async def _wait_response_stream(session: ResponseSession):
    # response object is False, so use `is None` here
    while session.response is None:
        logger.debug('response not ready, sleep 0.1s...')
        await asyncio.sleep(0.1)


async def _flush_h2(session: ResponseSession):
    """
    browser only reads the first chunk when the second chunk arrives,
    so send arbitrary data to flush browser buffer.
    """
    await _wait_response_stream(session)

    while True:
        if session.response is None:
            break

        if session.need_flush:
            if time.time() - session.last_flush > 0.01:
                s5_data = BINARY_PADDING + os.urandom(random.randint(100, 1000))
                h2_data = session.mp_wrapper.send(session.stream_id, s5_data)
                await session.response.write(h2_data)
                session.need_flush = False

        await asyncio.sleep(0.01)


async def _s5_to_h2(session: ResponseSession):
    """
    TODO: how to support TCP half-close?
    Easy solution: not support it at all. Close both sides of the TCP connection when any side closed.

    And 'half-open' should end up with closing.
    """
    await _wait_response_stream(session)

    while True:
        try:
            s5_data = await session.s5_reader.read(1400)
            logger.debug('got data in s5 ======> %s %s', len(s5_data), s5_data[:20].hex())
        except Exception as e:
            logger.info('socks5 read error for stream_id: %s %s:%s', session.stream_id, e.__class__.__name__, e)
            break

        h2_data = session.mp_wrapper.send(session.stream_id, s5_data)

        logger.debug('===333=== send data to h2 ======> %s %s', len(h2_data), h2_data[:20].hex())
        try:
            await session.response.write(h2_data)
        except ConnectionResetError:
            break
        except Exception as e:
            logger.warning(f'unexpected Exception: {e.__class__.__name__}: {e}')
            break

        session.need_flush = True
        session.last_flush = time.time()

        # EOF
        if not s5_data:
            break

    try:
        # write the last empty bytes to flush browser buffer
        await _inform_eof(session.response, session.mp_wrapper, session.stream_id)
        session.response = None
        session.s5_writer.close()
    except Exception:
        pass


async def _cancel_if_idle(session_pool, session, timeout=60):
    """
    Wait a timeout, if no binary request come from client, close this session (cancel the tasks).
    """
    await asyncio.sleep(timeout)
    if session.response is None:
        logger.debug(f'{session.stream_id}: no response attached to session')
        try:
            session.clean()
            session_pool.pop(session.stream_id)
        except Exception:
            pass


async def _close_http(response):
    # write_eof() to avoid Nginx error: "upstream prematurely closed connection"
    await response.write_eof()
    return response


async def _inform_eof(response, mp_wrapper, stream_id):
    # write EOF to close client connection
    h2_data = mp_wrapper.send(stream_id, b'')
    try:
        await response.write(h2_data)
    except Exception:
        pass


async def _handle_open_request(request, response):
    session_pool = request.app.session_pool
    mp_wrapper : Multiplexing = request.app.mp_wrapper

    ctrl = CtrlMsg()
    ctrl.from_str(await request.text())

    if ctrl.msg_type != CtrlMsg.TYPE_REQUEST:
        reason = f'unknown CtrlMsg: {ctrl.msg_type}'
        result = _get_s5_response(ctrl, 0, False, reason)
        await response.write(result)
        return await _close_http(response)

    logger.info('got request %s %s', ctrl.dst_addr, ctrl.dst_port)

    # TODO: To reduce delay, always return success to client before try to connect dst.
    # If connect failed, write EOF to client.
    s5_reader, s5_writer, reason = await _s5_connect(ctrl.dst_addr, ctrl.dst_port)

    if not s5_reader or not s5_writer:
        result = _get_s5_response(ctrl, 0, False, reason)
        await response.write(result)
        return await _close_http(response)

    stream_id = mp_wrapper.new_stream()
    result = _get_s5_response(ctrl, stream_id, True)

    session = ResponseSession(
        stream_id=stream_id,
        mp_wrapper=mp_wrapper,
        s5_writer=s5_writer,
        s5_reader=s5_reader,
        tasks=[])

    session_pool[stream_id] = session

    task1 = asyncio.ensure_future(_s5_to_h2(session))
    task2 = asyncio.ensure_future(_flush_h2(session))
    session.tasks.append(task1)
    session.tasks.append(task2)

    asyncio.ensure_future(_cancel_if_idle(session_pool, session))

    await response.write(result)
    return await _close_http(response)


async def _handle_binary_request(request, response):
    """
    Set Nginx proxy_read_timeout to a large number.
    Keep the first HTTP binary request as downward stream, don't close it until the socks5 source/dest closed.
    All following HTTP binary requests are only for upward data, and should be closed immediately.

    If the HTTP2 connection between Browser and Nginx has closed, but socks5 connections in local and remote
    are still active, the remote_server won't known until data come from dest, and the local_server won't known
    until a second POST. To solve this, the Browser should notify the local_server on HTTP2 broken.
    """
    session_pool = request.app.session_pool
    mp_wrapper = request.app.mp_wrapper

    h2_data = await request.read()
    logger.debug('===222=== got data from h2 ====> %s %s', len(h2_data), h2_data[:20].hex())
    stream_id, s5_data, left_data = mp_wrapper.receive(h2_data)
    if left_data:
        logger.warning('!!!!--2--!!!! ignore left data from h2 (may be padding?) ====> %s %s', len(left_data), left_data[:20].hex())

    session = session_pool.get(stream_id)

    if session is None:
        logger.info(f'unknown stream_id: {stream_id}')
        await _inform_eof(response, mp_wrapper, stream_id)
        return await _close_http(response)

    if not s5_data:
        logger.info('downstream closed for stream_id: %s', stream_id)
        try:
            session.s5_writer.close()
        except Exception:
            pass
        return await _close_http(response)

    # h2_to_s5
    try:
        session.s5_writer.write(s5_data)
    except Exception as e:
        logger.info('upstream closed for stream_id: %s %s', stream_id, e)
        session.response = None
        return await _close_http(response)

    # There is already an alive stream, close this one (response object is False, so use `is None` here).
    if session.response is not None:
        return await _close_http(response)

    session.response = response

    logger.info(f'{stream_id}: leave first request/response connection alive')
    while session.response is not None:
        await asyncio.sleep(1)

    logger.info(f'{stream_id}: no data anymore, close the connection')
    await response.write_eof()
    session_pool.pop(stream_id)
    await _cancel_if_idle(session_pool, session, 0)
    return await _close_http(response)


async def http_server_handler(request):
    status = 206
    if request.method.upper() == 'OPTIONS':
        status = 200
    if 'text/plain' in request.content_type.lower():
        status = 200

    headers = deepcopy(HEADERS)
    headers['Content-Type'] = request.content_type.lower()

    response = web.StreamResponse(
        status=status,
        reason='OK',
        headers=headers,
    )

    await response.prepare(request)

    if request.method.upper() == 'OPTIONS':
        return await _close_http(response)

    if 'text/plain' in request.content_type.lower():
        return await _handle_open_request(request, response)

    elif 'application/octet-stream' in request.content_type.lower():
        response.enable_chunked_encoding()
        return await _handle_binary_request(request, response)

    else:
        logger.warning('unknown content_type')
        return await _close_http(response)


def start_remote():

    app = web.Application()
    app.router.add_route('*', '/', http_server_handler)
    app.router.add_route('*', '/{tail:.*}', http_server_handler)

    app.mp_wrapper = Multiplexing(role='server')
    app.session_pool = {}

    web.run_app(app, host='0.0.0.0', port=8080)
