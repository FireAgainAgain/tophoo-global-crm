# 局域网访问

默认 `python run.py` 仅允许本机访问。要让可信局域网内的设备访问，在项目根目录运行：

```bash
python run.py --host 0.0.0.0
```

在其他设备上访问 `http://<服务器局域网IP>:8002/`。按需允许防火墙在专用网络放行 TCP 8002。使用局域网 HTTP 时，`AUTH_COOKIE_SECURE=false` 才能继续使用登录 Cookie。正式对外部署请使用 HTTPS，见[部署说明](DEPLOYMENT.md)。
