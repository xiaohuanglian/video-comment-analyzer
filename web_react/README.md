# 评论工作台前端

普通使用：在项目根目录双击 `run.command`（Mac）或 `run.bat`（Windows）。界面和 API 共用 `http://127.0.0.1:8766`。

## 开发

在根目录运行 `./run_web_dev.sh`；另开终端：

```bash
cd web_react
npm ci
npm run dev
```

打开 `http://localhost:5173`，`/api` 自动代理到后端。

## 发布界面

```bash
npm run build
```

`dist/` 由后端提供，支持刷新 `/collect`、`/insight` 等页面。更新源码后需重新构建，再重启后端。

## 检查

```bash
npx tsc -b --noEmit
npm run lint
npm run test:ci
npm run build
```

入口为新手首页；帮助页解释流程和常见问题。三步工作流保留人工启动分析、逐条审核和受控发送。
