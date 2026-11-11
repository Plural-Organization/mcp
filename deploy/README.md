# Production deployment

`mcp.plrl.host` runs as a separate stateless container on the relay server. Cloudflared connects
to its loopback-only published port. It shares neither data nor privileges with the Plural relay
or accounts service.

```sh
docker build --platform linux/amd64 -t plural-mcp:VERSION .
docker save plural-mcp:VERSION | gzip | ssh relay 'gunzip | sudo docker load'

ssh relay sudo docker run -d \
  --name plural-mcp \
  --restart unless-stopped \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --publish 127.0.0.1:8081:8080 \
  plural-mcp:VERSION
```

Add this rule before the catch-all entry in `/etc/cloudflared-plural/config.yml`:

```yaml
  - hostname: mcp.plrl.host
    service: http://127.0.0.1:8081
```

The matching DNS record is a proxied CNAME from `mcp` to the tunnel's
`<tunnel-id>.cfargotunnel.com` address.
