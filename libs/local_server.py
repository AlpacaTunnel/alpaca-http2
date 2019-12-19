import socket
import struct
import time
import random
import traceback
import asyncio
import os
import logging
from json.decoder import JSONDecodeError
from aiohttp import web, WSMsgType

from .socks5 import Socks5Parser
from .ws_helper import ws_connect, ws_recv, ws_send
from .multiplexing import Multiplexing, BINARY_PADDING, byte2int
from .ctrl_msg import CtrlMsg

# set to CRITICAL to prevent logging too many "Unhandled exception"
logging.getLogger('aiohttp').setLevel('CRITICAL')

logger = logging.getLogger(__name__)


class RequestSession:
    def __init__(self, stream_id=None, send_buffer=None, recv_q=None, recv_buffer=None):
        self.stream_id = stream_id
        self.send_buffer = send_buffer
        self.recv_q = recv_q
        self.recv_buffer = recv_buffer


async def _s5_prepare(s5_conn, s5_reader, s5_writer):

    s5_buffer = b''
    for _x in range(20):
        s5_buffer += await s5_reader.readexactly(1)
        greeting = s5_conn.receive_greeting(s5_buffer)
        if greeting == Socks5Parser.PARSE_DONE:
            break
    else:
        raise Exception('wrong socks5 greeting message')

    greeting_reply = s5_conn.send_greeting()
    s5_writer.write(greeting_reply)

    s5_buffer = b''
    for _x in range(100):
        s5_buffer += await s5_reader.readexactly(1)
        s5_request = s5_conn.receive_request(s5_buffer)
        if s5_request == Socks5Parser.PARSE_DONE:
            break
    else:
        raise Exception('wrong socks5 request message')

    # after s5_conn.receive_request(), should save the addr/port in s5_conn
    address_type, dst_addr, dst_port = s5_conn.address_type[0], s5_conn.dst_addr, s5_conn.dst_port

    if address_type == Socks5Parser.ADDRESS_TYPE_IPV4:
        dst_addr = socket.inet_ntop(socket.AF_INET, dst_addr)

    elif address_type == Socks5Parser.ADDRESS_TYPE_IPV6:
        dst_addr = socket.inet_ntop(socket.AF_INET6, dst_addr)

    elif address_type == Socks5Parser.ADDRESS_TYPE_DOMAIN:
        dst_addr = dst_addr.decode()

    dst_port = struct.unpack('!H', dst_port)[0]

    return address_type, dst_addr, dst_port


def _request_equal(a, b):
    return a.dst_addr == b.dst_addr and a.dst_port == b.dst_port and a.address_type == b.address_type


def _pop_result(result_list, request_ctrl):
    if len(result_list) > 1000:
        raise Exception('too many unhandled results, raise for debug')

    for result_str in result_list:
        result = CtrlMsg()
        try:
            result.from_str(result_str)
        except JSONDecodeError:
            logger.error(f'failed to decode response: {result_str}')
            result_list.remove(result_str)
            return

        if result.msg_type != CtrlMsg.TYPE_RESPONSE:
            logger.error(f'got unknown response {result_str}')
            result_list.remove(result_str)
            return

        if _request_equal(result, request_ctrl):
            result_list.remove(result_str)
            return result


async def _wait_result(result_list, request_ctrl):
    response : CtrlMsg = None
    while response is None:
        response = _pop_result(result_list, request_ctrl)
        logger.debug('wait response...')
        await asyncio.sleep(0.1)
    return response


async def _s5_server(s5_reader, s5_writer, upstream_q, result_list, session_pool):

    s5_conn = Socks5Parser()

    address_type, dst_addr, dst_port = await _s5_prepare(s5_conn, s5_reader, s5_writer)

    request_ctrl = CtrlMsg(
        msg_type=CtrlMsg.TYPE_REQUEST,
        stream_id=0,
        address_type=address_type,
        dst_addr=dst_addr,
        dst_port=dst_port
    )

    ctrl_str = request_ctrl.to_str()
    upstream_q.put_nowait((WSMsgType.TEXT, ctrl_str))
    logger.info(ctrl_str)

    # TODO: add timeout
    response = await _wait_result(result_list, request_ctrl)

    if not response.result:
        logger.info(f'request failed, reason: {response.reason}')
        server_data = s5_conn.send_failed_response(1)
        s5_writer.write(server_data)
        s5_writer.close()
        return

    if response.stream_id in session_pool:
        logger.info(f'will overwrite conflict stream_id: {response.stream_id}')

    server_data = s5_conn.send_success_response()
    s5_writer.write(server_data)

    session = RequestSession(
        stream_id=response.stream_id,
        send_buffer=bytearray(),
        recv_q=asyncio.Queue(),
        recv_buffer=bytearray(),
    )

    session_pool[response.stream_id] = session

    task1 = asyncio.ensure_future(_buffer_to_ws(response.stream_id, session.send_buffer, upstream_q))
    task2 = asyncio.ensure_future(_ws_to_s5(response.stream_id, session.recv_q, s5_writer))

    # _s5_to_ws
    while True:
        try:
            s5_data = await s5_reader.read(8192)
        except Exception as e:
            logger.warning(f'read socks5 error of stream_id: {response.stream_id} {e}')
            break

        # use shadow copy to avoid change the id of `send_buffer`
        session.send_buffer[:] = session.send_buffer[:] + s5_data[:]

        # EOF
        if not s5_data:
            # _buffer_to_ws() can not detect EOF, because empty bytes are omitted.
            # should sleep more than in _buffer_to_ws() to wait real data sent.
            await asyncio.sleep(0.1)
            ws_data = Multiplexing().send(response.stream_id, b'')
            upstream_q.put_nowait((WSMsgType.BINARY, ws_data))
            break

    logger.debug(f'The request ended: {response.stream_id} {ctrl_str}')
    try:
        task1.cancel()
    except Exception:
        pass
    try:
        task2.cancel()
    except Exception:
        pass


async def _buffer_to_ws(stream_id, send_buffer, upstream_q):
    """
    On remote side, each request is sent from Nginx to the remote_server via HTTP/1.1.
    Nginx translate HTTP2 to HTTP/1.1.
    
    Client may send two requests in a very short time, they will reach Nginx in order.
    But the remote_server may receive them in disorder. (Better to put the remote_server and Nginx on the same host.)

    One solution is to add sequence number to each request (in Multiplexing), which is complicated.
    Another solution is to add a delay between each request to reduce the change of disorder, just like below.

    If data is big, such as upload file, there still may have problem.
    """
    while True:
        if send_buffer:
            ws_data = Multiplexing().send(stream_id, bytes(send_buffer))
            send_buffer[:] = b''
            upstream_q.put_nowait((WSMsgType.BINARY, ws_data))
        await asyncio.sleep(0.001 * random.randint(5, 15))


async def _ws_to_s5(stream_id, recv_q, s5_writer):
    while True:
        s5_data = await recv_q.get()

        try:
            s5_writer.write(s5_data)
        except Exception as e:
            logger.warning(f'stream_id: {stream_id} {e}')
            break

        # EOF
        if not s5_data:
            break

    try:
        s5_writer.close()
    except Exception as _e:
        pass


async def _ws_binary_handler(session_pool, ws_data):
    if len(ws_data) < 4:
        raise Exception('Got partial data from ws')

    stream_id = byte2int(ws_data[0:4])
    recv_buffer = session_pool[stream_id].recv_buffer

    # use shadow copy to avoid change the id of `recv_buffer`
    recv_buffer[:] = recv_buffer[:] + ws_data[4:]

    while True:
        stream_id, s5_data, left_data = Multiplexing().receive(bytes(recv_buffer))
        if stream_id == Multiplexing.IncompleteReadError:
            return

        if stream_id not in session_pool:
            logger.info(f'unknown stream_id: {stream_id}')
            return

        recv_buffer[:] = left_data
        logger.debug(f'received stream_id: {stream_id}, data length: {len(s5_data)}, {s5_data[:20].hex()}, left_data: {len(left_data)}')

        if s5_data.startswith(BINARY_PADDING):
            logger.debug('got keepalive/padding data, skip')
            continue

        # ws_to_s5
        recv_q = session_pool[stream_id].recv_q
        recv_q.put_nowait(s5_data)

        # # EOF
        # if not s5_data:
        #     session_pool.pop(stream_id)


async def _s5_to_ws(upstream_q, ws):
    while True:
        msg_type, s5_data = await upstream_q.get()
        if msg_type == WSMsgType.TEXT:
            logger.debug('===111=== send data from s5 >>>> %s', s5_data)
        else:
            logger.debug('===111=== send data from s5 >>>> %s %s', len(s5_data), s5_data[:20].hex())

        await ws_send(ws, s5_data, msg_type)


async def ws_server_handler(request):
    if request.app.occupied:
        return web.Response(text="Only one connection allowed", status=429)

    peer = request.transport.get_extra_info('peername')
    ws = web.WebSocketResponse(heartbeat=30)

    try:
        await ws.prepare(request)
        request.app.occupied = True
        logger.info(f'new session connected from {peer}')

        task = asyncio.ensure_future(_s5_to_ws(request.app.upstream_q, ws))

        while True:
            ws_msg = await ws_recv(ws)
            if not ws_msg:
                break

            if ws_msg.type == WSMsgType.TEXT:
                request.app.result_list.append(ws_msg.data)
                logger.debug('response data: %s', ws_msg.data)

            elif ws_msg.type == WSMsgType.BINARY:
                logger.debug('===444=== got response data from ws =====> %s %s', len(ws_msg.data), ws_msg.data[:20].hex())
                await _ws_binary_handler(request.app.session_pool, ws_msg.data)

            else:
                logger.info(f'got unknown type: {ws_msg.type}')

    except Exception as e:
        logger.info(f'Error: got Exception: {e}, details: {traceback.format_exc()}')

    finally:
        try:
            task.cancel()
        except Exception as e:
            logger.info(f'failed to cancel task {e}')

        await ws.close()
        logger.info(f'session from {peer} is closed')
        request.app.occupied = False

        return ws


def start_socks5_server(host, port, upstream_q, result_list, session_pool):

    s5_task = asyncio.start_server(
        lambda r, w: _s5_server(r, w, upstream_q, result_list, session_pool),
        host,
        port,
    )

    asyncio.ensure_future(s5_task)
    logger.info(f'Started socks5 server at {host}:{port}')


def start_local():
    app = web.Application()
    app.router.add_get('/', ws_server_handler)
    app.router.add_get('/{tail:.*}', ws_server_handler)

    app.occupied = False  # only allow one connection
    app.session_pool = {'stream_id': RequestSession()}
    app.upstream_q = asyncio.Queue()
    app.result_list = []

    start_socks5_server('0.0.0.0', 1080, app.upstream_q, app.result_list, app.session_pool)

    web.run_app(app, host='0.0.0.0', port=8080)

    loop = asyncio.get_event_loop()
    loop.run_forever()
