import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger


class Database:
    def __init__(self, db_dir: str):
        self.db_path = os.path.join(db_dir, "collectimage.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._phash_cache: dict[int, int] = {}  # image_id -> phash_int
        self._init_db()
        self._load_phash_cache()

    def _get_connection(self) -> sqlite3.Connection:
        """获取持久化数据库连接（WAL 模式，复用连接）"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path, check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _load_phash_cache(self):
        """加载所有 phash 到内存缓存，避免每次去重都全表扫描"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, phash FROM images WHERE phash IS NOT NULL AND phash != ''"
        )
        self._phash_cache.clear()
        for row in cursor.fetchall():
            try:
                self._phash_cache[row[0]] = int(row[1], 16)
            except (ValueError, TypeError):
                pass

    def _init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                group_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                tags TEXT,
                character TEXT,
                description TEXT,
                ai_detect TEXT,
                confirmed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE images ADD COLUMN ai_detect TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE images ADD COLUMN confirmed INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE images ADD COLUMN phash TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash)")

        self._init_alias_db(conn, cursor)

        conn.commit()

    def _init_alias_db(self, conn=None, cursor=None):
        """初始化别名表"""
        own_conn = conn is None
        if own_conn:
            conn = self._get_connection()
            cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS character_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias_type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                alias TEXT NOT NULL,
                UNIQUE(alias_type, original_name, alias)
            )
        """)

        if own_conn:
            conn.commit()

    def is_hash_exists(self, file_hash: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM images WHERE file_hash = ? LIMIT 1", (file_hash,))
        return cursor.fetchone() is not None

    def get_all_phashes(self) -> list:
        """获取所有非空的 phash 及对应 id"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, phash FROM images WHERE phash IS NOT NULL AND phash != ''")
        rows = cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    def find_similar_phash(self, phash: str, threshold: int = 10) -> Optional[dict]:
        """查找与给定 phash 汉明距离 <= threshold 的图片（使用内存缓存）"""
        if not phash:
            return None
        try:
            phash_int = int(phash, 16)
        except (ValueError, TypeError):
            return None
        for img_id, existing_int in self._phash_cache.items():
            distance = bin(phash_int ^ existing_int).count('1')
            if distance <= threshold:
                return self.get_image_by_id(img_id)
        return None

    def update_phash(self, image_id: int, phash: str) -> bool:
        """更新指定图片的 phash"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE images SET phash = ? WHERE id = ?", (phash, image_id))
            conn.commit()
            if phash and cursor.rowcount > 0:
                try:
                    self._phash_cache[image_id] = int(phash, 16)
                except (ValueError, TypeError):
                    pass
            return cursor.rowcount > 0
        except Exception:
            return False

    def get_images_without_phash(self, limit: int = 100) -> list:
        """获取没有 phash 的图片记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, file_path FROM images WHERE phash IS NULL OR phash = '' LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        return [{"id": row[0], "file_path": row[1]} for row in rows]

    def add_image(self, image_data: dict) -> bool:
        """从字典添加图片记录"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO images 
                   (file_hash, file_path, file_name, group_id, sender_id, timestamp, tags, character, description, ai_detect, confirmed, phash) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    image_data.get('file_hash'),
                    image_data.get('file_path'),
                    image_data.get('file_name'),
                    image_data.get('group_id'),
                    image_data.get('sender_id'),
                    image_data.get('timestamp'),
                    image_data.get('tags'),
                    image_data.get('character'),
                    image_data.get('description'),
                    image_data.get('ai_detect'),
                    image_data.get('confirmed', 0),
                    image_data.get('phash'),
                ),
            )
            conn.commit()
            phash = image_data.get('phash')
            if phash and cursor.lastrowid:
                try:
                    self._phash_cache[cursor.lastrowid] = int(phash, 16)
                except (ValueError, TypeError):
                    pass
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_image(
        self,
        file_hash: str,
        file_path: str,
        file_name: str,
        group_id: str,
        sender_id: str,
        timestamp: int,
        tags: Optional[dict] = None,
        character: Optional[str] = None,
        description: Optional[str] = None,
        ai_detect: Optional[str] = None,
        confirmed: int = 0,
        phash: Optional[str] = None,
    ) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO images 
                   (file_hash, file_path, file_name, group_id, sender_id, timestamp, tags, character, description, ai_detect, confirmed, phash) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_hash,
                    file_path,
                    file_name,
                    group_id,
                    sender_id,
                    timestamp,
                    json.dumps(tags, ensure_ascii=False) if tags else None,
                    character,
                    description,
                    ai_detect,
                    confirmed,
                    phash,
                ),
            )
            conn.commit()
            if phash and cursor.lastrowid:
                try:
                    self._phash_cache[cursor.lastrowid] = int(phash, 16)
                except (ValueError, TypeError):
                    pass
            return True
        except sqlite3.IntegrityError:
            return False

    def get_all_images(self, limit: int = 100, offset: int = 0) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM images ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def search_by_tag(self, tag: str, limit: int = 50) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM images WHERE tags LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f'%"{tag}"%', limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def search_by_character(self, character: str, limit: int = 50) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM images WHERE character LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{character}%", limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_image_by_hash(self, file_hash: str) -> Optional[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM images WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_image_by_id(self, image_id: int) -> Optional[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM images WHERE id = ?", (image_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_image(
        self,
        image_id: int,
        tags: Optional[dict] = None,
        character: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            updates = []
            params = []
            if tags is not None:
                updates.append("tags = ?")
                params.append(json.dumps(tags, ensure_ascii=False))
            if character is not None:
                updates.append("character = ?")
                params.append(character)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if not updates:
                return False
            params.append(image_id)
            cursor.execute(
                f"UPDATE images SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
            return True
        except Exception:
            return False

    def update_character(self, image_id: int, character: str) -> bool:
        """只更新 character 字段"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE images SET character = ? WHERE id = ?",
                (character, image_id),
            )
            conn.commit()
            return True
        except Exception:
            return False

    def update_confirmed(self, image_id: int, confirmed: int) -> bool:
        """更新确认状态"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE images SET confirmed = ? WHERE id = ?",
                (confirmed, image_id),
            )
            conn.commit()
            return True
        except Exception:
            return False

    def delete_image(self, image_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM images WHERE id = ?", (image_id,))
            conn.commit()
            self._phash_cache.pop(image_id, None)
            return True
        except Exception:
            return False

    def cleanup_missing_files(self) -> int:
        """清理数据库中有记录但文件不存在的条目，返回清理数量"""
        cleaned = 0
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, file_path FROM images")
            rows = cursor.fetchall()

            for row in rows:
                image_id = row[0]
                file_path = row[1]
                if file_path and not os.path.exists(file_path):
                    cursor.execute("DELETE FROM images WHERE id = ?", (image_id,))
                    self._phash_cache.pop(image_id, None)
                    cleaned += 1

            conn.commit()
        except Exception as e:
            logger.error(f"[CollectImage] 清理缺失文件失败: {e}")
        return cleaned

    def cleanup_orphaned_files(self, images_dir: str) -> int:
        """清理images目录下没有数据库记录的文件，返回清理数量"""
        cleaned = 0
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 获取所有数据库中的文件路径
            cursor.execute("SELECT file_path FROM images")
            db_paths = {row[0] for row in cursor.fetchall() if row[0]}

            # 扫描images目录
            if os.path.exists(images_dir):
                for filename in os.listdir(images_dir):
                    file_path = os.path.join(images_dir, filename)
                    if os.path.isfile(file_path) and file_path not in db_paths:
                        try:
                            os.remove(file_path)
                            cleaned += 1
                        except OSError as e:
                            logger.warning(f"[CollectImage] 删除孤立文件失败: {file_path}, {e}")
        except Exception as e:
            logger.error(f"[CollectImage] 清理孤立文件失败: {e}")
        return cleaned

    def search_images(
        self,
        tag: str = None,
        character: str = None,
        description: str = None,
        group_id: str = None,
        confirmed: int = None,
        limit: int = 50,
        offset: int = 0,
        random: bool = False,
    ) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        conditions = []
        params = []
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
        if character:
            conditions.append("character LIKE ?")
            params.append(f"%{character}%")
        if description:
            conditions.append("description LIKE ?")
            params.append(f"%{description}%")
        if group_id:
            conditions.append("group_id = ?")
            params.append(group_id)
        if confirmed is not None:
            conditions.append("confirmed = ?")
            params.append(confirmed)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        order_clause = "ORDER BY RANDOM()" if random else "ORDER BY timestamp DESC"
        params.extend([limit, offset])
        cursor.execute(
            f"SELECT * FROM images WHERE {where_clause} {order_clause} LIMIT ? OFFSET ?",
            params,
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def count_images(self, tag: str = None, character: str = None, description: str = None,
                     group_id: str = None, confirmed: int = None) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        conditions = []
        params = []
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
        if character:
            conditions.append("character LIKE ?")
            params.append(f"%{character}%")
        if description:
            conditions.append("description LIKE ?")
            params.append(f"%{description}%")
        if group_id:
            conditions.append("group_id = ?")
            params.append(group_id)
        if confirmed is not None:
            conditions.append("confirmed = ?")
            params.append(confirmed)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        cursor.execute(f"SELECT COUNT(*) FROM images WHERE {where_clause}", params)
        count = cursor.fetchone()[0]
        return count

    def get_stats(self, days: int = 7) -> dict:
        """获取统计信息"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 总数
        cursor.execute("SELECT COUNT(*) FROM images")
        total = cursor.fetchone()[0]

        # 已确认
        cursor.execute("SELECT COUNT(*) FROM images WHERE confirmed = 1")
        confirmed = cursor.fetchone()[0]

        # 未确认
        cursor.execute("SELECT COUNT(*) FROM images WHERE confirmed = 0")
        unconfirmed = cursor.fetchone()[0]

        # 今日新增
        today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        cursor.execute("SELECT COUNT(*) FROM images WHERE timestamp >= ?", (today_start,))
        today_new = cursor.fetchone()[0]

        # 每日新增趋势
        daily_data = []
        for i in range(days - 1, -1, -1):
            date = datetime.now() - timedelta(days=i)
            day_start = int(date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            day_end = int(date.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
            cursor.execute("SELECT COUNT(*) FROM images WHERE timestamp >= ? AND timestamp <= ?", (day_start, day_end))
            count = cursor.fetchone()[0]
            daily_data.append({
                "date": date.strftime("%Y-%m-%d"),
                "label": date.strftime("%m/%d"),
                "count": count
            })

        return {
            "total": total,
            "confirmed": confirmed,
            "unconfirmed": unconfirmed,
            "today_new": today_new,
            "daily": daily_data
        }

    def search_character_random(self, keyword: str, limit: int = 1) -> list:
        """模糊搜索角色(含作品)并随机选取"""
        conn = self._get_connection()
        cursor = conn.cursor()
        pattern = f"%{keyword}%"
        cursor.execute("""
            SELECT * FROM images 
            WHERE character LIKE ? OR ai_detect LIKE ?
            ORDER BY RANDOM() 
            LIMIT ?
        """, (pattern, pattern, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def search_all_random(self, keyword: str, limit: int = 1) -> list:
        """模糊搜索标签、描述和角色(含作品)并随机选取"""
        conn = self._get_connection()
        cursor = conn.cursor()
        pattern = f"%{keyword}%"
        cursor.execute("""
            SELECT * FROM images 
            WHERE tags LIKE ? OR description LIKE ? OR character LIKE ? OR ai_detect LIKE ?
            ORDER BY RANDOM() 
            LIMIT ?
        """, (pattern, pattern, pattern, pattern, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def add_alias(self, alias_type: str, original_name: str, alias: str) -> bool:
        """添加别名"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO character_aliases (alias_type, original_name, alias) VALUES (?, ?, ?)",
                (alias_type, original_name, alias)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False

    def get_all_aliases(self) -> list:
        """获取所有别名"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM character_aliases ORDER BY alias_type, original_name")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_aliases_by_type(self, alias_type: str) -> list:
        """按类型获取别名"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM character_aliases WHERE alias_type = ? ORDER BY original_name",
            (alias_type,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_alias(self, alias_id: int) -> bool:
        """删除别名"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM character_aliases WHERE id = ?", (alias_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False

    def search_alias(self, keyword: str) -> list:
        """搜索别名"""
        conn = self._get_connection()
        cursor = conn.cursor()
        pattern = f"%{keyword}%"
        cursor.execute(
            "SELECT * FROM character_aliases WHERE original_name LIKE ? OR alias LIKE ? ORDER BY alias_type, original_name",
            (pattern, pattern)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def import_aliases(self, aliases_data: list) -> int:
        """批量导入别名"""
        imported = 0
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for item in aliases_data:
                alias_type = item.get("alias_type", "character")
                original_name = item.get("original_name", "")
                alias = item.get("alias", "")
                if original_name and alias:
                    try:
                        cursor.execute(
                            "INSERT OR IGNORE INTO character_aliases (alias_type, original_name, alias) VALUES (?, ?, ?)",
                            (alias_type, original_name, alias)
                        )
                        if cursor.rowcount > 0:
                            imported += 1
                    except Exception as e:
                        logger.warning(f"[CollectImage] 导入别名失败: {original_name} -> {alias}, {e}")
            conn.commit()
        except Exception as e:
            logger.error(f"[CollectImage] 批量导入别名失败: {e}")
        return imported

    def get_alias_count(self) -> int:
        """获取别名总数"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM character_aliases")
        count = cursor.fetchone()[0]
        return count

    def get_original_names_by_alias(self, keyword: str, alias_type: str = None) -> list:
        """通过别名获取原始名称列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        pattern = f"%{keyword}%"

        if alias_type:
            cursor.execute(
                "SELECT DISTINCT original_name FROM character_aliases WHERE alias_type = ? AND alias LIKE ?",
                (alias_type, pattern)
            )
        else:
            cursor.execute(
                "SELECT DISTINCT original_name FROM character_aliases WHERE alias LIKE ?",
                (pattern,)
            )
        rows = cursor.fetchall()
        return [row[0] for row in rows]

    def get_work_original_names_by_alias(self, keyword: str) -> list:
        """通过别名获取作品原始名称列表"""
        return self.get_original_names_by_alias(keyword, alias_type="work")

    def _simplify_chinese(self, text: str) -> str:
        """简繁转换"""
        if not text:
            return text
        replacements = {
            '夢': '梦', '澤': '泽', '穂': '穗', '亜': '亚',
            '桜': '樱', '姫': '姬', '稲': '稻', '葉': '叶',
            '館': '馆', '黒': '黑', '麥': '麦', '開發': '开发',
            '圍': '围', '戰': '战', '裡': '里', '說': '说',
            '與': '与', '為': '为', '個': '个', '們': '们',
            '這': '这', '那': '那', '來': '来', '時': '时',
            '會': '会', '過': '过', '還': '还', '後': '后',
            '樓': '楼', '間': '间', '問': '问', '長': '长',
            '門': '门', '開': '开', '關': '关', '頭': '头',
            '臉': '脸', '話': '话', '聲': '声', '聽': '听',
            '寫': '写', '記': '记', '讓': '让', '給': '给',
            '対': '对', '錯': '错', '嗎': '吗', '呢': '呢',
            '吧': '吧', '嗎': '吗', '哦': '哦', '呀': '呀',
            '辺': '边', '巻': '卷', '査': '查', '対': '对',
            '歩': '步', '説': '说', '晩': '晚', '悪': '恶',
            '徳': '德', '経': '经', '営': '营', '処': '处',
            '挙': '举', '関': '关', '満': '满', '発': '发',
            '給': '给', '記': '记', '認': '认', '変': '变',
            '報': '报', '豊': '丰', '節': '节', '約': '约',
            '級': '级', '収': '收', '討': '讨', '講': '讲',
            '獄': '狱', '険': '险', '階': '阶', '帯': '带',
            '陸': '陆', '隊': '队', '陽': '阳', '陰': '阴',
            '毎': '每', '指示': '指示', '作成': '作成',
        }
        result = text
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result

    def _traditionalize(self, text: str) -> str:
        """繁化转换"""
        if not text:
            return text
        replacements = {
            '梦': '夢', '泽': '澤', '穗': '穂', '亚': '亜',
            '樱': '桜', '姬': '姫', '稻': '稲', '叶': '葉',
            '馆': '館', '黑': '黒', '麦': '麥', '开发': '開發',
            '围': '圍', '战': '戰', '里': '裡', '说': '說',
            '与': '與', '为': '為', '个': '個', '们': '們',
            '这': '這', '那': '那', '来': '來', '时': '時',
            '会': '會', '过': '過', '还': '還', '后': '後',
            '楼': '樓', '间': '間', '问': '問', '长': '長',
            '门': '門', '开': '開', '关': '關', '头': '頭',
            '脸': '臉', '话': '話', '声': '聲', '听': '聽',
            '写': '寫', '记': '記', '让': '讓', '给': '給',
            '对': '対', '错': '錯', '吗': '嗎', '呢': '呢',
        }
        result = text
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result

    def _build_search_conditions(self, keyword: str) -> tuple:
        """构建搜索条件和参数（去重优化）"""
        conditions = []
        params = []
        seen = set()

        def add_character_like(pattern: str):
            if pattern not in seen:
                seen.add(pattern)
                conditions.append("character LIKE ?")
                params.append(pattern)

        def add_multi_field_like(term: str):
            key = ("multi", term)
            if key not in seen:
                seen.add(key)
                pattern = f"%{term}%"
                conditions.append(
                    "(character LIKE ? OR ai_detect LIKE ? OR tags LIKE ? OR description LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])

        # 收集所有变体搜索词
        terms = [keyword]
        simplified = self._simplify_chinese(keyword)
        if simplified != keyword:
            terms.append(simplified)
        traditional = self._traditionalize(keyword)
        if traditional != keyword and traditional != simplified:
            terms.append(traditional)

        # 1. 每个变体：多字段模糊匹配 + JSON name 精确匹配
        for term in terms:
            add_multi_field_like(term)
            add_character_like(f'%"{term}"%')

        # 2. 每个变体：JSON work 字段匹配
        for term in terms:
            add_character_like(f'%"work": "%{term}%"%')

        # 3. 角色别名 → 原始名（含简繁变体）
        char_originals = []
        for orig in self.get_original_names_by_alias(keyword, "character")[:20]:
            char_originals.append(orig)
            s = self._simplify_chinese(orig)
            if s != orig:
                char_originals.append(s)
            t = self._traditionalize(orig)
            if t != orig and t != s:
                char_originals.append(t)

        for orig in char_originals:
            add_character_like(f"%{orig}%")
            add_character_like(f'%"{orig}"%')

        # 4. 作品别名 → 原始名（含简繁变体）
        for orig in self.get_work_original_names_by_alias(keyword)[:20]:
            add_character_like(f'%"work": "%{orig}%"%')
            s = self._simplify_chinese(orig)
            if s != orig:
                add_character_like(f'%"work": "%{s}%"%')

        return conditions, params

    def search_character_random_with_alias(self, keyword: str, limit: int = 1) -> list:
        """模糊搜索角色(含作品)并随机选取，支持别名匹配"""
        conditions, params = self._build_search_conditions(keyword)

        where_clause = " OR ".join(conditions)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM images WHERE {where_clause} ORDER BY RANDOM() LIMIT ?",
            params + [limit]
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def search_all_random_with_alias(self, keyword: str, limit: int = 1) -> list:
        """模糊搜索标签、描述和角色(含作品)并随机选取，支持别名匹配"""
        conditions, params = self._build_search_conditions(keyword)

        where_clause = " OR ".join(conditions)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM images WHERE {where_clause} ORDER BY RANDOM() LIMIT ?",
            params + [limit]
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def search_with_alias(self, keyword: str, limit: int = 50, offset: int = 0,
                          confirmed: int = None) -> tuple:
        conditions, params = self._build_search_conditions(keyword)
        where_clause = " OR ".join(conditions)
        if confirmed is not None:
            where_clause = f"({where_clause}) AND confirmed = ?"
            params.append(confirmed)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM images WHERE {where_clause}", params)
        total = cursor.fetchone()[0]
        query_params = params + [limit, offset]
        cursor.execute(
            f"SELECT * FROM images WHERE {where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            query_params
        )
        return [dict(row) for row in cursor.fetchall()], total

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._phash_cache.clear()
