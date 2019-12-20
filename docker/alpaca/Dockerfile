FROM python:3.6.9

MAINTAINER alpaca.tunnel@gmail.com

RUN pip3 install aiohttp uvloop

RUN git clone https://github.com/AlpacaTunnel/alpaca-switch.git /opt/alpaca-switch

COPY entrypoint.sh /usr/bin/

CMD ["sh", "/usr/bin/entrypoint.sh"]
