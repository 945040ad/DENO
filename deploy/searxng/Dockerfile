# SearXNG for Cloud Run (docs/09 §5.3): the settings ship inside the image, since Cloud Run has no
# bind mounts. SEARXNG_SECRET comes from the environment.
FROM searxng/searxng:latest
COPY settings.yml /etc/searxng/settings.yml
