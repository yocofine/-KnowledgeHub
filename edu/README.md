# 教辅知识库迁移工具（准备阶段归档）

**当前部署、更新与回滚说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。下面保留的是迁移前的准备阶段说明，不代表当前部署状态。**

当前基线为 Tencent/WeKnora `v0.8.2`，分支 `edu-migration`。使用 WeKnora 原生界面，不保留旧教辅前端。此目录是第一阶段的隔离部署、只读盘点和账号绑定工具，**不是已完成迁移的生产版**。

旧 `edu-rag-platform-server` 保持不动。没有推送 GitHub，没有连接生产数据库，也没有启动、替换服务器服务。

## 账号与权限方案

新账号由用户在 WeKnora 注册，不复制旧密码。`account-map.json` 保存“旧用户名 → 新邮箱”，已按用户提供的信息填入管理员绑定。它被 Git 忽略，不公开提交邮箱。其他旧用户缺少绑定时列为待处理，绝不归给管理员。

公共文档、规则、FAQ 放入独立团队空间，普通用户 viewer，管理员 owner/admin；FAQ 使用原生 FAQ 类型，不与文档混存。每个人（包括管理员）的个人话术保留原 owner_id，通过映射绑定到新 user_id。

注意：**团队空间的管理权限，不等于全系统管理员只看自己话术。原生知识库还支持分享和邀请。** 个人主空间必须只有本人，跨空间访问关闭；后续话术模块仍需针对分享、邀请、检索、导出、缓存及公开链接执行完整隔离约束与双账号测试，不能仅靠隐藏前端菜单。

`check-account` 只校验新邮箱、用户 ID、个人主空间、唯一 active owner。通过检查不代表完整隔离验收，更不会自动导入数据。

## 独立部署（先测试，不切换旧域名）

在新项目根目录执行，以下为 Linux 服务器命令：

```bash
python3 edu/setup.py init
python3 edu/setup.py check
docker compose --env-file edu/.env -f edu/compose.yml config --quiet
docker compose --env-file edu/.env -f edu/compose.yml pull
docker compose --env-file edu/.env -f edu/compose.yml up -d
docker compose --env-file edu/.env -f edu/compose.yml ps
```

`init` 生成独立随机凭据，已有配置拒绝覆盖。不输出秘密值；不要把 `docker compose config` 的完整输出发给别人，使用 `--quiet`。不要在已有数据库上重置 AES/JWT 等密钥。Linux 配置文件权限为 0600；Windows 还应自行限制目录 ACL。

默认只监听服务器回环地址：前端 `127.0.0.1:18081`、API `127.0.0.1:18080`。可以通过 SSH 隧道在自己的电脑访问，例如将本机 18081 转发到服务器 127.0.0.1:18081。旧 8080 服务、数据卷与域名不受影响；不要为了访问测试环境直接开放数据库/Redis/docreader 端口。

只有 app、frontend、docreader、PostgreSQL、Redis 五项服务。向量检索用 PostgreSQL，不启动 Milvus、etcd、MinIO、Ollama 或本地 MinerU。固定版本镜像；如果服务器拉取受限，可在 `edu/.env` 设置经过验证的自建镜像地址，不提供未经验证的公共代理。

五项服务内存上限合计约 4.125 GiB，并限制解析和后台并发。**这是资源约束，不是不会宕机的保证，也未经实际大文件压力测试。** 旧系统和新系统同时全负荷运行仍可能挤占 8G 内存；上线前检查 `docker stats`、磁盘、swap 和 OOM，批量导入先用小文件。容器触发上限也会导致任务失败，不能把重启当成功。Redis 使用 noeviction；容量不足需停止导入并处理积压，不能丢弃队列。

## 模型与解析配置

在原生界面配置远程模型：聊天沿用现有 API；embedding 选择阿里云 `text-embedding-v4` 并确认 1024 维；rerank 沿用远程 API。不要复制旧向量索引，应重新索引文档。模型 API Key 通过原生模型配置录入，不写入账号映射或快照。

PDF 知识库选择 **MinerU Cloud**（引擎 `mineru_cloud`），在原生解析器设置录入 MinerU API Key，选择 pipeline 或对应已开通模型。源码读取的是解析器设置 `mineru_api_key`，**不是**旧系统 `.env` 的 `MINERU_API_KEY`；仅复制旧环境变量不会生效。云端解析不需要本地 MinerU 容器；docreader 是原生通用格式解析服务，不等于本地 MinerU。先确认小 PDF 实际走云端引擎，再上传大文件。

初始环境只对本机开放，以便注册新邮箱账号。完成账号创建后将 `DISABLE_REGISTRATION=true`，执行 `setup.py check`，再重建 app。正式开放前还需 HTTPS 反向代理、备份、审计及安全验收；此目录没有修改现有 Nginx/证书/K8s。

## 旧数据只读导出

使用只读 MySQL 用户。先安装导出工具依赖：

```bash
python3 -m venv edu/.venv
edu/.venv/bin/pip install -r edu/requirements.txt
```

将源数据库 URL 安全放入环境变量 `EDU_SOURCE_DATABASE_URL`（不要将真实密码粘贴到聊天或提交 Git）。格式为 `mysql+pymysql://只读用户:URL编码密码@数据库地址:3306/旧库名`。在旧 MySQL 中执行只读一致性事务，导出固定字段白名单，不读取用户密码、系统 Key、会话或钉钉回调密文。

```bash
edu/.venv/bin/python edu/migration.py export --out edu/snapshots/legacy.json
python3 edu/migration.py inventory --snapshot edu/snapshots/legacy.json
python3 edu/migration.py plan --snapshot edu/snapshots/legacy.json --out edu/reports/plan.json
```

快照包含私人话术正文、规则、FAQ、分组及文件元数据和版本清单，**仍属敏感数据**，只能离线保管。它不含文件字节；原文件、预览图片和规则图片需要从旧存储单独备份并校验 SHA256。软删除记录保留在快照，但不列入有效内容迁移计划。任务中断的文件也必须核对原件，不能因未发布就丢失。

计划默认不执行写入。未知旧用户、重复邮箱、多人共用个人 tenant ID、无 owner 或字段变化会阻止或列出待处理，不自动猜测。聊天记录、历史审计与钉钉入库修订暂不导入，旧系统保留作为历史查询与回滚依据。

## 新账号身份校验

先登录该用户的**个人**空间，将其当前 JWT 临时放入 `EDU_WEKNORA_TOKEN`。不得使用管理员 Token 代替普通用户，也不要发送 Token 给别人。个人主空间 ID 从原生空间信息读取。

```bash
python3 edu/migration.py check-account --username admin --tenant-id 个人空间ID --base-url http://127.0.0.1:18080 --out edu/reports/admin-identity.json
```

成功报告记录新邮箱、user_id 和 personal_tenant_id，不记录 Token。只发送 GET 请求；禁止跳转以及向非本机 HTTP 地址发送 Token。后续导入前还需核对分享/邀请及公共空间成员角色。

## 后续迁移和切换门槛

| 教辅功能 | 本阶段状态 | 切换前要求 |
| --- | --- | --- |
| 新邮箱登录及原生界面 | 原生能力，部署尚未实测 | 新账号注册、模型配置、登录验证 |
| 文档和独立 FAQ | 已准备只读快照与迁移清单 | 原文件/图片导入、串行解析、检索与预览核验 |
| 私人话术 | owner 保留、邮箱映射与身份校验已实现 | 原生界面业务适配及完整隔离测试，之后才导入 |
| 规则通知与钉钉 | 旧功能仍在旧项目 | 富文本推送、管理员权限、群消息入库、幂等/版本/撤销适配 |
| 高频问题云 | 旧功能仍在旧项目 | 新会话统计与点击快速提问适配 |

先完成测试环境、双账号隔离、文档/FAQ/规则的数量及内容对账、小文件到大文件压力验证、回滚演练，再停止旧写入并切换域名。不能把“容器启动”当成“迁移完成”。不要运行 `down -v`、删除旧数据卷、覆盖旧项目或直接导入旧 MySQL SQL 到 PostgreSQL。

离线回归测试：

```bash
python3 -m unittest discover -s edu -p 'test_*.py' -v
```

上游参考：[WeKnora v0.8.2](https://github.com/Tencent/WeKnora/tree/v0.8.2)。
