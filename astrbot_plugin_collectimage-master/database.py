import json
import os
import sqlite3
from datetime import datetime
from typing import Optional


class Database:
    def __init__(self, db_dir: str):
        self.db_path = os.path.join(db_dir, "collectimage.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def is_hash_exists(self, file_hash: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM images WHERE file_hash = ? LIMIT 1", (file_hash,))
        result = cursor.fetchone() is not None
        conn.close()
        return result

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
    ) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO images 
                   (file_hash, file_path, file_name, group_id, sender_id, timestamp, tags, character, description) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            conn.commit()
            conn.close()
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
        conn.close()
        return [dict(row) for row in rows]

    def search_by_tag(self, tag: str, limit: int = 50) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM images WHERE tags LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f'%"tag"%', limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def search_by_character(self, character: str, limit: int = 50) -> list:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM images WHERE character LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{character}%", limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_image_by_hash(self, file_hash: str) -> Optional[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM images WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_image_by_id(self, image_id: int) -> Optional[dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM images WHERE id = ?", (image_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_image(
        self,
        image_id: int,
        tags: Optional[dict] = None,
        character: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        try:
            conn = self._get_connection()
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
            conn.close()
            return True
        except Exception:
            return False

    def delete_image(self, image_id: int) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM images WHERE id = ?", (image_id,))
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def search_images(
        self,
        tag: str = None,
        character: str = None,
        description: str = None,
        group_id: str = None,
        limit: int = 50,
        offset: int = 0,
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
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])
        cursor.execute(
            f"SELECT * FROM images WHERE {where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def count_images(self) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM images")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def close(self):
        pass
