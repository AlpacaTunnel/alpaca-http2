// don't include this js file in the html, otherwise the globals and functions will overlap
// let the Worker() to download this js file

var started = false;

// only call postMessage in a Worker, otherwise it triggers onmessage and cause infinite loop.
function limitInWorker() {
    if (! self instanceof DedicatedWorkerGlobalScope) {
        throw 'Not in DedicatedWorkerGlobalScope';
    }
}

// print the log in index page
function printLog(msg) {
    limitInWorker();
    postMessage(msg);
}

onmessage = function(event) {
    if (started) {
        printLog('Switch has already started!');
        return;
    }

    printLog('Remote HTTP2 URL: ' + event.data[0]);
    printLog('Local WebSocket URL: ' + event.data[1]);

    swtartSwitch(event.data[0], event.data[1]);

    started = true;
    printLog('Switch started...');
}

function swtartSwitch(remote_h2, local_ws) {
    let ws = new WebSocket(local_ws);

    ws.onopen = function (event) {
        printLog('WebSocket is open.')
    };

    ws.onclose = function(error) {
        printLog('Socket is closed, code: ' + error.code + ', reason: ' + error.reason);
        console.error(error);
    };

    ws.onerror = function(error) {
        printLog('Socket encountered error, check console log.');
        console.error(error);
        ws.close();
    };

    ws.onmessage = function (event) {
        switchMessage(event, remote_h2, ws);
    };
}

function getContentType(data) {
    if (data instanceof Blob) {
        return 'application/octet-stream';
    }
    return 'text/plain';
}

function switchMessage(event, remote_h2, ws) {
    fetch(
        remote_h2,
        {
            cache: 'no-store',
            method: 'POST',
            headers: {'Content-Type': getContentType(event.data)},
            body: event.data
        }
    ).then(function (response) {
        if (response.headers.get('Content-Type').includes('text/plain')) {
            response.text().then(function (text) { ws.send(text); });
            return;
        }

        pumpBinaryStream(response.body.getReader(), ws, undefined);
    });
}

// copy and duplicate the stream_id, so the local_server can known the id without full data.
function pumpBinaryStream(reader, ws, stream_id) {
    reader.read().then(function (result) {
        // 1) If the stream is only for upward data, the response should be empty,
        //    and the `stream_id` == "undefined" when it closed.
        // 2) If the stream is for downward data (usually the first binary stream),
        //    when it closed, should write empty data to inform SOCKS5 client to close.
        //    This empty chunk may duplicate, but it's nessary if stream was closed unexpectedly.
        if (result.done) {
            if (typeof(stream_id) != "undefined") {
                // 4-bytes-stream-id + 4-bytes-data-length + 0-bytes-empty-data, see Multiplexing
                let empty_chunk = concatTypedArrays(stream_id, new Uint8Array([0, 0, 0, 0]));
                let empty_chunk_with_id = concatTypedArrays(stream_id, empty_chunk);
                ws.send(empty_chunk_with_id);
            }
            return;
        }

        const chunk = result.value;

        // the first chunk must begin with stream_id.
        if (typeof(stream_id) == "undefined") {
            // the first chunk should have at least 4 bytes. if not, make it fail.
            if (chunk.length < 4) {
                printLog('Error: First chunk is less than 4 bytes, this connection will be ignored.');
                return;
            }
            stream_id = chunk.slice(0, 4);
        }

        let chunk_with_id = concatTypedArrays(stream_id, chunk);
        ws.send(chunk_with_id);

        // following chunks may not start with stream_id, let the Python Websocket server to handle it.
        pumpBinaryStream(reader, ws, stream_id);
    });
}

// a, b: TypedArray of same type
function concatTypedArrays(a, b) {
    var c = new (a.constructor)(a.length + b.length);
    c.set(a, 0);
    c.set(b, a.length);
    return c;
}
