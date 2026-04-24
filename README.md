# 每日 CNS 文献微信简报 - 新手模板

这个项目每天自动做 5 件事：

1. 读取 Nature / Science / Cell 及常用子刊的 RSS。
2. 通过 PubMed 补充检索，防止部分 RSS 不稳定。
3. 按关键词筛选。如果不填关键词，就收集所有最新论文。
4. 自动去重，避免同一篇论文每天重复推送。
5. 生成 Markdown 简报，并通过 Server酱或企业微信机器人推送到手机。

## 你需要准备什么

- 一个 GitHub 账号
- 一个 Server酱 SendKey，或者企业微信机器人 Webhook
- 可选：一个兼容 OpenAI 格式的 LLM API，用来生成中文精简总结

## 推荐第一版：Server酱推送到微信

1. 打开 Server酱官网，微信扫码登录。
2. 进入「SendKey」页面，复制你的 SendKey。
3. 在 GitHub 仓库中依次点击：Settings -> Secrets and variables -> Actions -> New repository secret。
4. 新增 secret：

| Name | Value |
|---|---|
| SERVERCHAN_SENDKEY | 你复制的 SendKey |

## 可选：设置关键词

如果你只想看某些方向，例如单细胞、空间组学、CRISPR，可以新增：

| Name | Value |
|---|---|
| KEYWORDS | single-cell,spatial transcriptomics,CRISPR,CAR-T,organoid |

如果不设置 KEYWORDS，系统会尽量收集当天所有新论文。

## 可选：AI 中文总结

第一版可以先不接 AI，跑通微信推送最重要。

后续要接 AI 时，添加这三个 secrets：

| Name | 说明 |
|---|---|
| LLM_BASE_URL | 兼容 OpenAI 格式的接口地址，例如 https://api.example.com/v1 |
| LLM_API_KEY | 你的 API key |
| LLM_MODEL | 你要使用的模型名 |

## 手动运行一次

进入 GitHub 仓库：

Actions -> Daily Paper WeChat Digest -> Run workflow

如果成功，你会在手机微信/企业微信收到一条文献简报。

## 修改推送时间

文件位置：`.github/workflows/daily.yml`

默认是按 America/Los_Angeles 时区每天早上 8:30 运行：

```yaml
schedule:
  - cron: "30 8 * * *"
    timezone: "America/Los_Angeles"
```

如果你想改成北京时间早上 8:30：

```yaml
schedule:
  - cron: "30 8 * * *"
    timezone: "Asia/Shanghai"
```

## 推荐期刊列表

- Nature
- Nature Methods
- Nature Biotechnology
- Nature Medicine
- Nature Communications
- Science
- Science Advances
- Cell
- Cell Reports
- Cell Metabolism
- Cancer Cell
- Immunity
- Neuron
- Molecular Cell

## 注意

- 不要把 SendKey、Webhook、API key 写进代码。
- 不要批量下载全文 PDF。
- 先让自动推送跑通，再做网页、收藏、标签和推荐系统。
