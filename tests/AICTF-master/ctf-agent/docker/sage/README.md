# SageMath Remote API - 部署教程

## 概述

在远程服务器上部署 SageMath Docker 容器，通过 HTTP API 为 CTF Agent 的密码学 agent 提供 SageMath 计算能力。

## 架构

```
本地 CTF Agent  ──HTTP POST──→  远程服务器 Docker
(sage_exec tool)   /execute     (SageMath + Flask API)
```

---

## 一、远程服务器准备

### 1. 安装 Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录以生效

# 验证
docker --version
docker compose version
```

### 2. 上传文件

将 `docker/sage/` 目录下的三个文件上传到远程服务器：

```bash
# 方式一：scp
scp -r docker/sage/ user@your-server:/opt/sage-api/

# 方式二：git clone 整个项目后进入目录
cd /opt/sage-api/
```

文件清单：
- `Dockerfile` - Docker 镜像构建文件
- `sage_api.py` - Flask API 包装器
- `docker-compose.yml` - Docker Compose 配置

---

## 二、构建和启动

### 1. 构建镜像

```bash
cd /opt/sage-api/
docker compose build
```

> 首次构建需要下载 SageMath 基础镜像（约 2-3GB），耗时较长。

### 2. 配置 API Key（可选但推荐）

```bash
# 生成随机 API Key
export SAGE_API_KEY=$(openssl rand -hex 32)
echo "SAGE_API_KEY=$SAGE_API_KEY" > .env
echo "请保存此 API Key: $SAGE_API_KEY"
```

### 3. 启动服务

```bash
# 前台启动（调试用）
docker compose up

# 后台启动（生产用）
docker compose up -d
```

### 4. 验证服务

```bash
# 健康检查
curl http://localhost:8617/health

# 测试执行（无 API Key）
curl -X POST http://localhost:8617/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(factor(2024))"}'

# 测试执行（有 API Key）
curl -X POST http://localhost:8617/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"code": "print(factor(2024))"}'
```

期望输出：
```json
{"stdout": "2^3 * 11 * 23\n", "stderr": "", "exit_code": 0, "elapsed": 1.23}
```

---

## 三、CTF Agent 配置

### 1. 修改 config.yaml

在 `backend/config.yaml` 中添加：

```yaml
sage:
  url: "http://your-server-ip:8617/execute"
  api_key: "your-api-key-here"  # 如果没设置 API Key 则留空
  timeout: 120                   # 执行超时（秒）
```

### 2. 重启 CTF Agent

重启后端服务，`sage_exec` 工具将自动注册。

### 3. 验证工具注册

在前端 UI 中启动一个 crypto 题目，查看 agent 是否能调用 `sage_exec`。

---

## 四、防火墙配置

### 如果远程服务器有防火墙

```bash
# UFW
sudo ufw allow 8617/tcp

# iptables
sudo iptables -A INPUT -p tcp --dport 8617 -j ACCEPT
```

### 安全建议

- **生产环境必须设置 API Key**
- 如果不需要公网访问，可以限制 IP：
  ```bash
  sudo ufw allow from YOUR_LOCAL_IP to any port 8617
  ```
- 或使用 SSH 隧道：
  ```bash
  ssh -L 8617:localhost:8617 user@remote-server
  # 然后 config.yaml 中 url 设为 http://localhost:8617/execute
  ```

---

## 五、常用管理命令

```bash
# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 更新镜像
docker compose build --no-cache
docker compose up -d

# 查看资源使用
docker stats ctf-sage-api
```

---

## 六、故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| Connection refused | Docker 未启动 | `docker compose up -d` |
| 401 Unauthorized | API Key 不匹配 | 检查 .env 和 config.yaml 的 key |
| Execution timeout | 计算太复杂 | 增大 timeout 或优化算法 |
| OOM Killed | 内存不足 | 增大 docker-compose.yml 中 memory limit |
| sage not found | 镜像构建失败 | `docker compose build --no-cache` |

---

## 七、性能调优

### docker-compose.yml 参数

```yaml
environment:
  - SAGE_MAX_TIMEOUT=120    # 单次执行最大超时
  - SAGE_MAX_OUTPUT=100000  # 输出截断大小（字节）
deploy:
  resources:
    limits:
      memory: 4G    # 增大内存（格密码、大矩阵需要）
      cpus: '4.0'   # 增大 CPU
```

### gunicorn workers

修改 Dockerfile 中 CMD 的 `--workers` 参数：
- 单人使用：`--workers 2`
- 多人使用：`--workers 4`
