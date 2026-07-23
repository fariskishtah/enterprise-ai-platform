FROM nginxinc/nginx-unprivileged:1.28.0-alpine

USER root
RUN apk upgrade --no-cache

COPY infrastructure/nginx/reverse-proxy.conf /etc/nginx/conf.d/default.conf
COPY infrastructure/nginx/routes.inc /etc/nginx/routes.inc

USER 101:101

EXPOSE 8080 8443

CMD ["nginx", "-g", "daemon off;"]
