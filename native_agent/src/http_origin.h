#ifndef C300X_HTTP_ORIGIN_H
#define C300X_HTTP_ORIGIN_H

/* 0 for an API request a browser sent for a page of another site: an
 * Origin that is not this host, or a body type a cross-site form or
 * no-cors fetch can send without a CORS preflight (never answered here).
 * Home Assistant sends no Origin and JSON bodies; the setup page is same
 * origin. NULL or "" means the header is absent. */
int c300x_http_cross_site_safe(const char *method, const char *origin, const char *host, const char *content_type);

#endif
