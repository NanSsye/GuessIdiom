import json
import aiohttp
from loguru import logger
from typing import Optional
from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase
import tomllib
import os
import asyncio
import time
import uuid
import base64
from database.XYBotDB import XYBotDB
import sqlite3  # 直接在main.py中实现数据库功能

# 常量定义
XYBOT_PREFIX = "-----老夏的金库-----\n"
GAME_API_URL = "https://xiaoapi.cn/API/game_ktccy.php"
GAME_TIP = """🎮 看图猜成语游戏 🎮
发送"开始"或"猜成语"开始游戏！
发送"提示"获取成语提示！
发送"我猜 <你的答案>"提交答案！
发送"退出"结束游戏！
快来试试你的成语功底吧！😎"""
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "resources", "cache")

class GuessIdiomDB:
    def __init__(self):
        self.db_path = "data/guessidiom.db"  # 修改保存路径到data目录
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.ensure_connection()
        self.create_tables()

    def ensure_connection(self):
        """确保数据库连接是活跃的"""
        if not hasattr(self, 'conn') or self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def create_tables(self):
        """创建游戏统计表"""
        self.ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_stats (
            user_id TEXT PRIMARY KEY,
            play_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            total_points INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        self.conn.commit()

    def update_stats(self, user_id: str, points_earned: int, is_correct: bool = True):
        """更新用户统计数据"""
        self.ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO game_stats (user_id, play_count, correct_count, total_points, last_updated)
        VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            play_count = play_count + 1,
            correct_count = correct_count + ?,
            total_points = total_points + ?,
            last_updated = CURRENT_TIMESTAMP
        ''', (user_id, 1 if is_correct else 0, points_earned, 1 if is_correct else 0, points_earned))
        self.conn.commit()

    def get_leaderboard(self, limit: int = 10):
        """获取排行榜"""
        self.ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT user_id, play_count, correct_count, total_points 
        FROM game_stats 
        ORDER BY total_points DESC 
        LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

    def get_user_stats(self, user_id: str):
        """获取用户统计数据"""
        self.ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT play_count, correct_count, total_points 
        FROM game_stats 
        WHERE user_id = ?
        ''', (user_id,))
        return cursor.fetchone() or (0, 0, 0)

    def __del__(self):
        """确保在对象销毁时关闭连接"""
        if hasattr(self, 'conn') and self.conn is not None:
            self.conn.close()

class GuessIdiom(PluginBase):
    description = "看图猜成语插件"
    author = "老夏的金库"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        
        # 初始化数据库连接
        self.db = XYBotDB()
        self.game_db = GuessIdiomDB()  # 初始化游戏数据库
        
        # 添加关卡奖励配置
        self.level_rewards = {
            1: 20,
            2: 40,
            3: 60,
            4: 80,
            5: 100
        }
        
        self.game_sessions = {}  # {user_wxid: {"pic_path": str, "timeout_task": Task, "current_level": int}}
        
        with open("main_config.toml", "rb") as f:
            config = tomllib.load(f)
        self.admins = config["XYBot"]["admins"]

        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            logger.debug(f"缓存目录已创建或已存在: {CACHE_DIR}")
        except Exception as e:
            logger.error(f"创建缓存目录失败: {e}")
            raise

        try:
            with open("plugins/GuessIdiom/config.toml", "rb") as f:
                config = tomllib.load(f)
            plugin_config = config["GuessIdiom"]
            self.enable = plugin_config["enable"]
            self.commands = plugin_config["commands"]
            print(f"self.commands 的类型: {type(self.commands)}")
            self.game_timeout = 60
        except FileNotFoundError:
            logger.warning("config.toml 文件未找到，插件可能无法正常工作")
            self.enable = False
            self.commands = []
            self.game_timeout = 60

    def _get_nickname(self, message: dict) -> str:
        """获取用户昵称，如果不存在则返回用户ID"""
        return message.get("SenderNickname", message.get("SenderWxid", "用户"))

    @on_text_message(priority=60)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            logger.debug("插件未启用，跳过处理")
            return True

        content = message["Content"].strip()
        chat_id = message["FromWxid"]
        user_wxid = message["SenderWxid"]

        if content == "猜成语":
            # 获取用户战绩
            stats = self.game_db.get_user_stats(user_wxid)
            play_count, correct_count, total_points = stats
            user_nickname = await bot.get_nickname(user_wxid)

            # 获取排行榜前五名
            leaderboard = self.game_db.get_leaderboard(5)
            leaderboard_message = "🏆 猜成语积分排行榜 TOP5 🏆\n\n"
            if leaderboard:
                for rank, (wxid, play_count, correct_count, total_points) in enumerate(leaderboard, 1):
                    user_nickname = await bot.get_nickname(wxid)  # 获取每个用户的昵称
                    leaderboard_message += (f"第{rank}名: {user_nickname} - {total_points}积分 🎖️\n"
                                            f"游玩{play_count}次 | 猜对{correct_count}次 🥇\n"
                                            f"------------------------\n")
            else:
                leaderboard_message += "暂时还没有人玩游戏哦，快来试试吧！🎉"

            # 构建完整消息
            gameplay_message = (
                "🎮 看图猜成语游戏 🎮\n"
                "发送'开始'或'猜成语'开始游戏！🚀\n"
                "发送'提示'获取成语提示！💡\n"
                "发送'我猜 <你的答案>'提交答案！🤔\n"
                "发送'我的猜成语战绩'可查询战绩 📊\n"
                "发送'猜成语排行榜'可查询排行榜 🏅\n"
                "发送'退出'结束游戏！❌\n"
                "快来试试你的成语功底吧！😎\n\n"
            )

            user_stats_message = (
                f"你的战绩:\n"
                f"游玩次数: {play_count}次 🎮\n"
                f"猜对次数: {correct_count}次 ✅\n"
                f"总积分: {total_points}分 💰\n\n"
            )

            # 合并所有消息
            full_message = gameplay_message + user_stats_message + leaderboard_message

            # 发送合并后的消息
            await bot.send_text_message(chat_id, full_message)

            # 开始游戏
            success = await self.start_game(bot, message, chat_id, user_wxid)
            if success:
                return False
            else:
                return True

        elif content == "我的猜成语战绩":
            # 获取用户战绩
            stats = self.game_db.get_user_stats(user_wxid)
            play_count, correct_count, total_points = stats
            user_nickname = await bot.get_nickname(user_wxid)
            if play_count > 0:
                accuracy = (correct_count / play_count * 100)
                msg = (f"🎮 {user_nickname} 的猜成语战绩 🎮\n\n"
                       f"总计获得: {total_points}积分\n"
                       f"游玩次数: {play_count}次\n"
                       f"猜对次数: {correct_count}次\n"
                       f"正确率: {accuracy:.1f}%")
            else:
                msg = f"{user_nickname} 还没有玩过猜成语游戏哦，快来试试吧！"
            await bot.send_at_message(chat_id, XYBOT_PREFIX + msg, [user_wxid])
            return False

        elif content == "猜成语排行榜":
            # 获取排行榜前五名
            leaderboard = self.game_db.get_leaderboard(5)
            if leaderboard:
                leaderboard_message = "🏆 猜成语积分排行榜 TOP5 🏆\n\n"
                for rank, (wxid, play_count, correct_count, total_points) in enumerate(leaderboard, 1):
                    user_nickname = await bot.get_nickname(wxid)  # 获取每个用户的昵称
                    leaderboard_message += (f"第{rank}名: {user_nickname} - {total_points}积分\n"
                                            f"游玩{play_count}次 | 猜对{correct_count}次\n"
                                            f"------------------------\n")
                await bot.send_text_message(chat_id, leaderboard_message)
            else:
                await bot.send_text_message(chat_id, "暂时还没有人玩游戏哦，快来试试吧！")
            return False

        if content == "提示":
            await self.get_hint(bot, message, chat_id, user_wxid)
            return False

        if content == "退出":
            await self.end_game(bot, message, chat_id, user_wxid)
            return False

        if content.startswith("我猜 "):
            guess = content[3:].strip()
            await self.check_answer(bot, message, chat_id, user_wxid, guess)
            return False

        if user_wxid in self.game_sessions:
            await bot.send_text_message(chat_id, XYBOT_PREFIX + GAME_TIP)
            return False

        return True

    async def start_game(self, bot: WechatAPIClient, message: dict, chat_id: str, user_wxid: str):
        """开始新游戏"""
        # 如果已有游戏在进行，先取消之前的超时任务
        if user_wxid in self.game_sessions and "timeout_task" in self.game_sessions[user_wxid]:
            self.game_sessions[user_wxid]["timeout_task"].cancel()

        # 初始化游戏会话
        if user_wxid not in self.game_sessions:
            self.game_sessions[user_wxid] = {
                "current_level": 1,
                "hint_used": False,  # 添加提示使用标记
                "pic_path": None,
                "timeout_task": None,
                "answer": None,
                "hint": None
            }

        current_level = self.game_sessions[user_wxid]["current_level"]

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "msg": "开始游戏",
                    "id": user_wxid
                }
                
                async with session.get(GAME_API_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"API 请求失败: {resp.status}")
                        await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 游戏启动失败，请稍后再试！")
                        return False

                    text = await resp.text()
                    try:
                        data = json.loads(text)
                        logger.debug(f"API 返回内容: {json.dumps(data, indent=4, ensure_ascii=False)}")
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}, 响应内容: {text}")
                        await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 游戏启动失败，API 返回异常！")
                        return False

                    if data["code"] != 200:
                        logger.error(f"API 返回异常: {data}")
                        await bot.send_text_message(chat_id, XYBOT_PREFIX + f"🙅 游戏启动失败: {data.get('msg', '未知错误')}")
                        return False

                    pic_url = data["data"]["pic"]
                    pic_filename = f"{uuid.uuid4()}.jpg"
                    pic_path = os.path.join(CACHE_DIR, pic_filename)
                    
                    async with session.get(pic_url) as img_resp:
                        if img_resp.status != 200:
                            logger.error(f"图片下载失败: {img_resp.status}")
                            await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 图片加载失败，请稍后再试！")
                            return False
                        img_data = await img_resp.read()
                        with open(pic_path, "wb") as f:
                            f.write(img_data)
                        logger.debug(f"图片已保存至: {pic_path}, 大小: {len(img_data)} bytes")

                    # 将图片转换为 base64
                    with open(pic_path, "rb") as f:
                        img_bytes = f.read()
                        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                        logger.debug(f"Base64 数据长度: {len(img_base64)}")

                    # 发送图片
                    result = await bot.send_image_message(chat_id, img_base64)
                    logger.debug(f"发送图片结果: {result}")

                    # 发送游戏开始提示
                    await bot.send_at_message(
                        chat_id,
                        XYBOT_PREFIX + f"🎉 游戏开始啦！请看图猜成语！\n"
                        f"当前第{current_level}关\n"
                        f'发送"提示"获取线索，发送"我猜 <答案>"提交，发送"退出"结束游戏哦！',
                        [user_wxid]
                    )

                    # 保存答案和提示
                    self.game_sessions[user_wxid]["answer"] = data["data"]["answer"]
                    self.game_sessions[user_wxid]["hint"] = data["data"]["msg"]

                    # 设置新的超时任务
                    timeout_task = asyncio.create_task(
                        self.game_timeout_handler(bot, chat_id, user_wxid)
                    )
                    
                    # 更新游戏会话
                    self.game_sessions[user_wxid]["pic_path"] = pic_path
                    self.game_sessions[user_wxid]["timeout_task"] = timeout_task

                    return True

        except Exception as e:
            logger.exception(f"开始游戏失败: {e}")
            await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 游戏启动出错啦，请稍后再试！")
            return False

    async def get_hint(self, bot: WechatAPIClient, message: dict, chat_id: str, user_wxid: str):
        """提供渐进式提示"""
        if user_wxid not in self.game_sessions:
            await bot.send_at_message(chat_id, XYBOT_PREFIX + '🤔 你还没开始游戏哦！发送"开始"试试吧！', [user_wxid])
            return

        # 从游戏会话中获取答案
        answer = self.game_sessions[user_wxid].get("answer")
        if answer:
            # 提示为答案的第一个字
            hint = answer[0]  # 获取答案的第一个字
            await bot.send_at_message(chat_id, XYBOT_PREFIX + f'💡 提示来啦：{hint}\n快猜猜吧！', [user_wxid])
        else:
            await bot.send_at_message(chat_id, XYBOT_PREFIX + '🤔 目前没有可用的提示！', [user_wxid])

    async def check_answer(self, bot: WechatAPIClient, message: dict, chat_id: str, user_wxid: str, guess: str):
        """检查用户答案是否正确"""
        if user_wxid not in self.game_sessions:
            await bot.send_at_message(chat_id, XYBOT_PREFIX + '🤔 你还没开始游戏哦！发送"开始"试试吧！', [user_wxid])
            return

        current_level = self.game_sessions[user_wxid].get("current_level", 1)
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {"msg": f"我猜 {guess}", "id": user_wxid}
                async with session.get(GAME_API_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"API 请求失败: {resp.status}")
                        await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 答案检查失败，请稍后再试！")
                        return
                    text = await resp.text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}, 响应内容: {text}")
                        await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 答案检查失败，API 返回异常！")
                        return

                if data["code"] != 200:
                    logger.error(f"API 返回异常: {data}")
                    await bot.send_text_message(chat_id, XYBOT_PREFIX + f"🙅 答案检查失败: {data.get('msg', '未知错误')}")
                    return

                result_msg = data["data"]["msg"]
                answer = data["data"].get("answer", "未知答案")

                if "正确" in result_msg:
                    # 先发送当前关卡完成消息
                    reward_points = self.level_rewards[current_level]
                    self.db.add_points(user_wxid, reward_points)
                    # 更新游戏统计
                    self.game_db.update_stats(user_wxid, reward_points, True)
                    
                    await bot.send_at_message(
                        chat_id,
                        XYBOT_PREFIX + f'🎉 恭喜通过第{current_level}关！答案是：{answer}\n'
                        f'🎁 获得{reward_points}积分！\n'
                        f'准备开始第{current_level + 1}关，继续加油！',
                        [user_wxid]
                    )

                    # 更新关卡等级
                    if current_level < 5:
                        self.game_sessions[user_wxid]["current_level"] = current_level + 1
                        # 然后开始新的一关
                        await self.start_game(bot, message, chat_id, user_wxid)
                    else:
                        # 完成所有关卡
                        await bot.send_at_message(
                            chat_id,
                            XYBOT_PREFIX + f'🏆 恭喜你完成了所有关卡！\n发送"开始"重新挑战！',
                            [user_wxid]
                        )
                        # 清理游戏会话
                        if user_wxid in self.game_sessions:
                            self.game_sessions[user_wxid]["timeout_task"].cancel()
                            pic_path = self.game_sessions[user_wxid]["pic_path"]
                            if os.path.exists(pic_path):
                                os.remove(pic_path)
                            del self.game_sessions[user_wxid]
                else:
                    # 更新游戏统计（猜错）
                    self.game_db.update_stats(user_wxid, 0, False)
                    await bot.send_at_message(
                        chat_id,
                        XYBOT_PREFIX + f'❌ 猜错了！{result_msg}\n'
                        f'当前第{current_level}关，再想想,或者发送"提示"获取线索！',
                        [user_wxid]
                    )
        except Exception as e:
            logger.exception(f"检查答案失败: {e}")
            await bot.send_text_message(chat_id, XYBOT_PREFIX + "🙅 答案检查出错啦，请稍后再试！")

    async def game_timeout_handler(self, bot: WechatAPIClient, chat_id: str, user_wxid: str):
        """游戏超时处理，超时后删除图片"""
        await asyncio.sleep(60)  # 每关60秒
        if user_wxid in self.game_sessions:
            await bot.send_at_message(
                chat_id,
                XYBOT_PREFIX + "⏰ 本关超时啦！游戏结束！",
                [user_wxid]
            )
            pic_path = self.game_sessions[user_wxid]["pic_path"]
            if os.path.exists(pic_path):
                os.remove(pic_path)
                logger.debug(f"图片已删除: {pic_path}")
            del self.game_sessions[user_wxid]

    async def end_game(self, bot: WechatAPIClient, message: dict, chat_id: str, user_wxid: str):
        """结束游戏并清理资源"""
        if user_wxid not in self.game_sessions:
            await bot.send_at_message(chat_id, XYBOT_PREFIX + '🤔 你还没开始游戏哦！', [user_wxid])
            return

        self.game_sessions[user_wxid]["timeout_task"].cancel()
        pic_path = self.game_sessions[user_wxid]["pic_path"]
        if os.path.exists(pic_path):
            os.remove(pic_path)
            logger.debug(f"图片已删除: {pic_path}")
        del self.game_sessions[user_wxid]
            
        await bot.send_at_message(chat_id, XYBOT_PREFIX + '👋 游戏已结束，欢迎下次再来！', [user_wxid])
