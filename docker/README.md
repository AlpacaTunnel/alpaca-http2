Deploy an Alpaca server and an Nginx server within Docker
=========================================================

# Requirements

Please install Docker and docker-compose first.

The nginx image is based on [steveltn/https-portal](https://github.com/SteveLTN/https-portal), it will auto request certificate from Let's Encrypt and auto renew it.


# Config

Edit `environment` in `docker-compose.yml` to configure.

The Nginx and Alpaca docker instances communicate by the docker bridge network. The Nginx instance can access the Alpaca server by domain name `alpaca`, since it's the Alpaca server's name in `docker-compose.yml`. Don't change it.

#### DOMAINS

The nginx configuration used here requires a domain name. Raw IP address is forbidden.

#### ALPACA_LOCATION

The `ALPACA_LOCATION` is the URL to access the Alpaca Proxy application, rename it to a random string to prevent from probing.

#### STAGE

Change `STAGE` for different environment:

- `local`: use a self-signed certificate
- `staging`: request a fake certificate from Let's Encrypt
- `production`: for a production environment

#### Volumes

You can put your own static files in `/var/www/vhosts/$YOUR_DOMAIN`, and copy the content from [alpaca-switch Javascript page](https://github.com/AlpacaTunnel/alpaca-switch/tree/master/html) into a subfolder. The subfolder name should be different from `ALPACA_LOCATION`, and also name it to a random string to prevent from probing.

#### Auth

There is no authentication by default, but you can add HTTP Basic Auth to your `ALPACA_LOCATION` and static files subfolder. Edit Nginx configuration `default.ssl.conf.erb` to add password, and also add your credential to the `fetch()` function in the `switch_worker.js` in the static files.


# Deploy

When the configurations are ready, deploy with this cmd:

```sh
docker-compose up --build -d
```

It will build the images, start an Nginx server with only HTTPS, and start an Alpaca server. After the cmd finished, you can test with the URI `https://server_domain/subfolder/`. If anything goes wrong, you can check the logs with `docker logs instance-name`.

That's it, thanks.
