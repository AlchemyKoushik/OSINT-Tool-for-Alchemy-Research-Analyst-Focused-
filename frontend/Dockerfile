FROM nginx:1.27-alpine

WORKDIR /usr/share/nginx/html

COPY index.html /opt/osint/index.template.html
COPY styles.css ./styles.css
COPY favicon.ico ./favicon.ico
COPY location-catalog.json ./location-catalog.json
COPY ui ./ui
COPY react-trend-insight-cards ./react-trend-insight-cards
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.d/40-render-config.sh /docker-entrypoint.d/40-render-config.sh

RUN chmod +x /docker-entrypoint.d/40-render-config.sh

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
