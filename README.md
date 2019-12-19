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
