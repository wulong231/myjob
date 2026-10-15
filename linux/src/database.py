"""SQLite 数据库管理模块
====================
提供播放历史、收藏、播放列表、播放位置记忆等数据持久化。
"""
import sqlite3
import threading
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ==================== 视频标签预设分类 ====================

# 预设分类顺序
VIDEO_TAG_CATEGORIES: List[str] = ["系列", "属性", "风格", "自定义"]

# 各分类下的常见预设标签
VIDEO_TAG_PRESETS: Dict[str, List[str]] = {
    "系列": ["教程系列", "游戏实况", "番剧", "纪录片", "电影", "连载中", "已完结"],
    "属性": ["高清", "蓝光", "4K", "1080P", "HDR", "杜比", "60帧", "原声"],
    "风格": ["搞笑", "热血", "治愈", "悬疑", "科幻", "奇幻", "日常", "励志", "感人"],
    "自定义": [],
}

# 标签默认分类
VIDEO_TAG_DEFAULT_CATEGORY = "自定义"


class Database:
    """SQLite 数据库管理类（线程安全）"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = Path.cwd() / ".bili23" / "database"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "bili23.db")
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.info(f"数据库已初始化: {self.db_path}")

    def _init_db(self):
        """创建数据库表"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.executescript('''
                CREATE TABLE IF NOT EXISTS play_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    file_name TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration INTEGER DEFAULT 0,
                    position_ms INTEGER DEFAULT 0,
                    played_at TIMESTAMP,
                    play_count INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    file_name TEXT,
                    title TEXT,
                    artist TEXT,
                    added_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_name TEXT,
                    title TEXT,
                    artist TEXT,
                    position INTEGER DEFAULT 0,
                    added_at TIMESTAMP,
                    UNIQUE(playlist_id, file_path),
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS playback_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    position_ms INTEGER DEFAULT 0,
                    updated_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS music_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    cover_color TEXT DEFAULT '#667EEA',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS music_folder_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_name TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration INTEGER DEFAULT 0,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(folder_id, file_path),
                    FOREIGN KEY (folder_id) REFERENCES music_folders(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_play_history_played_at ON play_history(played_at);
                CREATE INDEX IF NOT EXISTS idx_favorites_added_at ON favorites(added_at);
                CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist_id ON playlist_items(playlist_id);
                CREATE INDEX IF NOT EXISTS idx_playback_positions_file_path ON playback_positions(file_path);
                CREATE INDEX IF NOT EXISTS idx_music_folder_items_folder_id ON music_folder_items(folder_id);

                CREATE TABLE IF NOT EXISTS video_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '自定义',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(file_path, tag)
                );

                CREATE INDEX IF NOT EXISTS idx_video_tags_file_path ON video_tags(file_path);
                CREATE INDEX IF NOT EXISTS idx_video_tags_tag ON video_tags(tag);
            ''')
            conn.commit()
            # 旧库迁移：为已存在的 video_tags 表补充 category 字段（需先于 category 索引创建）
            self._migrate_video_tags_table(conn)
            # category 字段就绪后再创建索引，避免旧库无该字段时报错
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_video_tags_category ON video_tags(category)"
            )
            conn.commit()
            logger.debug("数据库表创建/验证完成")
        except sqlite3.Error as e:
            logger.error(f"初始化数据库表失败: {e}", exc_info=True)
            raise

    def _migrate_video_tags_table(self, conn: sqlite3.Connection):
        """数据库迁移：若 video_tags 表缺少 category 字段则补充"""
        try:
            cursor = conn.execute("PRAGMA table_info(video_tags)")
            columns = [row[1] for row in cursor.fetchall()]
            if "category" not in columns:
                conn.execute(
                    "ALTER TABLE video_tags ADD COLUMN category TEXT NOT NULL DEFAULT '自定义'"
                )
                conn.commit()
                logger.info("video_tags 表已迁移：新增 category 字段")
        except sqlite3.Error as e:
            logger.error(f"迁移 video_tags 表失败: {e}", exc_info=True)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全）"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            logger.debug(f"数据库连接已创建: {self.db_path}")
        return self._conn

    @staticmethod
    def _row_to_dict(row) -> Optional[Dict[str, Any]]:
        """将 sqlite3.Row 转换为字典"""
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    # ==================== 播放历史 ====================

    def add_play_history(self, file_path, file_name, title, artist, album,
                         duration, position_ms):
        """添加或更新播放历史记录"""
        try:
            with self._lock:
                conn = self._get_conn()
                now = datetime.now().isoformat()
                conn.execute(
                    '''
                    INSERT INTO play_history
                        (file_path, file_name, title, artist, album,
                         duration, position_ms, played_at, play_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(file_path) DO UPDATE SET
                        file_name = excluded.file_name,
                        title = excluded.title,
                        artist = excluded.artist,
                        album = excluded.album,
                        duration = excluded.duration,
                        position_ms = excluded.position_ms,
                        played_at = excluded.played_at,
                        play_count = play_history.play_count + 1
                    ''',
                    (file_path, file_name, title, artist, album,
                     duration, position_ms, now)
                )
                conn.commit()
                logger.debug(f"播放历史已记录: {file_path}")
        except sqlite3.Error as e:
            logger.error(f"添加播放历史失败: {e}", exc_info=True)

    def get_play_history(self, limit=100, days=None) -> List[Dict[str, Any]]:
        """获取播放历史记录"""
        try:
            with self._lock:
                conn = self._get_conn()
                if days is not None:
                    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                    cursor = conn.execute(
                        '''SELECT * FROM play_history
                           WHERE played_at >= ?
                           ORDER BY played_at DESC LIMIT ?''',
                        (cutoff, limit)
                    )
                else:
                    cursor = conn.execute(
                        '''SELECT * FROM play_history
                           ORDER BY played_at DESC LIMIT ?''',
                        (limit,)
                    )
                rows = cursor.fetchall()
                return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"获取播放历史失败: {e}", exc_info=True)
            return []

    def clear_play_history(self, before_days=None):
        """清理播放历史；None=清空全部，N=清理N天前的记录"""
        try:
            with self._lock:
                conn = self._get_conn()
                if before_days is None:
                    conn.execute("DELETE FROM play_history")
                    logger.info("已清空全部播放历史")
                else:
                    cutoff = (datetime.now() - timedelta(days=before_days)).isoformat()
                    cursor = conn.execute(
                        "DELETE FROM play_history WHERE played_at < ?",
                        (cutoff,)
                    )
                    logger.info(f"已清理 {cursor.rowcount} 条 {before_days} 天前的播放历史")
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"清理播放历史失败: {e}", exc_info=True)

    def get_play_count(self, file_path) -> int:
        """获取指定文件的播放次数"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT play_count FROM play_history WHERE file_path = ?",
                    (file_path,)
                )
                row = cursor.fetchone()
                if row is None:
                    return 0
                return int(row["play_count"])
        except sqlite3.Error as e:
            logger.error(f"获取播放次数失败: {e}", exc_info=True)
            return 0

    # ==================== 收藏 ====================

    def add_favorite(self, file_path, file_name, title, artist) -> bool:
        """添加收藏，返回 True 表示新增，False 表示已存在"""
        try:
            with self._lock:
                conn = self._get_conn()
                now = datetime.now().isoformat()
                cursor = conn.execute(
                    '''INSERT OR IGNORE INTO favorites
                       (file_path, file_name, title, artist, added_at)
                       VALUES (?, ?, ?, ?, ?)''',
                    (file_path, file_name, title, artist, now)
                )
                conn.commit()
                added = cursor.rowcount > 0
                if added:
                    logger.debug(f"已添加收藏: {file_path}")
                else:
                    logger.debug(f"收藏已存在，跳过: {file_path}")
                return added
        except sqlite3.Error as e:
            logger.error(f"添加收藏失败: {e}", exc_info=True)
            return False

    def remove_favorite(self, file_path) -> bool:
        """移除收藏，返回 True 表示成功删除"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "DELETE FROM favorites WHERE file_path = ?",
                    (file_path,)
                )
                conn.commit()
                removed = cursor.rowcount > 0
                if removed:
                    logger.debug(f"已移除收藏: {file_path}")
                else:
                    logger.debug(f"未找到收藏记录: {file_path}")
                return removed
        except sqlite3.Error as e:
            logger.error(f"移除收藏失败: {e}", exc_info=True)
            return False

    def is_favorite(self, file_path) -> bool:
        """判断是否已收藏"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT 1 FROM favorites WHERE file_path = ? LIMIT 1",
                    (file_path,)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"查询收藏状态失败: {e}", exc_info=True)
            return False

    def get_favorites(self) -> List[Dict[str, Any]]:
        """获取全部收藏列表"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM favorites ORDER BY added_at DESC"
                )
                return [self._row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取收藏列表失败: {e}", exc_info=True)
            return []

    def search_favorites(self, keyword) -> List[Dict[str, Any]]:
        """按关键词搜索收藏（匹配标题、艺术家、文件名）"""
        try:
            with self._lock:
                conn = self._get_conn()
                like = f"%{keyword}%"
                cursor = conn.execute(
                    '''SELECT * FROM favorites
                       WHERE title LIKE ? OR artist LIKE ? OR file_name LIKE ?
                       ORDER BY added_at DESC''',
                    (like, like, like)
                )
                return [self._row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"搜索收藏失败: {e}", exc_info=True)
            return []

    # ==================== 播放位置记忆 ====================

    def save_position(self, file_path, position_ms):
        """保存播放位置"""
        try:
            with self._lock:
                conn = self._get_conn()
                now = datetime.now().isoformat()
                conn.execute(
                    '''INSERT INTO playback_positions (file_path, position_ms, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(file_path) DO UPDATE SET
                           position_ms = excluded.position_ms,
                           updated_at = excluded.updated_at''',
                    (file_path, position_ms, now)
                )
                conn.commit()
                logger.debug(f"已保存播放位置 {file_path}: {position_ms}ms")
        except sqlite3.Error as e:
            logger.error(f"保存播放位置失败: {e}", exc_info=True)

    def get_position(self, file_path) -> int:
        """获取播放位置，无记录返回 0"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT position_ms FROM playback_positions WHERE file_path = ?",
                    (file_path,)
                )
                row = cursor.fetchone()
                if row is None:
                    return 0
                return int(row["position_ms"])
        except sqlite3.Error as e:
            logger.error(f"获取播放位置失败: {e}", exc_info=True)
            return 0

    def clear_position(self, file_path):
        """清除指定文件的播放位置记录"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "DELETE FROM playback_positions WHERE file_path = ?",
                    (file_path,)
                )
                conn.commit()
                logger.debug(f"已清除播放位置记录: {file_path}")
        except sqlite3.Error as e:
            logger.error(f"清除播放位置失败: {e}", exc_info=True)

    # ==================== 播放列表 ====================

    def create_playlist(self, name) -> int:
        """创建播放列表，返回新播放列表 ID；失败返回 -1"""
        try:
            with self._lock:
                conn = self._get_conn()
                now = datetime.now().isoformat()
                cursor = conn.execute(
                    "INSERT INTO playlists (name, created_at, updated_at) VALUES (?, ?, ?)",
                    (name, now, now)
                )
                conn.commit()
                playlist_id = cursor.lastrowid
                logger.info(f"已创建播放列表: {name} (id={playlist_id})")
                return int(playlist_id)
        except sqlite3.Error as e:
            logger.error(f"创建播放列表失败: {e}", exc_info=True)
            return -1

    def delete_playlist(self, playlist_id):
        """删除播放列表及其所有条目"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "DELETE FROM playlists WHERE id = ?",
                    (playlist_id,)
                )
                # playlist_items 通过外键 ON DELETE CASCADE 自动删除
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"已删除播放列表 id={playlist_id}")
                else:
                    logger.debug(f"未找到播放列表 id={playlist_id}")
        except sqlite3.Error as e:
            logger.error(f"删除播放列表失败: {e}", exc_info=True)

    def get_playlists(self) -> List[Dict[str, Any]]:
        """获取全部播放列表"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM playlists ORDER BY updated_at DESC"
                )
                return [self._row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取播放列表失败: {e}", exc_info=True)
            return []

    def add_to_playlist(self, playlist_id, file_path, file_name, title, artist):
        """添加歌曲到播放列表（已存在则跳过）"""
        try:
            with self._lock:
                conn = self._get_conn()
                now = datetime.now().isoformat()
                # 获取当前最大 position
                cursor = conn.execute(
                    "SELECT MAX(position) AS max_pos FROM playlist_items WHERE playlist_id = ?",
                    (playlist_id,)
                )
                row = cursor.fetchone()
                max_pos = row["max_pos"] if row is not None and row["max_pos"] is not None else -1
                position = max_pos + 1
                conn.execute(
                    '''INSERT OR IGNORE INTO playlist_items
                       (playlist_id, file_path, file_name, title, artist, position, added_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (playlist_id, file_path, file_name, title, artist, position, now)
                )
                conn.execute(
                    "UPDATE playlists SET updated_at = ? WHERE id = ?",
                    (now, playlist_id)
                )
                conn.commit()
                logger.debug(f"已添加到播放列表 {playlist_id}: {file_path}")
        except sqlite3.Error as e:
            logger.error(f"添加到播放列表失败: {e}", exc_info=True)

    def remove_from_playlist(self, playlist_id, file_path):
        """从播放列表移除歌曲"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "DELETE FROM playlist_items WHERE playlist_id = ? AND file_path = ?",
                    (playlist_id, file_path)
                )
                now = datetime.now().isoformat()
                conn.execute(
                    "UPDATE playlists SET updated_at = ? WHERE id = ?",
                    (now, playlist_id)
                )
                conn.commit()
                if cursor.rowcount > 0:
                    logger.debug(f"已从播放列表 {playlist_id} 移除: {file_path}")
                else:
                    logger.debug(f"未在播放列表 {playlist_id} 中找到: {file_path}")
        except sqlite3.Error as e:
            logger.error(f"从播放列表移除失败: {e}", exc_info=True)

    def get_playlist_items(self, playlist_id) -> List[Dict[str, Any]]:
        """获取播放列表中的全部歌曲（按 position 排序）"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY position ASC",
                    (playlist_id,)
                )
                return [self._row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取播放列表条目失败: {e}", exc_info=True)
            return []

    # ==================== 应用设置 ====================

    def set_setting(self, key, value):
        """设置应用配置项（键值对）"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    '''INSERT INTO app_settings (key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
                    (key, str(value))
                )
                conn.commit()
                logger.debug(f"已保存设置: {key}={value}")
        except sqlite3.Error as e:
            logger.error(f"保存设置失败: {e}", exc_info=True)

    def get_setting(self, key, default=None):
        """获取应用配置项，不存在时返回 default"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT value FROM app_settings WHERE key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                if row is None:
                    return default
                return row["value"]
        except sqlite3.Error as e:
            logger.error(f"获取设置失败: {e}", exc_info=True)
            return default

    # ==================== 资源释放 ====================

    def close(self):
        """关闭数据库连接"""
        try:
            with self._lock:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                    logger.info("数据库连接已关闭")
        except sqlite3.Error as e:
            logger.error(f"关闭数据库连接失败: {e}", exc_info=True)

    # ==================== 音乐收藏夹 ====================

    def create_music_folder(self, name: str, description: str = "",
                            cover_color: str = "#667EEA") -> int:
        """创建音乐收藏夹，返回 ID；失败返回 -1"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "INSERT INTO music_folders (name, description, cover_color) VALUES (?, ?, ?)",
                    (name, description, cover_color)
                )
                conn.commit()
                fid = cursor.lastrowid
                logger.info(f"已创建音乐收藏夹: {name} (id={fid})")
                return int(fid)
        except sqlite3.Error as e:
            logger.error(f"创建音乐收藏夹失败: {e}", exc_info=True)
            return -1

    def delete_music_folder(self, folder_id: int):
        """删除音乐收藏夹及其所有条目"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute("DELETE FROM music_folders WHERE id = ?", (folder_id,))
                conn.commit()
                logger.info(f"已删除音乐收藏夹 id={folder_id}")
        except sqlite3.Error as e:
            logger.error(f"删除音乐收藏夹失败: {e}", exc_info=True)

    def rename_music_folder(self, folder_id: int, new_name: str):
        """重命名收藏夹"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute("UPDATE music_folders SET name = ? WHERE id = ?",
                             (new_name, folder_id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"重命名收藏夹失败: {e}", exc_info=True)

    def get_music_folders(self) -> list:
        """获取所有音乐收藏夹"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    """SELECT f.*, COUNT(m.id) as item_count
                       FROM music_folders f
                       LEFT JOIN music_folder_items m ON f.id = m.folder_id
                       GROUP BY f.id
                       ORDER BY f.created_at DESC"""
                )
                return [self._row_to_dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取音乐收藏夹列表失败: {e}", exc_info=True)
            return []

    def add_to_music_folder(self, folder_id: int, file_path: str,
                            file_name: str, title: str = "",
                            artist: str = "", album: str = "",
                            duration: int = 0):
        """添加音频到收藏夹"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    """INSERT OR IGNORE INTO music_folder_items
                       (folder_id, file_path, file_name, title, artist, album, duration)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (folder_id, file_path, file_name, title, artist, album, duration)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"添加到收藏夹失败: {e}", exc_info=True)

    def remove_from_music_folder(self, folder_id: int, file_path: str):
        """从收藏夹移除音频"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "DELETE FROM music_folder_items WHERE folder_id = ? AND file_path = ?",
                    (folder_id, file_path)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"从收藏夹移除失败: {e}", exc_info=True)

    def get_music_folder_items(self, folder_id: int) -> list:
        """获取收藏夹内所有音频"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM music_folder_items WHERE folder_id = ? ORDER BY added_at DESC",
                    (folder_id,)
                )
                return [self._row_to_dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取收藏夹内容失败: {e}", exc_info=True)
            return []

    # ==================== 视频标签 ====================

    def add_video_tag(self, file_path: str, tag: str,
                      category: str = VIDEO_TAG_DEFAULT_CATEGORY) -> bool:
        """为视频添加标签（带分类），返回是否新增或更新"""
        try:
            with self._lock:
                conn = self._get_conn()
                cat = (category or VIDEO_TAG_DEFAULT_CATEGORY).strip() or VIDEO_TAG_DEFAULT_CATEGORY
                # 若 (file_path, tag) 已存在则更新分类，否则新增
                cursor = conn.execute(
                    '''INSERT INTO video_tags (file_path, tag, category)
                       VALUES (?, ?, ?)
                       ON CONFLICT(file_path, tag) DO UPDATE SET
                           category = excluded.category''',
                    (file_path, tag.strip(), cat)
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"添加视频标签失败: {e}", exc_info=True)
            return False

    def remove_video_tag(self, file_path: str, tag: str) -> bool:
        """移除视频标签，返回是否成功删除"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "DELETE FROM video_tags WHERE file_path = ? AND tag = ?",
                    (file_path, tag.strip())
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"移除视频标签失败: {e}", exc_info=True)
            return False

    def get_video_tags(self, file_path: str) -> List[Dict[str, Any]]:
        """获取视频的所有标签（含分类），返回 [{'tag', 'category'}, ...]"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT tag, category FROM video_tags WHERE file_path = ? ORDER BY added_at DESC",
                    (file_path,)
                )
                return [{"tag": row["tag"], "category": row["category"]}
                        for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取视频标签失败: {e}", exc_info=True)
            return []

    def get_all_video_tags(self) -> List[Dict[str, Any]]:
        """获取所有不重复的标签（含分类），返回 [{'tag', 'category'}, ...]"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT DISTINCT tag, category FROM video_tags ORDER BY category, tag"
                )
                return [{"tag": row["tag"], "category": row["category"]}
                        for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"获取所有标签失败: {e}", exc_info=True)
            return []

    def get_tags_grouped_by_category(self) -> Dict[str, List[str]]:
        """获取按分类分组的标签字典 {category: [tag, ...]}"""
        grouped: Dict[str, List[str]] = {}
        for item in self.get_all_video_tags():
            grouped.setdefault(item["category"], []).append(item["tag"])
        return grouped

    def get_videos_by_tag(self, tag: str) -> List[str]:
        """获取具有指定标签的所有视频路径"""
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT file_path FROM video_tags WHERE tag = ? ORDER BY added_at DESC",
                    (tag.strip(),)
                )
                return [row["file_path"] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"按标签获取视频失败: {e}", exc_info=True)
            return []

    def clear_video_tags(self, file_path: str):
        """清除视频的所有标签"""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute("DELETE FROM video_tags WHERE file_path = ?", (file_path,))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"清除视频标签失败: {e}", exc_info=True)

    def rename_file_path(self, old_path: str, new_path: str) -> bool:
        """
        当音频文件被移动/重命名后，同步更新所有表中的 file_path 引用。

        更新的表：
        - play_history (UNIQUE file_path)
        - favorites (UNIQUE file_path)
        - playback_positions (UNIQUE file_path)
        - playlist_items (playlist_id + file_path 联合唯一)
        - music_folder_items (folder_id + file_path 联合唯一)

        Args:
            old_path: 原文件路径
            new_path: 新文件路径

        Returns:
            是否更新成功（即使没有匹配记录也返回 True）
        """
        try:
            with self._lock:
                conn = self._get_conn()
                cursor = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 各表用 UPDATE + 冲突处理：
                # 如果新路径已存在（UNIQUE 冲突），就先删旧记录，保留新记录不覆盖
                for table, pkey_cols in [
                    ("play_history", ["file_path"]),
                    ("favorites", ["file_path"]),
                    ("playback_positions", ["file_path"]),
                ]:
                    # 先尝试直接更新
                    try:
                        cursor.execute(
                            f"UPDATE {table} SET file_path = ? WHERE file_path = ?",
                            (new_path, old_path)
                        )
                    except sqlite3.IntegrityError:
                        # 新路径已存在：删除旧路径记录，保留已有的新路径记录
                        cursor.execute(
                            f"DELETE FROM {table} WHERE file_path = ?",
                            (old_path,)
                        )

                # playlist_items：playlist_id + file_path 联合唯一
                try:
                    cursor.execute(
                        "UPDATE playlist_items SET file_path = ? WHERE file_path = ?",
                        (new_path, old_path)
                    )
                except sqlite3.IntegrityError:
                    cursor.execute(
                        "DELETE FROM playlist_items WHERE file_path = ?",
                        (old_path,)
                    )

                # music_folder_items：folder_id + file_path 联合唯一（无 updated_at 列）
                try:
                    cursor.execute(
                        "UPDATE music_folder_items SET file_path = ? WHERE file_path = ?",
                        (new_path, old_path)
                    )
                except sqlite3.IntegrityError:
                    cursor.execute(
                        "DELETE FROM music_folder_items WHERE file_path = ?",
                        (old_path,)
                    )

                conn.commit()
                logger.debug(f"文件路径重命名同步完成: {old_path} -> {new_path}")
                return True
        except sqlite3.Error as e:
            logger.error(f"重命名文件路径更新数据库失败: {e}", exc_info=True)
            return False


# ==================== 全局单例 ====================

_db_instance: Optional[Database] = None
_db_lock = threading.Lock()


def get_database(db_path: str = None) -> Database:
    """获取全局数据库单例（双重检查锁定，线程安全）"""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = Database(db_path)
    return _db_instance
