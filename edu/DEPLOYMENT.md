# WeKnora 教辅部署版

基于 Tencent/WeKnora v0.8.2，保留上游版权与许可证，使用原生 Vue/TDesign 界面和独立教辅扩展。

## 数据与权限

迁移新邮箱账号，不复制旧密码。账号映射、密码和 API Key 不提交 Git。按用户选择，user1 和 Tilley 不迁入，其话术不归给管理员。当前有效数据为 12 个文件、管理员 3 条话术、5 条规则。独立 FAQ 库保留；旧 3 条 FAQ 都已删除，不恢复。

原件和预览共 28 项已备份并校验 SHA256。软删除数据、旧用户、聊天和审计历史保留在旧站及数据库备份，不冒充新账号的数据。

文档与检索底座是 WeKnora app、PostgreSQL/ParadeDB、Redis、docreader。轻量 edu-bridge 只提供话术、规则同步、机器人设置及个人问题云，不加载本地模型。

私人话术使用原生 JWT 验证后的 user_id 查询、编辑、删除；SQL 始终包含 owner_id，管理员也无跨用户例外。话术不放入共享知识库，不能通过原生知识库分享或文档检索泄漏。切换账号清空页面和表单，响应禁止缓存。

规则所有登录用户可读，只有管理员可修改和推送。规则保存后通过持久化待同步状态写入 WeKnora 检索库；服务 Key 仅授权规则知识库。普通团队成员应设为 viewer，以保持公共文档和 FAQ 只读。

钉钉 Webhook 和加签密钥已加密迁移，GET 仅返回是否配置。保留颜色、加粗、倾斜和换行转换，迁移历史规则不重发群聊。**群里 @机器人入库属于应用机器人 Stream 功能，不是群 Webhook 功能，须另外配置应用机器人与发送人授权。** 原生 IM 平台提供 Stream 设置，不能以现有 Webhook 代替入库凭据。

问题云按当前用户汇总，不泄漏其他用户的提问；点击问题后进入原生新对话并填入输入框。旧聊天历史不直接导入新会话。

## 资源配置

聊天、阿里云 text-embedding-v4（1024 维）、rerank 和 MinerU Cloud 使用 API，不搬本地 BGE/MinerU/Ollama 权重。PDF、Word、PPT、图片选择 mineru_cloud；docreader 是通用格式服务，不是本地 MinerU 容器。

上传并发 1，后台 core 并发 1，embedding 批次 8、调用池 1，迁移按文件串行。设置内存/CPU 上限、日志轮转和健康检查，但不保证永远不会失败或宕机，仍须检查 API 限额、超时、磁盘和 OOM。

v0.8.2 的 embedding/rerank 装配器使用 source=remote；阿里云通过 parameters.provider=aliyun 表达，不能只设 source=aliyun。

## 更新部署

```bash
cd /root/WeKnora-edu
git pull --ff-only
# 不得在已有数据库上重生成 AES/JWT/扩展加密密钥
python3 edu/setup.py check
docker compose --env-file edu/.env -f edu/compose.yml -f edu/compose.mirror.yml -f edu/compose.bridge.yml config --quiet
docker compose --env-file edu/.env -f edu/compose.yml -f edu/compose.mirror.yml -f edu/compose.bridge.yml up -d
```

前端必须先在构建机编译并发布 dist，不能只更新源码便声称前端已更新：

```bash
cd frontend
npm ci --registry=https://registry.npmmirror.com --no-audit --no-fund
VITE_IS_DOCKER=true VITE_FRONTEND_COMMIT=$(git rev-parse --short HEAD) npm run build
```

扩展目前复用服务器已有 edu-rag-platform-api 的 Python 运行镜像，但只启动新的 edu_bridge.main，不连接旧数据库、不导入旧模型。新服务器可另用 Python 3.12 + FastAPI/httpx/cryptography/uvicorn 构建轻量镜像。现有运行镜像不要误删。

扩展数据卷 edu-weknora_edu-data 声明为 external，首次部署须 docker volume create；SQLite 文件和加密设置应一起备份。静态目录只读，官方入口脚本只可写公共 config.js。

生产 Nginx 使用现有证书代理到回环 18081；18080/18082、数据库和 Redis 不公开。公开注册关闭，管理员使用原生邀请/创建用户功能。继承的上游 CI 需要腾讯 DockerHub secrets，私有仓库暂禁无效自动构建，配置自己的 CI 后再启用。

## 验收及回滚

```bash
python3 -m unittest discover -s edu -p 'test_*.py'
cd frontend
npm run type-check
npm test -- src/stores/uploadTasksCore.test.ts src/stores/uploadQueue.test.ts
```

acceptance.py 验证真实 JWT 双账号隔离，验收身份随后停用。native_import.py 核验原件并保存新 ID，解析 completed 后才处理下一文件；登录过期会续期，不重复上传。search_acceptance.py 检查检索与流式回答。

cutover.py prepare 备份旧全库、环境、Compose 和 Nginx。switch 只替换本站代理，nginx -t 失败会恢复旧配置。旧项目、镜像和数据卷保留，不执行 down -v。

```bash
python3 /root/WeKnora-edu/edu/cutover.py rollback
```

回滚会先恢复旧服务再恢复旧代理，不删除新数据。新站上线后的新增写入不会自动回填旧站，回滚前须另行备份与对账。私密交接文件不得公开分享。
