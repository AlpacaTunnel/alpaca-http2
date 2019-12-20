alpaca-switch
=============

A SOCKS5 proxy over HTTP2, with the TLS fingerprint of any web browser and Nginx server. Inspired by [naiveproxy](https://github.com/klzgrad/naiveproxy).

# Architecture

User ⟶ (local Websockets/SOCKS5 server) ⟶ (local Browser) ⟶ (Censor) ⟶ (remote Nginx server) ⟶ (remote HTTP application) ⟶ (Internet)

The proxy consists of 4 parts, and upward data flow as below:

- local Websockets/SOCKS5 server: receive socks5 request, send to local Browser via Websockets.
- local Browser: receive Websockets message, send to remote Nginx server via HTTP2.
- remote Nginx server: receive HTTP2 POST, proxy to HTTP application.
- remote HTTP application: receive HTTP POST, parse as socks5 request.

And downward vice versa.

With Chrome App, the local Websockets server and local Browser can be merged into one (no Websockets needed in such an App), but since Chrome will remove App in the future, so the above workflow was introduced. And it not only works on Chrome, but also on Firefox, and other modern browsers as well.


# Usage

First configure and deploy the remote Nginx server and HTTP application into you server. You can use [Docker-compose](https://github.com/AlpacaTunnel/alpaca-switch/tree/master/docker) for help. Remember the `ALPACA_LOCATION` and `static files subfolder`.

Then start the local server with the cmd:

```sh
python3 main.py --role local
```

Then open a web browser in your local PC, goto the subfolder of your domain. In the page, change `Remote HTTP2(s) URL` to the value of `ALPACA_LOCATION`. Click `Start Worker` to establish Websockets connections to the local server.

Now you can use the socks5 proxy server listening at `127.0.0.1:1080`.
