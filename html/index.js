var switch_worker = undefined;

window.onload = function() {
    document.getElementById("http2-url").value = document.URL + 'alpaca_url/';
    document.getElementById("ws-url").value = "ws://127.0.0.1:8080/";
}

function getDatetime() {
    let time = new Date().toISOString().slice(0, 23);
    return time.replace('T', ' ');
}

// print the log in index page
function printLog(msg) {
    let dated_msg = "[" + getDatetime() + '] ' + msg;
    let new_line = "<br>" + dated_msg;
    console.log(dated_msg);
    document.getElementById("console-log").innerHTML += new_line;
}

function cleanLog() {
    document.getElementById("console-log").innerHTML = "";
}

function startWorker() {
    if (typeof(switch_worker) != "undefined") {
        printLog('Worker has already started!');
        return;
    }

    let http2_url = document.getElementById("http2-url").value;
    let ws_url = document.getElementById("ws-url").value;

    switch_worker = new Worker("switch_worker.js");
    switch_worker.postMessage([http2_url, ws_url]);

    // print log message from worker
    switch_worker.onmessage = function(event) {
        printLog(event.data);
    };
}

function stopWorker() {
    if (typeof(switch_worker) == "undefined") {
        printLog('Worker is not running!');
        return;
    }

    switch_worker.terminate();
    printLog('Worker stopped.');
    switch_worker = undefined;
}
