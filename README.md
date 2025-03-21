# XYBotV2 插件 - 看图猜成语 🎮

## 简介
由老夏的金库倾情打造，一款让你在微信上也能玩看图猜成语的小插件。斗图之余，还能涨姿势，简直yyds！😎

<img src="https://github.com/user-attachments/assets/a2627960-69d8-400d-903c-309dbeadf125" width="400" height="600">

## 特点
- 玩法简单：发送“开始”或配置的指令即可开始游戏。
- 贴心提示：发送“提示”获取成语线索。
- 积分排行：支持查看猜成语积分排行榜。
- 战绩查询：可以查看自己的猜成语战绩。
- 难度递增：总共5关，难度逐渐增加。

## 使用方法
1.  安装插件，配置好`config.toml`文件。
2.  在微信群里@机器人，发送指令开始游戏。
    -   开始游戏: `开始` 或 `config.toml`里配置的指令。
    -   获取提示: `提示`
    -   提交答案: `我猜 <你的答案>`
    -   退出游戏: `退出`
    -   查看排行榜: `猜成语排行榜`
    -   查看个人战绩: `我的猜成语战绩`

## 配置
在`plugins/GuessIdiom/config.toml`中进行配置：
```toml
[GuessIdiom]
enable = true  # 是否启用插件
commands = ["猜成语"] # 启动游戏的指令


## 依赖
-   `aiohttp`
-   `loguru`
-   `tomllib` (Python 3.11+)
-   `WechatAPI`
-   `utils`
-   `database`

## 注意事项
-   请确保机器人已正确配置并连接到微信。
-   缓存图片会保存在`resources/cache`目录下。

**给个 ⭐ Star 支持吧！** 😊

**开源不易，感谢打赏支持！**

![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)
